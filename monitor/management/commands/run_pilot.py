"""Pilot: the only part of the app that talks to the module (besides the collector's reads).

    python manage.py run_pilot            # loops forever (Docker service "pilote")
    python manage.py run_pilot --once     # one pass, for a test

Each pass: the clock may queue an on / off (monitor.heating.run_clock), then the oldest due
command gets one attempt (monitor.heating.run_next). Failed attempts are retried every 20 s
for 5 min; attempts wait for a quiet moment between two readings of the collector.
"""

import logging
import time
from datetime import datetime

from django.core.management.base import BaseCommand

from monitor.heating import last_collector_reading, run_clock, run_next

logger = logging.getLogger(__name__)

PAUSE_AFTER_ATTEMPT_S = 10  # the module drops out when it is queried too often


def run_once(now: datetime):
    """One pass. Returns the command attempted, or None."""
    queued = run_clock(now)
    if queued:
        logger.info("Horloge : %s", queued)
    command = run_next(now, last_collector_reading())
    if command is not None:
        logger.info("%s, essai %d : %s (%s)", command.describe(), command.attempts,
                    command.get_status_display(), command.detail)
    return command


class Command(BaseCommand):
    help = "Envoie au chauffage les commandes en attente (page web, Telegram, horloge), une à la fois."

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true", help="Un seul passage puis quitte")
        parser.add_argument("--interval", type=int, default=5, help="Secondes entre deux passages (défaut : 5)")

    def handle(self, *args, **options):
        if options["once"]:
            command = run_once(datetime.now())
            self.stdout.write(f"{command}: {command.detail}" if command else "Rien à envoyer.")
            return

        self.stdout.write(f"Pilote : file de commandes vérifiée toutes les {options['interval']} s.")
        while True:
            pause = options["interval"]
            try:
                if run_once(datetime.now()) is not None:
                    pause = max(pause, PAUSE_AFTER_ATTEMPT_S)
            except Exception:  # keep running whatever happens (database locked, CSV being written...)
                logger.exception("Passage du pilote échoué, nouvel essai au prochain tour")
            time.sleep(pause)
