"""Watch the CSV and send a Telegram message when a defect appears or goes away.

    python manage.py run_alerts            # loops forever (Docker service "telegram-com")
    python manage.py run_alerts --once     # one pass, for a cron job or a test

TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must be set in the environment.
The state is saved only after the messages were sent: if Telegram is unreachable,
the same messages are tried again on the next pass instead of being lost.

In the loop, the bot also answers /status with the last reading. Only messages from
TELEGRAM_CHAT_ID are answered, and commands sent while the service was stopped are ignored.
"""

import logging
import time
from datetime import datetime

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from monitor.core import alerts
from monitor.core import readings as rd
from monitor.models import AlertState, CodeLabel

logger = logging.getLogger(__name__)

STATE_FIELDS = (
    "active_code", "active_since", "last_seen",
    "pending_code", "pending_count", "pending_since", "last_processed",
)
MAX_POLL_S = 50  # Telegram long polling: stay well under proxies' idle timeouts


def to_core(row: AlertState) -> alerts.AlertState:
    return alerts.AlertState(**{name: getattr(row, name) for name in STATE_FIELDS})


def save_core(row: AlertState, state: alerts.AlertState) -> None:
    for name in STATE_FIELDS:
        setattr(row, name, getattr(state, name))
    row.save()


def run_once(send) -> int:
    """One pass. `send(text)` raises on failure. Returns the number of messages sent."""
    frame = rd.load_readings(settings.HEATING_CSV_PATH)
    row = AlertState.load()
    messages, new_state = alerts.process_readings(
        frame,
        to_core(row),
        CodeLabel.labels(CodeLabel.Kind.STATE),
        CodeLabel.labels(CodeLabel.Kind.ERROR),
    )
    for text in messages:
        send(text)
    save_core(row, new_state)
    return len(messages)


def status_text() -> str:
    return alerts.format_status(
        rd.load_readings(settings.HEATING_CSV_PATH),
        datetime.now(),
        CodeLabel.labels(CodeLabel.Kind.STATE),
        CodeLabel.labels(CodeLabel.Kind.ERROR),
        settings.STATUS_LIVE_MAX_AGE_S,
    )


def skip_old_commands(token) -> int | None:
    """Offset just after the last pending update, so a restart does not answer stale commands."""
    updates = alerts.get_telegram_updates(token, offset=-1)
    return updates[-1]["update_id"] + 1 if updates else None


def answer_commands(token, chat_id, offset, wait, send) -> int | None:
    """Wait up to `wait` s for messages, answer /status, return the next offset.

    If sending fails, the exception goes up and the caller keeps the old offset,
    so the same command is answered on the next try.
    """
    for update in alerts.get_telegram_updates(token, offset, wait):
        if alerts.is_status_command(update, chat_id):
            send(status_text())
        offset = update["update_id"] + 1
    return offset


class Command(BaseCommand):
    help = "Envoie une alerte Telegram à l'apparition et à la disparition d'un défaut, et répond à /status."

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true", help="Un seul passage puis quitte (sans répondre à /status)")
        parser.add_argument("--interval", type=int, default=60, help="Secondes entre deux passages (défaut : 60)")

    def handle(self, *args, **options):
        token, chat_id = settings.TELEGRAM_BOT_TOKEN, settings.TELEGRAM_CHAT_ID
        if not token or not chat_id:
            raise CommandError("TELEGRAM_BOT_TOKEN et TELEGRAM_CHAT_ID doivent être définis.")

        def send(text):
            alerts.send_telegram(token, chat_id, text)

        if options["once"]:
            sent = run_once(send)
            self.stdout.write(f"{sent} message(s) envoyé(s).")
            return

        self.stdout.write(f"Surveillance de {settings.HEATING_CSV_PATH} toutes les {options['interval']} s.")
        try:
            offset = skip_old_commands(token)
        except Exception:
            logger.exception("Lecture des commandes Telegram impossible au démarrage")
            offset = None
        next_pass = 0.0
        while True:
            if time.monotonic() >= next_pass:
                try:
                    sent = run_once(send)
                    if sent:
                        logger.info("%d message(s) envoyé(s)", sent)
                except Exception:  # keep watching whatever happens (CSV being written, network down...)
                    logger.exception("Passage d'alerte échoué, nouvel essai au prochain tour")
                next_pass = time.monotonic() + options["interval"]

            # Waiting for Telegram messages replaces the sleep between two passes.
            wait = min(MAX_POLL_S, max(1, next_pass - time.monotonic()))
            try:
                offset = answer_commands(token, chat_id, offset, wait, send)
            except Exception:
                logger.exception("Lecture des commandes Telegram échouée")
                time.sleep(max(0, next_pass - time.monotonic()))
