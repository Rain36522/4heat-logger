"""Main loop: presence test, boiler state filter, recording.

          module unreachable ──(every presence_interval)──> TCP test
                 │ reachable
                 ▼
          read values ──fails──> module unreachable
                 │
          boiler at rest ──(every presence_interval)──> read again, record nothing
                 │ running
                 ▼
          record a CSV row ──(every record_interval)──> read again
"""

import logging
import threading
import time
from datetime import datetime
from typing import Optional

from .config import REST_STATES, STATE_ID, Settings
from .module_client import FourHeatClient, ModuleError
from .storage import CsvStorage

logger = logging.getLogger(__name__)


class Monitor:
    def __init__(
        self,
        settings: Settings,
        client: FourHeatClient,
        storage: CsvStorage,
        stop_event: threading.Event,
    ) -> None:
        self._settings = settings
        self._client = client
        self._storage = storage
        self._stop = stop_event
        self._online: Optional[bool] = None  # None = not known yet
        self._running: Optional[bool] = None

    def run(self) -> None:
        if not REST_STATES:
            logger.warning("REST_STATES is empty: state filter disabled, every reading is recorded")
        while not self._stop.is_set():
            self._stop.wait(self._cycle())

    def _cycle(self) -> float:
        """Do one cycle and return the seconds to wait before the next one."""
        started = time.monotonic()
        interval = self._do_cycle()
        return max(0.0, interval - (time.monotonic() - started))

    def _do_cycle(self) -> float:
        settings = self._settings

        if not self._online:
            if not self._client.is_reachable():
                self._set_online(False, "no TCP answer")
                return settings.presence_interval
            # Measured: a query sent right after the TCP test gets an empty answer; 2 s later it works.
            if self._stop.wait(settings.probe_settle):
                return 0.0

        try:
            values = self._client.read_values()
        except ModuleError as error:
            self._set_online(False, str(error))
            return settings.presence_interval
        self._set_online(True)

        running = self._is_running(values)
        self._set_running(running, values.get(STATE_ID))
        if not running:
            return settings.presence_interval

        self._storage.append(datetime.now().isoformat(timespec="seconds"), values)
        return settings.record_interval

    @staticmethod
    def _is_running(values: dict[str, int]) -> bool:
        """Unknown state means running: better one useless row than a lost one."""
        if not REST_STATES:
            return True
        state = values.get(STATE_ID)
        return state is None or state not in REST_STATES

    def _set_online(self, online: bool, reason: str = "") -> None:
        if online != self._online:
            if online:
                logger.info("module reachable")
            else:
                logger.warning("module unreachable (%s)", reason)
                self._running = None  # unknown until the module is back
        self._online = online

    def _set_running(self, running: bool, state: Optional[int]) -> None:
        if running != self._running:
            logger.info("boiler %s (state=%s)", "running: recording" if running else "at rest: not recording", state)
        self._running = running
