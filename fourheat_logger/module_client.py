"""Network access to the 4HEAT module: presence test and read-only query."""

import socket

from .config import READ_ALL_QUERY
from .protocol import parse_values


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
            raw = self._query()
        except OSError as error:
            raise ModuleError(f"connection failed: {error}") from error

        values = parse_values(raw)
        if not values:
            raise ModuleError(f"no values in answer: {raw!r}")
        return values

    def _query(self) -> str:
        with socket.create_connection((self._host, self._port), timeout=self._read_timeout) as sock:
            sock.settimeout(self._read_timeout)
            sock.sendall(READ_ALL_QUERY)

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
