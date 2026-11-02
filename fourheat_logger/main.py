"""Entry point: python3 -m fourheat_logger.main <module_ip> [options]"""

import argparse
import logging
import os
import signal
import sys
import threading
from pathlib import Path

from .config import Settings
from .module_client import FourHeatClient
from .monitor import Monitor
from .storage import CsvStorage, HeaderMismatchError

EXIT_OK = 0
EXIT_BAD_OUTPUT_FILE = 2  # systemd unit: RestartPreventExitStatus=2


def parse_args() -> Settings:
    defaults = Settings(host="")
    parser = argparse.ArgumentParser(description="Read-only logger for a 4HEAT module")
    parser.add_argument("host", help="IP address or hostname of the 4HEAT module")
    parser.add_argument("--port", type=int, default=defaults.port)
    parser.add_argument("--output", type=Path, default=defaults.output)
    parser.add_argument("--presence-interval", type=float, default=defaults.presence_interval,
                        help="seconds between checks while the module is unreachable or the boiler at rest")
    parser.add_argument("--record-interval", type=float, default=defaults.record_interval,
                        help="seconds between readings while the boiler runs")
    args = parser.parse_args()
    return Settings(
        host=args.host,
        port=args.port,
        output=args.output,
        presence_interval=args.presence_interval,
        record_interval=args.record_interval,
    )


def setup_logging() -> None:
    # Under systemd the journal already adds the timestamp.
    fmt = "%(levelname)s %(message)s" if "JOURNAL_STREAM" in os.environ else "%(asctime)s %(levelname)s %(message)s"
    logging.basicConfig(level=logging.INFO, format=fmt, stream=sys.stdout)


def main() -> int:
    settings = parse_args()
    setup_logging()

    storage = CsvStorage(settings.output)
    try:
        storage.check_header()
    except HeaderMismatchError as error:
        logging.error("%s", error)
        return EXIT_BAD_OUTPUT_FILE

    stop_event = threading.Event()
    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, lambda *_: stop_event.set())

    client = FourHeatClient(settings.host, settings.port, settings.probe_timeout, settings.read_timeout)
    logging.info("started: module=%s:%s output=%s", settings.host, settings.port, settings.output)
    Monitor(settings, client, storage, stop_event).run()
    logging.info("stopped")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
