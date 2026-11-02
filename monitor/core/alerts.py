"""Defect alerts: a small state machine plus the Telegram bot calls (no Django).

Rules (decided with the user):
  - a defect is any error code other than 0;
  - it is confirmed after CONFIRM_READINGS consecutive readings with the same code,
    so a single bad read does not alert;
  - one message per change of confirmed code (not one per minute);
  - a "resolved" message when the code goes back to 0.
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from dataclasses import dataclass, replace
from datetime import datetime, timedelta

import pandas as pd

from .readings import EPISODE_MAX_GAP_S, find_startups, last_valid, minutes_since_startup

CONFIRM_READINGS = 2


@dataclass
class AlertState:
    """What the alerter remembers between two runs."""

    active_code: int = 0  # confirmed defect currently open (0 = none)
    active_since: datetime | None = None
    last_seen: datetime | None = None  # last reading that still showed the active defect
    pending_code: int | None = None  # candidate code waiting for confirmation
    pending_count: int = 0
    pending_since: datetime | None = None
    last_processed: datetime | None = None  # timestamp of the last reading handled


def process_readings(
    frame: pd.DataFrame,
    state: AlertState,
    state_names: dict[int, str] | None = None,
    error_names: dict[int, str] | None = None,
    first_run_lookback_min: float = 10,
) -> tuple[list[str], AlertState]:
    """Handle the readings newer than state.last_processed.

    Returns the messages to send and the new state. Nothing is sent here, and the
    given state is not modified, so the caller can drop the result if sending fails.
    On the very first run only the last few minutes are looked at, never the whole history.
    """
    state = replace(state)
    state_names = state_names or {}
    error_names = error_names or {}

    valid = frame.dropna(subset=["error"])
    if valid.empty:
        return [], state
    if state.last_processed is None:
        cutoff = valid["timestamp"].iloc[-1] - timedelta(minutes=first_run_lookback_min)
        rows = valid[valid["timestamp"] >= cutoff]
    else:
        rows = valid[valid["timestamp"] > state.last_processed]
    if rows.empty:
        return [], state

    startups = find_startups(frame)
    messages: list[str] = []
    previous = state.last_processed

    for row in rows.itertuples(index=False):
        moment = row.timestamp.to_pydatetime()
        code = int(row.error)

        if previous is not None and (moment - previous).total_seconds() > EPISODE_MAX_GAP_S:
            state.pending_code, state.pending_count = None, 0  # the logger paused: start over
        previous = moment

        if code == state.active_code:
            state.last_seen = moment
            state.pending_code, state.pending_count = None, 0
            continue

        if code == state.pending_code:
            state.pending_count += 1
        else:
            state.pending_code, state.pending_count, state.pending_since = code, 1, moment
        if state.pending_count < CONFIRM_READINGS:
            continue

        # The new code is confirmed.
        if code != 0:
            messages.append(
                format_defect(row, code, state.pending_since, state.active_code, state_names, error_names, startups)
            )
            state.active_code, state.active_since, state.last_seen = code, state.pending_since, moment
        else:
            messages.append(format_resolved(state, state.pending_since, error_names))
            state.active_code, state.active_since, state.last_seen = 0, None, None
        state.pending_code, state.pending_count, state.pending_since = None, 0, None

    state.last_processed = previous
    return messages, state


def _named(code: int, names: dict[int, str]) -> str:
    return f"{code} ({names[code]})" if code in names else str(code)


def _number(value, decimals: int = 0) -> str:
    return "?" if value is None or pd.isna(value) else f"{value:.{decimals}f}"


def format_duration(minutes: float) -> str:
    minutes = int(round(minutes))
    if minutes < 60:
        return f"{minutes} min"
    hours, rest = divmod(minutes, 60)
    return f"{hours} h {rest:02d}" if rest else f"{hours} h"


def format_defect(row, code, since, previous_code, state_names, error_names, startups) -> str:
    lines = [f"DÉFAUT chauffage : code {_named(code, error_names)}"]
    if previous_code:
        lines[0] += f" (remplace le défaut {previous_code})"
    lines.append(f"Depuis {since:%d.%m %H:%M} (confirmé sur {CONFIRM_READINGS} lectures)")

    state = None if pd.isna(row.state) else int(row.state)
    state_text = "?" if state is None else _named(state, state_names)
    lines.append(
        f"État {state_text}, chaudière {_number(row.boiler_temp)} °C "
        f"(consigne {_number(row.boiler_target_temp)}), fumées {_number(row.exhaust_temp)} °C, "
        f"O₂ {_number(row.oxygen_percent, 1)} %"
    )
    since_start = minutes_since_startup(startups, pd.Timestamp(since))
    if since_start is not None:
        lines.append(f"{format_duration(since_start)} après le démarrage")
    return "\n".join(lines)


def format_resolved(state: AlertState, resumed_at: datetime, error_names) -> str:
    name = _named(state.active_code, error_names)
    observed = format_duration((state.last_seen - state.active_since).total_seconds() / 60)
    silent_s = (resumed_at - state.last_seen).total_seconds()
    if silent_s > EPISODE_MAX_GAP_S:
        return (
            f"Défaut {name} : plus de données depuis {state.last_seen:%d.%m %H:%M} "
            f"(chauffage arrêté ?), durée observée {observed}. "
            f"Reprise à {resumed_at:%d.%m %H:%M} sans défaut."
        )
    return f"Défaut {name} terminé à {resumed_at:%H:%M}, durée {observed}."


def format_status(
    frame: pd.DataFrame,
    now: datetime,
    state_names: dict[int, str] | None = None,
    error_names: dict[int, str] | None = None,
    live_max_age_s: float = 180,
) -> str:
    """Answer to /status: the last reading, each value taken from its last non-empty cell."""
    if frame.empty:
        return "Aucune mesure disponible."
    state_names = state_names or {}
    error_names = error_names or {}

    def latest(column):
        return last_valid(frame, column)[0]

    last_stamp = frame["timestamp"].iloc[-1].to_pydatetime()
    age_s = (now - last_stamp).total_seconds()
    age = "à l'instant" if age_s < 60 else f"il y a {format_duration(age_s / 60)}"
    lines = [f"Dernière mesure : {last_stamp:%d.%m %H:%M} ({age})"]
    if age_s > live_max_age_s:
        lines.append("Plus de données récentes (chauffage ou logger arrêté ?)")

    state, error = latest("state"), latest("error")
    state_text = "?" if state is None else _named(int(state), state_names)
    if error is None:
        error_text = "défaut ?"
    elif error == 0:
        error_text = "aucun défaut"
    else:
        error_text = f"DÉFAUT code {_named(int(error), error_names)}"
    lines.append(f"État {state_text}, {error_text}")
    lines.append(
        f"Chaudière {_number(latest('boiler_temp'))} °C (consigne {_number(latest('boiler_target_temp'))}), "
        f"fumées {_number(latest('exhaust_temp'))} °C, O₂ {_number(latest('oxygen_percent'), 1)} %"
    )
    return "\n".join(lines)


def is_status_command(update: dict, chat_id: str) -> bool:
    """True for a /status (or /status@BotName) message coming from the configured chat only."""
    message = update.get("message") or {}
    if str(message.get("chat", {}).get("id")) != str(chat_id):
        return False
    words = (message.get("text") or "").split()
    return bool(words) and words[0].split("@")[0].lower() == "/status"


def get_telegram_updates(token: str, offset: int | None = None, wait: float = 0) -> list[dict]:
    """Messages sent to the bot (long polling: waits up to `wait` s for one). Raises on any failure."""
    params = {"timeout": int(wait), "allowed_updates": '["message"]'}
    if offset is not None:
        params["offset"] = offset
    url = f"https://api.telegram.org/bot{token}/getUpdates?{urllib.parse.urlencode(params)}"
    with urllib.request.urlopen(url, timeout=wait + 10) as response:
        data = json.load(response)
    if not data.get("ok"):
        raise RuntimeError(f"Telegram refused getUpdates: {data.get('description')}")
    return data["result"]


def send_telegram(token: str, chat_id: str, text: str, timeout: float = 10) -> None:
    """Send a plain-text message with the Telegram Bot API. Raises on any failure."""
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    body = urllib.parse.urlencode({"chat_id": chat_id, "text": text}).encode()
    request = urllib.request.Request(url, data=body, method="POST")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        if response.status != 200:
            raise RuntimeError(f"Telegram answered HTTP {response.status}")
