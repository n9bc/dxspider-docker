"""DXSpider telnet ingestor.

Connects to a DXSpider cluster node via plain TCP (asyncio.open_connection),
logs in as the monitor user, sets up the necessary filters, then streams
lines into the parser and repo.

Design
------
* ``process_lines(line_iter)`` — pure async logic, testable without sockets.
* ``run()`` — thin wrapper that opens a real socket and feeds it into
  ``process_lines``; reconnects with exponential back-off + jitter on failure.
* ``handle_users_block(text)`` — parse + repo write + broadcast for show/users.
* ``stop()`` — signals the reconnect loop to exit cleanly.

Monitor setup commands are the module constant ``MONITOR_SETUP_COMMANDS``;
edit here to adjust what filters the monitor user receives.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import logging
import math
import random
from dataclasses import asdict
from typing import Any, AsyncIterator, Callable

from app.config import Settings
from app.parsers import InfoRecord, SpotRecord, parse_line, parse_users_block
from app.repo import Repo

__all__ = [
    "Ingestor",
    "MONITOR_SETUP_COMMANDS",
    "spot_to_dict",
    "next_backoff",
]

logger = logging.getLogger(__name__)

UTC = dt.timezone.utc

# ---------------------------------------------------------------------------
# Monitor setup commands sent immediately after login.
# Adjust these if the target node requires different filter syntax.
# Assumptions (to verify on a real node):
#   - set/page 0    → disables paging so output is a continuous stream
#   - set/dx        → subscribe to DX spots
#   - set/wwv       → subscribe to WWV propagation bulletins
#   - set/wcy       → subscribe to WCY geomagnetic data
#   - set/announce  → subscribe to announcements
#   - set/no/here   → mark the monitor account as "not here" (invisible)
# ---------------------------------------------------------------------------

MONITOR_SETUP_COMMANDS: list[str] = [
    "set/page 0",
    "set/dx",
    "set/wwv",
    "set/wcy",
    "set/announce",
    "set/no/here",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def spot_to_dict(rec: SpotRecord) -> dict[str, Any]:
    """Return a JSON-safe dict representation of a SpotRecord.

    All values are one of: str, int, float, bool, None — no datetime objects.
    """
    return {
        "kind": rec.kind,
        "spotter": rec.spotter,
        "dx_call": rec.dx_call,
        "freq_khz": rec.freq_khz,
        "band": rec.band,
        "mode": rec.mode,
        "source": rec.source,
        "spotter_dxcc": rec.spotter_dxcc,
        "spotter_continent": rec.spotter_continent,
        "dx_dxcc": rec.dx_dxcc,
        "dx_continent": rec.dx_continent,
        "comment": rec.comment,
        "when_z": rec.when_z,
        "raw": rec.raw,
    }


def _info_to_dict(rec: InfoRecord) -> dict[str, Any]:
    """Return a JSON-safe dict for an InfoRecord."""
    return {
        "kind": rec.kind,
        "sfi": rec.sfi,
        "a_index": rec.a_index,
        "k_index": rec.k_index,
        "r": rec.r,
        "origin": rec.origin,
        "text": rec.text,
        "raw": rec.raw,
    }


def next_backoff(
    attempt: int,
    *,
    base: float = 1.0,
    cap: float = 60.0,
    rng: random.Random | None = None,
) -> float:
    """Exponential back-off with full jitter, capped at *cap* seconds.

    Formula: uniform(0, min(cap, base * 2**attempt))

    Parameters
    ----------
    attempt:
        Zero-based reconnect attempt counter.
    base:
        Base delay in seconds (default 1 s).
    cap:
        Maximum delay in seconds (default 60 s).
    rng:
        Optional ``random.Random`` instance; uses the module-level RNG if None.
    """
    _rng = rng if rng is not None else random
    ceiling = min(cap, base * math.pow(2, attempt))
    return _rng.uniform(0, ceiling)


# ---------------------------------------------------------------------------
# Ingestor
# ---------------------------------------------------------------------------

class Ingestor:
    """DXSpider telnet ingestor.

    Parameters
    ----------
    settings:
        Application settings (host, port, credentials, poll interval).
    repo:
        Async repo for persisting spots and users.
    hub:
        Object with ``async broadcast(event: dict)``; may be None.
    clock:
        Callable returning the current UTC datetime (injectable for tests).
    """

    def __init__(
        self,
        settings: Settings,
        repo: Repo,
        hub: Any,
        *,
        clock: Callable[[], dt.datetime] = lambda: dt.datetime.now(tz=UTC),
    ) -> None:
        self._settings = settings
        self._repo = repo
        self._hub = hub
        self._clock = clock
        self._stop_event = asyncio.Event()

    # ------------------------------------------------------------------
    # Public control API
    # ------------------------------------------------------------------

    async def stop(self) -> None:
        """Signal the run loop to stop after the current iteration, interrupting any backoff sleep early for cooperative shutdown."""
        self._stop_event.set()

    # ------------------------------------------------------------------
    # Core processing — testable without real sockets
    # ------------------------------------------------------------------

    async def process_lines(self, line_iter: AsyncIterator[str]) -> None:
        """Consume an async iterable of raw text lines.

        For each line:
        * SpotRecord  → insert into repo, broadcast if hub is set.
        * InfoRecord  → broadcast if hub is set (no DB write for v1).
        * None        → ignore.
        """
        async for line in line_iter:
            try:
                rec = parse_line(line)
                if rec is None:
                    continue

                if isinstance(rec, SpotRecord) and rec.kind == "spot":
                    ts = self._clock()
                    await self._repo.insert_spot(rec, ts)
                    if self._hub is not None:
                        await self._hub.broadcast(
                            {"type": "spot", "data": spot_to_dict(rec)}
                        )

                elif isinstance(rec, InfoRecord):
                    if self._hub is not None:
                        await self._hub.broadcast(
                            {"type": rec.kind, "data": _info_to_dict(rec)}
                        )

            except Exception:
                logger.exception("Error processing line: %r", line)

    async def handle_users_block(self, text: str) -> None:
        """Parse a show/users block, write to repo, and broadcast."""
        now = self._clock()
        users = parse_users_block(text)
        await self._repo.replace_connected_users(users, now)
        if self._hub is not None:
            user_list = [
                {"callsign": u.callsign, "conn_type": u.conn_type}
                for u in users
            ]
            await self._hub.broadcast(
                {
                    "type": "users",
                    "data": {"count": len(users), "users": user_list},
                }
            )

    # ------------------------------------------------------------------
    # Telnet session
    # ------------------------------------------------------------------

    async def run(self) -> None:
        """Connect to DXSpider; reconnect with back-off on failure.

        Stops when ``stop()`` is called.
        """
        attempt = 0
        while not self._stop_event.is_set():
            try:
                await self._connect_and_stream()
                attempt = 0  # successful session resets the counter
            except asyncio.CancelledError:
                break
            except Exception:
                if self._stop_event.is_set():
                    break
                delay = next_backoff(attempt)
                logger.warning(
                    "Disconnected from DXSpider (attempt %d); "
                    "reconnecting in %.1fs",
                    attempt,
                    delay,
                )
                try:
                    await asyncio.wait_for(
                        self._stop_event.wait(), timeout=delay
                    )
                    break  # stop was requested during the wait
                except asyncio.TimeoutError:
                    pass
                attempt += 1

    async def _connect_and_stream(self) -> None:
        """Open a single telnet session, login, poll users, stream spots."""
        host = self._settings.dx_host
        port = self._settings.dx_port
        logger.info("Connecting to DXSpider at %s:%d", host, port)

        reader, writer = await asyncio.open_connection(host, port)
        try:
            await self._login(reader, writer)
            # Start users-poll task concurrently with the line stream
            poll_task = asyncio.create_task(
                self._users_poll_loop(reader, writer)
            )
            try:
                await self.process_lines(self._reader_lines(reader))
            finally:
                poll_task.cancel()
                try:
                    await poll_task
                except (asyncio.CancelledError, Exception):
                    pass
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass

    async def _login(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        """Wait for the login prompt then send credentials + setup commands.

        Assumptions (to verify on a real node):
        * The node sends a line containing "login" (case-insensitive) before
          waiting for the callsign.
        * Credentials: just the callsign is usually sufficient for a monitor
          account; no password challenge by default.  If a password is needed
          it would appear on the next prompt line.
        * Each command must be followed by a newline (\\n).
        """
        # Wait up to 10 s for a prompt containing "login" or "call"
        try:
            await asyncio.wait_for(
                self._wait_for_prompt(reader, [b"login", b"call", b">"]),
                timeout=10.0,
            )
        except asyncio.TimeoutError:
            logger.debug("No login prompt received; sending callsign anyway")

        user = self._settings.dx_monitor_user
        writer.write(f"{user}\n".encode())
        await writer.drain()

        # Some nodes ask for a password; wait briefly and send it if prompted
        try:
            prompt_line = await asyncio.wait_for(reader.readline(), timeout=3.0)
            if b"password" in prompt_line.lower():
                pw = self._settings.dx_monitor_password
                writer.write(f"{pw}\n".encode())
                await writer.drain()
        except asyncio.TimeoutError:
            pass

        # Send monitor setup commands
        for cmd in MONITOR_SETUP_COMMANDS:
            writer.write(f"{cmd}\n".encode())
        await writer.drain()
        logger.info("Logged in as %s; setup commands sent", user)

    async def _wait_for_prompt(
        self,
        reader: asyncio.StreamReader,
        keywords: list[bytes],
    ) -> None:
        """Read lines until one of the keywords appears."""
        while True:
            line = await reader.readline()
            if not line:
                raise ConnectionResetError("Connection closed before prompt")
            line_lower = line.lower()
            if any(kw in line_lower for kw in keywords):
                return

    @staticmethod
    async def _reader_lines(
        reader: asyncio.StreamReader,
    ) -> AsyncIterator[str]:
        """Yield decoded lines from an asyncio StreamReader."""
        while True:
            raw = await reader.readline()
            if not raw:
                return  # EOF
            yield raw.decode("utf-8", errors="replace").rstrip("\r\n")

    async def _users_poll_loop(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        """Periodically send show/users and process the response block.

        NOTE: In a real DXSpider stream the show/users output is interleaved
        with spot lines on the same reader.  For v1 simplicity we send the
        command and accumulate lines for a short collection window (1 s of
        inactivity) then parse the block.  Phase 2 can add proper protocol
        multiplexing if needed.
        """
        poll_s = self._settings.users_poll_seconds
        while not self._stop_event.is_set():
            await asyncio.sleep(poll_s)
            if self._stop_event.is_set():
                break
            try:
                writer.write(b"show/users\n")
                await writer.drain()
                # Collect response lines for up to 1 s
                block_lines: list[str] = []
                deadline = asyncio.get_running_loop().time() + 1.0
                while asyncio.get_running_loop().time() < deadline:
                    remaining = deadline - asyncio.get_running_loop().time()
                    try:
                        raw = await asyncio.wait_for(
                            reader.readline(), timeout=max(0.05, remaining)
                        )
                        if not raw:
                            break
                        block_lines.append(
                            raw.decode("utf-8", errors="replace").rstrip("\r\n")
                        )
                    except asyncio.TimeoutError:
                        break
                text = "\n".join(block_lines)
                await self.handle_users_block(text)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Error in users poll loop")
