"""Watch the CSV and send a Telegram message when a defect appears or goes away.

    python manage.py run_alerts            # loops forever (Docker service "telegram-com")
    python manage.py run_alerts --once     # one pass, for a cron job or a test

TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must be set in the environment.
The state is saved only after the messages were sent: if Telegram is unreachable,
the same messages are tried again on the next pass instead of being lost.

In the loop, the bot also answers commands (see HELP): last reading, on / off, boiler
target, clock. Only messages from TELEGRAM_CHAT_ID are answered, and commands sent while
the service was stopped are ignored (an old /arret must not switch the heating off later).
"""

import logging
import time
from datetime import datetime

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from monitor.core import alerts
from monitor.core import readings as rd
from monitor.heating import Action, Source, clock_summary, enqueue
from monitor.models import AlertState, CodeLabel

logger = logging.getLogger(__name__)

HELP = (
    "Commandes :\n"
    "/status : dernière mesure\n"
    "/marche : allumer le chauffage\n"
    "/arret : éteindre le chauffage\n"
    "/consigne 70 : consigne chaudière en °C\n"
    "/horloge : état de l'horloge et prochain changement"
)

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


def queued(action, value=None) -> str:
    command = enqueue(action, Source.TELEGRAM, value)
    return f"{command.describe()} : commande reçue, je te donne le résultat dès qu'elle est passée."


def reply(name: str, args: list[str]) -> str:
    """Answer to one command. Heating commands only go into the queue: the pilot service
    sends them and reports the result in a second message."""
    if name == "status":
        return status_text()
    if name == "marche":
        return queued(Action.ON)
    if name == "arret":
        return queued(Action.OFF)
    if name == "consigne":
        if len(args) != 1 or not args[0].isdigit():
            return "Indique la consigne en °C, par exemple : /consigne 70"
        return queued(Action.TARGET, int(args[0]))
    if name == "horloge":
        return clock_summary(datetime.now())
    return HELP


def answer_commands(token, chat_id, offset, wait, send) -> int | None:
    """Wait up to `wait` s for messages, answer the commands, return the next offset.

    The offset moves past each update before it is handled: if sending the answer fails,
    a heating command is not queued a second time.
    """
    for update in alerts.get_telegram_updates(token, offset, wait):
        offset = update["update_id"] + 1
        command = alerts.parse_command(update, chat_id)
        if command is not None:
            try:
                send(reply(*command))
            except Exception:
                logger.exception("Réponse à /%s échouée", command[0])
    return offset


class Command(BaseCommand):
    help = "Envoie une alerte Telegram à l'apparition et à la disparition d'un défaut, et répond aux commandes."

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true", help="Un seul passage puis quitte (sans répondre aux commandes)")
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
