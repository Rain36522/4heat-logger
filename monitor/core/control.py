"""Commands sent to the heating, and the weekly clock that decides when it runs (no Django).

Clock rules (decided with the user):
  - a slot runs from a start (day + time) to an end (day + time), every week, e.g.
    Monday 05:00 -> Friday 19:00; a slot without day repeats every day, e.g. 05:00 -> 21:00;
  - days off (holidays, leave) stop the heating for the whole day, even inside a slot;
  - the clock only acts when the wanted state changes (start or end of a slot, start or end
    of a day off), so a manual on/off from the web page or the bot stays until the next change.
"""

from __future__ import annotations

import time as clock
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from fourheat_logger.config import (
    BOILER_TARGET_ID,
    BOILER_TARGET_MAX_ID,
    BOILER_TARGET_MIN_ID,
    TURN_OFF_ID,
    TURN_ON_ID,
)
from fourheat_logger.module_client import ModuleError
from fourheat_logger.protocol import command_item

DAY_NAMES = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
DAY_MINUTES = 24 * 60
WEEK_MINUTES = 7 * DAY_MINUTES

# Used when the module does not send its own limits (B20005 / B20006).
DEFAULT_TARGET_RANGE = (30, 75)


# --- clock ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Slot:
    """start_day / end_day: 0 = Monday ... 6 = Sunday; both None = every day."""

    start_day: int | None
    start: time
    end_day: int | None
    end: time

    @property
    def every_day(self) -> bool:
        return self.start_day is None

    def describe(self) -> str:
        if self.every_day:
            return f"tous les jours {self.start:%H:%M} → {self.end:%H:%M}"
        return f"{DAY_NAMES[self.start_day]} {self.start:%H:%M} → {DAY_NAMES[self.end_day]} {self.end:%H:%M}"


@dataclass(frozen=True)
class DayOff:
    first: date
    last: date


def _minutes(day: int, moment: time) -> int:
    return day * DAY_MINUTES + moment.hour * 60 + moment.minute


def slot_active(slot: Slot, moment: datetime) -> bool:
    """True when `moment` is inside the slot (start included, end excluded).

    An end equal to the start means a full period (24 h for a daily slot, a week otherwise).
    """
    if slot.every_day:
        period, now = DAY_MINUTES, _minutes(0, moment.time())
        start, end = _minutes(0, slot.start), _minutes(0, slot.end)
    else:
        period, now = WEEK_MINUTES, _minutes(moment.weekday(), moment.time())
        start, end = _minutes(slot.start_day, slot.start), _minutes(slot.end_day, slot.end)
    length = (end - start) % period or period
    return (now - start) % period < length


def is_day_off(days_off: list[DayOff], day: date) -> bool:
    return any(off.first <= day <= off.last for off in days_off)


def wanted_on(moment: datetime, slots: list[Slot], days_off: list[DayOff]) -> bool:
    if is_day_off(days_off, moment.date()):
        return False
    return any(slot_active(slot, moment) for slot in slots)


def next_change(
    moment: datetime, slots: list[Slot], days_off: list[DayOff], horizon_days: int = 15
) -> tuple[datetime, bool] | None:
    """(when, wanted state) of the next change after `moment`, or None within the horizon.

    The wanted state can only change at a slot boundary or at midnight (days off), so only
    those instants are tested.
    """
    current = wanted_on(moment, slots, days_off)
    candidates = set()
    for offset in range(horizon_days + 1):
        day = moment.date() + timedelta(days=offset)
        candidates.add(datetime.combine(day, time.min))
        for slot in slots:
            candidates.add(datetime.combine(day, slot.start))
            candidates.add(datetime.combine(day, slot.end))
    for candidate in sorted(c for c in candidates if c > moment):
        state = wanted_on(candidate, slots, days_off)
        if state != current:
            return candidate, state
    return None


def describe_change(change: tuple[datetime, bool] | None) -> str:
    if change is None:
        return "aucun changement prévu dans les 15 prochains jours"
    when, on = change
    return f"{DAY_NAMES[when.weekday()]} {when:%d.%m à %H:%M} → {'marche' if on else 'arrêt'}"


# --- commands ------------------------------------------------------------------------


class ControlError(Exception):
    """A command could not be sent or confirmed; the message is shown to the user."""


class TryAgain(ControlError):
    """The module did not answer or did not confirm: worth another attempt later."""


class Refused(ControlError):
    """The command itself is wrong (target out of range): another attempt would not help."""


class HeatingControl:
    """One attempt of on / off or boiler target. No retry here: the queue retries the whole
    command later (see run_pilot), because the module drops out when it is queried too often.
    For the same reason, two connections of one attempt are spaced by `gap` seconds."""

    def __init__(self, client, gap: float = 5.0, read_back_delay: float = 10.0, sleep=clock.sleep) -> None:
        self._client = client
        self._gap = gap
        self._read_back_delay = read_back_delay
        self._sleep = sleep

    def turn_on(self) -> str:
        self._talk(lambda: self._client.send_command(command_item("J", TURN_ON_ID, 1)))
        return "Marche envoyée au chauffage."

    def turn_off(self) -> str:
        self._talk(lambda: self._client.send_command(command_item("J", TURN_OFF_ID, 1)))
        return "Arrêt envoyé au chauffage (extinction puis arrêt)."

    def set_boiler_target(self, value: int) -> str:
        """Write the boiler target after checking it against the module's own limits,
        then read it back: the command is only reported as done once the module shows it.
        Safe to repeat: an attempt that finds the value already written just says so."""
        values = self._talk(self._client.read_values)
        low, high = target_range(values)
        if not low <= value <= high:
            raise Refused(f"Consigne {value} °C refusée : elle doit être entre {low} et {high} °C.")
        before = values.get(BOILER_TARGET_ID)
        if before == value:
            return f"La consigne chaudière est à {value} °C."

        self._sleep(self._gap)
        self._talk(lambda: self._client.send_command(command_item("B", BOILER_TARGET_ID, value)))
        self._sleep(self._read_back_delay)
        after = self._talk(self._client.read_values).get(BOILER_TARGET_ID)
        if after != value:
            raise TryAgain(f"Consigne envoyée, mais le module indique toujours {after} °C.")
        return f"Consigne chaudière : {before} → {value} °C."

    @staticmethod
    def _talk(action):
        try:
            return action()
        except ModuleError as error:
            raise TryAgain(f"Module injoignable ou réponse inattendue ({error}).") from error


# --- queue ---------------------------------------------------------------------------

RETRY_EVERY = timedelta(seconds=20)
GIVE_UP_AFTER = timedelta(minutes=5)
# The collector reads the module every 60 s. A command starts between COLLECTOR_QUIET_AFTER
# and COLLECTOR_QUIET_UNTIL after its last reading, so both never query the module together.
COLLECTOR_QUIET_AFTER = timedelta(seconds=10)
COLLECTOR_QUIET_UNTIL = timedelta(seconds=35)
# Last reading older than this: the collector is not reading regularly, no window to wait for.
COLLECTOR_STALE_AFTER = timedelta(seconds=90)


def collector_allows(now: datetime, last_reading: datetime | None) -> bool:
    """True when a command may talk to the module now without meeting a collector read."""
    if last_reading is None:
        return True
    since = now - last_reading
    if since >= COLLECTOR_STALE_AFTER or since < timedelta(0):
        return True
    return COLLECTOR_QUIET_AFTER <= since <= COLLECTOR_QUIET_UNTIL


def next_try(created: datetime, now: datetime) -> datetime | None:
    """When to try a failed command again, or None when it is time to give up."""
    retry_at = now + RETRY_EVERY
    return retry_at if retry_at - created <= GIVE_UP_AFTER else None


def target_range(values: dict[str, int]) -> tuple[int, int]:
    """Allowed boiler target range: the module's limits when they look sane, else the default."""
    low, high = values.get(BOILER_TARGET_MIN_ID), values.get(BOILER_TARGET_MAX_ID)
    if low is None or high is None or not 0 < low < high <= 90:
        return DEFAULT_TARGET_RANGE
    return low, high
