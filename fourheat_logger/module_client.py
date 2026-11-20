"""Network access to the 4HEAT module: presence test, read query and write commands."""

import socket

from .config import READ_ALL_QUERY
from .protocol import build_command, parse_values


class ModuleError(Exception):
    """The module did not answer, or answered something unusable."""


class FourHeatClient:
    def __init__(self, host: str, port: int, probe_timeout: float, read_timeout: float) -> None:
        self._host = host
        self._port = port
        self._probe_timeout = probe_timeout
        self._read_timeout = read_timeout

    def is_reachable(self) -> bool:
        """Cheap presence test: can a TCP connection be opened? Nothing is sent."""
        try:
            with socket.create_connection((self._host, self._port), timeout=self._probe_timeout):
                return True
        except OSError:
            return False

    def read_values(self) -> dict[str, int]:
        """Send the read-all query and return {id: value}. Raise ModuleError on failure."""
        try:
            raw = self._query(READ_ALL_QUERY)
        except OSError as error:
            raise ModuleError(f"connection failed: {error}") from error

        values = parse_values(raw)
        if not values:
            raise ModuleError(f"no values in answer: {raw!r}")
        return values

    def send_command(self, *items: str) -> str:
        """Send a write frame (items from protocol.command_item) and return the raw answer.

        The exact acknowledgement format is not documented: the answer must not be an error
        and must mention the id of every item sent, otherwise ModuleError is raised (the
        command may still have been applied, so callers check the result when they can).
        """
        try:
            raw = self._query(build_command(*items))
        except OSError as error:
            raise ModuleError(f"connection failed: {error}") from error

        if not raw.strip():
            raise ModuleError("no answer")
        if '"ERR"' in raw:
            raise ModuleError(f"command refused: {raw!r}")
        missing = [item for item in items if item[1:6] not in raw]
        if missing:
            raise ModuleError(f"command not acknowledged: {raw!r}")
        return raw

    def _query(self, message: bytes) -> str:
        with socket.create_connection((self._host, self._port), timeout=self._read_timeout) as sock:
            sock.settimeout(self._read_timeout)
            sock.sendall(message)

            chunks = []
            while True:
                try:
                    chunk = sock.recv(1024)
                except socket.timeout:
                    break  # no more data within the timeout
                if not chunk:
                    break  # module closed the connection
                chunks.append(chunk)
                if b"".join(chunks).rstrip().endswith(b"]"):
                    break  # complete bracketed list received

        return b"".join(chunks).decode(errors="replace")
