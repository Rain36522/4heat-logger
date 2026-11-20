"""Command queue to the heating: the web page, the bot and the clock add commands here,
the pilot service (python manage.py run_pilot) sends them one at a time.

A failed attempt is tried again every RETRY_EVERY until GIVE_UP_AFTER (monitor.core.control),
and attempts wait for a quiet moment between two readings of the collector.
"""

import logging
from datetime import datetime, timedelta

from django.conf import settings

from fourheat_logger.module_client import FourHeatClient

from .core import alerts, control
from .core import readings as rd
from .models import ClockState, CommandLog, DayOff, ScheduleSlot

logger = logging.getLogger(__name__)

Action = CommandLog.Action
Source = CommandLog.Source
Status = CommandLog.Status

# Commands that replace each other while still waiting: the last wish wins.
SAME_KIND = {Action.ON: (Action.ON, Action.OFF), Action.OFF: (Action.ON, Action.OFF), Action.TARGET: (Action.TARGET,)}


def heating_control() -> control.HeatingControl:
    client = FourHeatClient(settings.FOURHEAT_HOST, settings.FOURHEAT_PORT, probe_timeout=3.0, read_timeout=10.0)
    return control.HeatingControl(client)


def notify(text: str) -> None:
    """Telegram message when the bot is configured; a lost notice is only logged."""
    token, chat_id = settings.TELEGRAM_BOT_TOKEN, settings.TELEGRAM_CHAT_ID
    if not token or not chat_id:
        return
    try:
        alerts.send_telegram(token, chat_id, text)
    except Exception:
        logger.exception("Notification Telegram échouée")


# --- queue ---------------------------------------------------------------------------


def enqueue(action: str, source: str, value: int | None = None) -> CommandLog:
    """Add a command; a waiting command of the same kind is replaced by this one."""
    now = datetime.now()
    CommandLog.objects.filter(status=Status.PENDING, action__in=SAME_KIND[action]).update(
        status=Status.CANCELLED, finished_at=now, detail="Remplacée par une commande plus récente."
    )
    return CommandLog.objects.create(source=source, action=action, value=value, next_try_at=now)


def last_collector_reading() -> datetime | None:
    frame = rd.load_readings(settings.HEATING_CSV_PATH)
    return None if frame.empty else frame["timestamp"].iloc[-1].to_pydatetime()


def run_next(now: datetime, last_reading: datetime | None, heating=None) -> CommandLog | None:
    """Make one attempt of the oldest due command, if the collector leaves room for it
    (`last_reading`: time of its last CSV row). Returns the command when an attempt was made."""
    command = (
        CommandLog.objects.filter(status=Status.PENDING, next_try_at__lte=now).order_by("timestamp", "id").first()
    )
    if command is None or not control.collector_allows(now, last_reading):
        return None

    heating = heating or heating_control()
    command.attempts += 1
    try:
        if command.action == Action.ON:
            text = heating.turn_on()
        elif command.action == Action.OFF:
            text = heating.turn_off()
        else:
            text = heating.set_boiler_target(command.value)
        command.status, command.next_try_at = Status.DONE, None
    except control.TryAgain as error:
        text = str(error)
        command.next_try_at = control.next_try(command.timestamp, datetime.now())
        if command.next_try_at is None:
            command.status = Status.FAILED
            text = f"Abandon après {command.attempts} essais : {text}"
    except control.Refused as error:
        text = str(error)
        command.status, command.next_try_at = Status.FAILED, None

    command.detail = text[:300]
    if command.status != Status.PENDING:
        command.finished_at = datetime.now()
    command.save()
    _report(command)
    return command


def _report(command: CommandLog) -> None:
    """Bot commands get their result; the clock reports its own successes and failures."""
    if command.source != Source.TELEGRAM or command.status == Status.PENDING:
        return
    prefix = "" if command.status == Status.DONE else "ÉCHEC : "
    notify(f"{command.describe()} : {prefix}{command.detail}")


# --- clock ---------------------------------------------------------------------------


def clock_plan():
    """(slots, days off) of the clock, as plain core objects."""
    slots = [slot.as_core() for slot in ScheduleSlot.objects.all()]
    days_off = [day.as_core() for day in DayOff.objects.all()]
    return slots, days_off


def clock_summary(now) -> str:
    state = ClockState.load()
    if not state.enabled:
        return "Horloge désactivée."
    slots, days_off = clock_plan()
    if not slots:
        return "Horloge active, mais aucune plage horaire n'est définie."
    current = "marche" if control.wanted_on(now, slots, days_off) else "arrêt"
    return (
        f"Horloge active : {current} prévu en ce moment.\n"
        f"Prochain changement : {control.describe_change(control.next_change(now, slots, days_off))}."
    )


CLOCK_RETRY_AFTER = timedelta(minutes=5)


def run_clock(now: datetime, tell=notify) -> str | None:
    """One clock pass: queue an on / off when the wanted state changes. Returns what was done.

    The clock only acts on changes, so a manual on / off stays until the next one. Right after
    the clock is switched on, the first pass only records the current wanted state. A change
    whose command failed is queued again after CLOCK_RETRY_AFTER and reported once.
    """
    state = ClockState.load()
    if not state.enabled:
        if state.last_wanted is not None or state.failed_at is not None or state.command_id is not None:
            state.last_wanted, state.failed_at, state.command = None, None, None
            state.save()
        return None

    if state.command is not None:
        command = state.command
        if command.status == Status.PENDING:
            return None
        state.command = None
        wanted_by_command = command.action == Action.ON
        if command.status == Status.DONE:
            state.last_wanted, state.failed_at = wanted_by_command, None
            tell(f"Horloge : {command.describe().lower()}. {command.detail}")
        elif command.status == Status.FAILED:
            if state.failed_at is None:
                tell(f"Horloge : {command.describe().lower()} impossible, nouvel essai dans 5 min. {command.detail}")
            state.failed_at = now
        state.save()  # cancelled (replaced by a manual command): the clock simply looks again

    slots, days_off = clock_plan()
    wanted = control.wanted_on(now, slots, days_off)
    if state.last_wanted is None:  # just switched on: remember, act on the next change only
        state.last_wanted = wanted
        state.save()
        return None
    if wanted == state.last_wanted:
        return None
    if state.failed_at is not None and now - state.failed_at < CLOCK_RETRY_AFTER:
        return None

    state.command = enqueue(Action.ON if wanted else Action.OFF, Source.CLOCK)
    state.save()
    return f"{state.command.describe()} mise en file"
