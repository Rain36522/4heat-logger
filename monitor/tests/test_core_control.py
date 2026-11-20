import unittest
from datetime import date, datetime, time, timedelta

from fourheat_logger.module_client import ModuleError
from fourheat_logger.protocol import build_command, command_item
from monitor.core.control import (
    DayOff,
    HeatingControl,
    Refused,
    Slot,
    TryAgain,
    collector_allows,
    describe_change,
    next_change,
    next_try,
    slot_active,
    target_range,
    wanted_on,
)

# Monday 2026-11-16 ... Sunday 2026-11-22
MONDAY = date(2026, 11, 16)
WORK_WEEK = Slot(0, time(5, 0), 4, time(19, 0))  # Monday 05:00 -> Friday 19:00
EVENINGS = Slot(None, time(18, 0), None, time(22, 0))
NIGHT = Slot(None, time(22, 0), None, time(6, 0))  # crosses midnight


def at(day_offset, hour, minute=0):
    return datetime(2026, 11, 16 + day_offset, hour, minute)


class FrameTests(unittest.TestCase):
    def test_write_frames_match_the_known_commands(self):
        self.assertEqual(build_command(command_item("J", "30253", 1)), b'["SEC","1","J30253000000000001"]')
        self.assertEqual(build_command(command_item("B", "20180", 70)), b'["SEC","1","B20180000000000070"]')

    def test_a_value_that_does_not_fit_is_refused(self):
        with self.assertRaises(ValueError):
            command_item("B", "20180", -1)


class SlotTests(unittest.TestCase):
    def test_weekly_slot_from_monday_to_friday(self):
        self.assertFalse(slot_active(WORK_WEEK, at(0, 4, 59)))
        self.assertTrue(slot_active(WORK_WEEK, at(0, 5)))  # start included
        self.assertTrue(slot_active(WORK_WEEK, at(2, 3)))  # Wednesday night
        self.assertTrue(slot_active(WORK_WEEK, at(4, 18, 59)))
        self.assertFalse(slot_active(WORK_WEEK, at(4, 19)))  # end excluded
        self.assertFalse(slot_active(WORK_WEEK, at(5, 12)))  # Saturday

    def test_weekly_slot_over_the_weekend(self):
        weekend = Slot(4, time(19, 0), 0, time(5, 0))  # Friday 19:00 -> Monday 05:00
        self.assertTrue(slot_active(weekend, at(6, 12)))
        self.assertTrue(slot_active(weekend, at(0, 4)))
        self.assertFalse(slot_active(weekend, at(0, 5)))

    def test_daily_slots_including_one_across_midnight(self):
        self.assertTrue(slot_active(EVENINGS, at(3, 20)))
        self.assertFalse(slot_active(EVENINGS, at(3, 22)))
        self.assertTrue(slot_active(NIGHT, at(3, 23)))
        self.assertTrue(slot_active(NIGHT, at(4, 5, 59)))
        self.assertFalse(slot_active(NIGHT, at(4, 6)))

    def test_same_start_and_end_means_always(self):
        self.assertTrue(slot_active(Slot(None, time(7, 0), None, time(7, 0)), at(1, 3)))


class ClockTests(unittest.TestCase):
    def test_a_day_off_stops_the_heating_inside_a_slot(self):
        holiday = [DayOff(date(2026, 11, 18), date(2026, 11, 18))]  # Wednesday
        self.assertTrue(wanted_on(at(1, 12), [WORK_WEEK], holiday))
        self.assertFalse(wanted_on(at(2, 12), [WORK_WEEK], holiday))
        self.assertTrue(wanted_on(at(3, 0), [WORK_WEEK], holiday))

    def test_no_slot_means_off(self):
        self.assertFalse(wanted_on(at(0, 12), [], []))

    def test_next_change(self):
        self.assertEqual(next_change(at(0, 3), [WORK_WEEK], []), (at(0, 5), True))
        self.assertEqual(next_change(at(0, 5), [WORK_WEEK], []), (at(4, 19), False))
        holiday = [DayOff(date(2026, 11, 18), date(2026, 11, 19))]
        self.assertEqual(next_change(at(0, 5), [WORK_WEEK], holiday), (at(2, 0), False))
        self.assertEqual(next_change(at(2, 9), [WORK_WEEK], holiday), (at(4, 0), True))
        self.assertIsNone(next_change(at(0, 3), [], []))

    def test_describe_change(self):
        self.assertEqual(describe_change((at(4, 19), False)), "vendredi 20.11 à 19:00 → arrêt")


class FakeModule:
    """Module that answers like the real one, can be busy, and can ignore writes."""

    def __init__(self, values, busy=0, ignore_writes=False):
        self.values = dict(values)
        self.sent = []
        self.busy = busy
        self.ignore_writes = ignore_writes

    def read_values(self):
        self._maybe_busy()
        return dict(self.values)

    def send_command(self, *items):
        self._maybe_busy()
        self.sent.extend(items)
        for item in items:
            if item.startswith("B") and not self.ignore_writes:
                self.values[item[1:6]] = int(item[6:])
        return "ok"

    def _maybe_busy(self):
        if self.busy:
            self.busy -= 1
            raise ModuleError("connection failed: busy")


VALUES = {"30001": 5, "20180": 65, "20005": 30, "20006": 75}


def control(module, pauses=None):
    return HeatingControl(module, gap=5, read_back_delay=10, sleep=(pauses if pauses is not None else []).append)


class HeatingControlTests(unittest.TestCase):
    def test_on_and_off_send_the_known_frames(self):
        module = FakeModule(VALUES)
        control(module).turn_on()
        control(module).turn_off()
        self.assertEqual(module.sent, ["J30253000000000001", "J30254000000000001"])

    def test_an_unreachable_module_asks_for_another_attempt(self):
        module = FakeModule(VALUES, busy=1)
        with self.assertRaisesRegex(TryAgain, "Module injoignable"):
            control(module).turn_on()
        self.assertEqual(module.sent, [])  # no retry inside an attempt: the queue retries later

    def test_target_is_written_then_read_back_with_pauses_between_connections(self):
        module, pauses = FakeModule(VALUES), []
        self.assertEqual(control(module, pauses).set_boiler_target(70), "Consigne chaudière : 65 → 70 °C.")
        self.assertEqual(module.sent, ["B20180000000000070"])
        self.assertEqual(pauses, [5, 10])  # read, 5 s, write, 10 s, read back

    def test_target_outside_the_module_limits_is_refused_without_writing(self):
        module = FakeModule(VALUES)
        with self.assertRaisesRegex(Refused, "entre 30 et 75"):
            control(module).set_boiler_target(80)
        self.assertEqual(module.sent, [])

    def test_repeating_a_target_already_applied_writes_nothing(self):
        module = FakeModule(VALUES)
        self.assertEqual(control(module).set_boiler_target(65), "La consigne chaudière est à 65 °C.")
        self.assertEqual(module.sent, [])

    def test_a_write_the_module_did_not_apply_asks_for_another_attempt(self):
        with self.assertRaisesRegex(TryAgain, "indique toujours 65"):
            control(FakeModule(VALUES, ignore_writes=True)).set_boiler_target(70)


class QueueTimingTests(unittest.TestCase):
    def test_commands_start_between_two_collector_reads(self):
        read = datetime(2026, 11, 20, 8, 0, 0)
        self.assertFalse(collector_allows(read + timedelta(seconds=5), read))  # just after a read
        self.assertTrue(collector_allows(read + timedelta(seconds=10), read))
        self.assertTrue(collector_allows(read + timedelta(seconds=35), read))
        self.assertFalse(collector_allows(read + timedelta(seconds=50), read))  # next read is close
        self.assertTrue(collector_allows(read + timedelta(minutes=5), read))  # collector not reading
        self.assertTrue(collector_allows(read, None))

    def test_retry_every_20_s_and_give_up_after_5_min(self):
        created = datetime(2026, 11, 20, 8, 0, 0)
        self.assertEqual(next_try(created, created + timedelta(seconds=1)), created + timedelta(seconds=21))
        self.assertEqual(next_try(created, created + timedelta(minutes=4, seconds=40)), created + timedelta(minutes=5))
        self.assertIsNone(next_try(created, created + timedelta(minutes=4, seconds=41)))

    def test_target_range_falls_back_when_the_module_limits_look_wrong(self):
        self.assertEqual(target_range({"20005": 30, "20006": 75}), (30, 75))
        self.assertEqual(target_range({}), (30, 75))
        self.assertEqual(target_range({"20005": 80, "20006": 40}), (30, 75))


if __name__ == "__main__":
    unittest.main()
