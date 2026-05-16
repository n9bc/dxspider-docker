"""Repository abstraction for DX cluster statistics storage.

``Repo`` — abstract base class defining the async interface.
``MemoryRepo`` — in-memory implementation used by tests (no DB required).

The real Postgres implementation lives in ``app.db`` (PgRepo).
"""

import abc
import datetime as dt
from typing import Any

from app.parsers import ConnectedUser, SpotRecord

__all__ = ["Repo", "MemoryRepo"]


class Repo(abc.ABC):
    """Async storage interface.  All implementations must satisfy this contract."""

    # ------------------------------------------------------------------
    # Spot ingestion
    # ------------------------------------------------------------------

    @abc.abstractmethod
    async def insert_spot(self, spot: SpotRecord, ts: dt.datetime) -> None:
        """Insert a spot unconditionally and update the hourly rollup."""

    @abc.abstractmethod
    async def insert_spot_dedup(self, spot: SpotRecord, ts: dt.datetime) -> bool:
        """Insert a spot only if the (ts, spotter, dx_call, freq_khz) key is new.

        Returns True if the row was inserted, False if it was a duplicate.
        """

    # ------------------------------------------------------------------
    # Spot queries
    # ------------------------------------------------------------------

    @abc.abstractmethod
    async def spot_count(self) -> int:
        """Return the total number of stored spots."""

    @abc.abstractmethod
    async def fetch_spots(
        self,
        since: dt.datetime,
        until: dt.datetime,
        source: "str | None" = None,
    ) -> list[dict[str, Any]]:
        """Return spots in [since, until) optionally filtered by source."""

    # ------------------------------------------------------------------
    # Rollup queries
    # ------------------------------------------------------------------

    @abc.abstractmethod
    async def rollup_rows(self) -> list[dict[str, Any]]:
        """Return all rows from the hourly rollup table."""

    # ------------------------------------------------------------------
    # Connected-users management
    # ------------------------------------------------------------------

    @abc.abstractmethod
    async def replace_connected_users(
        self,
        users: list[ConnectedUser],
        snapshot_ts: dt.datetime,
    ) -> None:
        """Replace the entire connected-users table with *users* atomically."""

    @abc.abstractmethod
    async def connected_users(self) -> list[dict[str, Any]]:
        """Return all currently connected users."""


# ---------------------------------------------------------------------------
# In-memory implementation (no database, no asyncpg)
# ---------------------------------------------------------------------------

class MemoryRepo(Repo):
    """Thread-safe-enough in-process store for testing and local dev."""

    def __init__(self) -> None:
        # List of dicts mirroring the spots table columns
        self._spots: list[dict[str, Any]] = []
        # Dedup set: (ts, spotter, dx_call, freq_khz)
        self._spot_dedup: set[tuple] = set()
        # Rollup: key → count
        # key = (hour_ts, band, mode, source, dx_dxcc, dx_continent, spotter_dxcc)
        self._rollup: dict[tuple, int] = {}
        # Connected users (flat list of dicts)
        self._users: list[dict[str, Any]] = []

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _hour_ts(ts: dt.datetime) -> dt.datetime:
        """Truncate *ts* to the hour boundary (UTC)."""
        return ts.replace(minute=0, second=0, microsecond=0)

    @staticmethod
    def _spot_to_row(spot: SpotRecord, ts: dt.datetime) -> dict[str, Any]:
        return {
            "ts": ts,
            "spotter": spot.spotter,
            "dx_call": spot.dx_call,
            "freq_khz": spot.freq_khz,
            "band": spot.band,
            "mode": spot.mode,
            "source": spot.source,
            "spotter_dxcc": spot.spotter_dxcc,
            "dx_dxcc": spot.dx_dxcc,
            "dx_continent": spot.dx_continent,
            "comment": spot.comment,
            "raw": spot.raw,
        }

    def _update_rollup(self, spot: SpotRecord, ts: dt.datetime) -> None:
        key = (
            self._hour_ts(ts),
            spot.band,
            spot.mode,
            spot.source,
            spot.dx_dxcc,
            spot.dx_continent,
            spot.spotter_dxcc,
        )
        self._rollup[key] = self._rollup.get(key, 0) + 1

    def _dedup_key(self, spot: SpotRecord, ts: dt.datetime) -> tuple:
        return (ts, spot.spotter, spot.dx_call, spot.freq_khz)

    # ------------------------------------------------------------------
    # Repo implementation
    # ------------------------------------------------------------------

    async def insert_spot(self, spot: SpotRecord, ts: dt.datetime) -> None:
        self._spots.append(self._spot_to_row(spot, ts))
        self._update_rollup(spot, ts)

    async def insert_spot_dedup(self, spot: SpotRecord, ts: dt.datetime) -> bool:
        key = self._dedup_key(spot, ts)
        if key in self._spot_dedup:
            return False
        self._spot_dedup.add(key)
        await self.insert_spot(spot, ts)
        return True

    async def spot_count(self) -> int:
        return len(self._spots)

    async def fetch_spots(
        self,
        since: dt.datetime,
        until: dt.datetime,
        source: "str | None" = None,
    ) -> list[dict[str, Any]]:
        rows = [r for r in self._spots if since <= r["ts"] < until]
        if source is not None:
            rows = [r for r in rows if r["source"] == source]
        return list(rows)

    async def rollup_rows(self) -> list[dict[str, Any]]:
        result = []
        for (hour_ts, band, mode, source, dx_dxcc, dx_continent, spotter_dxcc), count in self._rollup.items():
            result.append({
                "hour_ts": hour_ts,
                "band": band,
                "mode": mode,
                "source": source,
                "dx_dxcc": dx_dxcc,
                "dx_continent": dx_continent,
                "spotter_dxcc": spotter_dxcc,
                "count": count,
            })
        return result

    async def replace_connected_users(
        self,
        users: list[ConnectedUser],
        snapshot_ts: dt.datetime,
    ) -> None:
        self._users = [
            {
                "callsign": u.callsign,
                "conn_type": u.conn_type,
                "snapshot_ts": snapshot_ts,
            }
            for u in users
        ]

    async def connected_users(self) -> list[dict[str, Any]]:
        return list(self._users)
