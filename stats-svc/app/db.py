"""Postgres-backed Repo implementation using asyncpg.

The ``asyncpg`` library is imported lazily so that importing this module does
NOT crash when asyncpg is not installed (e.g. during unit tests that only use
MemoryRepo).

Usage::

    from app.db import make_pg_repo
    repo = await make_pg_repo(settings.db_dsn)
"""

import datetime as dt
from typing import Any

from app.parsers import ConnectedUser, SpotRecord
from app.repo import Repo

# ---------------------------------------------------------------------------
# Lazy asyncpg import — safe to import this module without the library installed
# ---------------------------------------------------------------------------
try:
    import asyncpg  # type: ignore[import]
except ImportError:
    asyncpg = None  # type: ignore[assignment]

__all__ = ["SCHEMA_SQL", "PgRepo", "make_pg_repo"]

# ---------------------------------------------------------------------------
# Schema DDL (idempotent)
# ---------------------------------------------------------------------------

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS spots (
    id          BIGSERIAL PRIMARY KEY,
    ts          TIMESTAMPTZ NOT NULL,
    spotter     TEXT        NOT NULL,
    dx_call     TEXT        NOT NULL,
    freq_khz    DOUBLE PRECISION NOT NULL,
    band        TEXT,
    mode        TEXT,
    source      TEXT        NOT NULL DEFAULT 'human',
    spotter_dxcc TEXT,
    dx_dxcc     TEXT,
    dx_continent TEXT,
    comment     TEXT,
    raw         TEXT
);

-- Unique constraint used by dedup upsert (backfill)
CREATE UNIQUE INDEX IF NOT EXISTS spots_dedup_uidx
    ON spots (ts, spotter, dx_call, freq_khz);

-- Fast range queries on time
CREATE INDEX IF NOT EXISTS spots_ts_idx ON spots (ts);
-- Filter by source
CREATE INDEX IF NOT EXISTS spots_source_idx ON spots (source);


CREATE TABLE IF NOT EXISTS connected_users (
    callsign    TEXT        NOT NULL,
    conn_type   TEXT        NOT NULL,
    since_ts    TIMESTAMPTZ,
    snapshot_ts TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (callsign)
);


CREATE TABLE IF NOT EXISTS spot_rollup_hourly (
    hour_ts      TIMESTAMPTZ NOT NULL,
    band         TEXT,
    mode         TEXT,
    source       TEXT        NOT NULL,
    dx_dxcc      TEXT,
    dx_continent TEXT,
    spotter_dxcc TEXT,
    count        BIGINT      NOT NULL DEFAULT 0,
    PRIMARY KEY (hour_ts, band, mode, source, dx_dxcc, dx_continent, spotter_dxcc)
);
"""


# ---------------------------------------------------------------------------
# PgRepo
# ---------------------------------------------------------------------------

class PgRepo(Repo):
    """Postgres-backed repository.

    Construct via ``make_pg_repo(dsn)`` — do NOT instantiate directly.
    """

    def __init__(self, pool: Any) -> None:
        if asyncpg is None:
            raise RuntimeError("asyncpg is not installed; cannot use PgRepo")
        self._pool = pool

    # ------------------------------------------------------------------
    # Spot ingestion
    # ------------------------------------------------------------------

    async def insert_spot(self, spot: SpotRecord, ts: dt.datetime) -> None:
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    """
                    INSERT INTO spots
                        (ts, spotter, dx_call, freq_khz, band, mode, source,
                         spotter_dxcc, dx_dxcc, dx_continent, comment, raw)
                    VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)
                    """,
                    ts,
                    spot.spotter,
                    spot.dx_call,
                    spot.freq_khz,
                    spot.band,
                    spot.mode,
                    spot.source,
                    spot.spotter_dxcc,
                    spot.dx_dxcc,
                    spot.dx_continent,
                    spot.comment,
                    spot.raw,
                )
                await self._upsert_rollup(conn, spot, ts)

    async def insert_spot_dedup(self, spot: SpotRecord, ts: dt.datetime) -> bool:
        """Insert only if the dedup key is new.  Returns True on insert, False on dup."""
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                result = await conn.execute(
                    """
                    INSERT INTO spots
                        (ts, spotter, dx_call, freq_khz, band, mode, source,
                         spotter_dxcc, dx_dxcc, dx_continent, comment, raw)
                    VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)
                    ON CONFLICT (ts, spotter, dx_call, freq_khz) DO NOTHING
                    """,
                    ts,
                    spot.spotter,
                    spot.dx_call,
                    spot.freq_khz,
                    spot.band,
                    spot.mode,
                    spot.source,
                    spot.spotter_dxcc,
                    spot.dx_dxcc,
                    spot.dx_continent,
                    spot.comment,
                    spot.raw,
                )
                # asyncpg returns "INSERT 0 N" — N==0 means conflict
                inserted = result.split()[-1] != "0"
                if inserted:
                    await self._upsert_rollup(conn, spot, ts)
                return inserted

    @staticmethod
    async def _upsert_rollup(conn: Any, spot: SpotRecord, ts: dt.datetime) -> None:
        hour_ts = ts.replace(minute=0, second=0, microsecond=0)
        await conn.execute(
            """
            INSERT INTO spot_rollup_hourly
                (hour_ts, band, mode, source, dx_dxcc, dx_continent, spotter_dxcc, count)
            VALUES ($1,$2,$3,$4,$5,$6,$7,1)
            ON CONFLICT (hour_ts, band, mode, source, dx_dxcc, dx_continent, spotter_dxcc)
            DO UPDATE SET count = spot_rollup_hourly.count + 1
            """,
            hour_ts,
            spot.band,
            spot.mode,
            spot.source,
            spot.dx_dxcc,
            spot.dx_continent,
            spot.spotter_dxcc,
        )

    # ------------------------------------------------------------------
    # Spot queries
    # ------------------------------------------------------------------

    async def spot_count(self) -> int:
        async with self._pool.acquire() as conn:
            return await conn.fetchval("SELECT COUNT(*) FROM spots")

    async def fetch_spots(
        self,
        since: dt.datetime,
        until: dt.datetime,
        source: "str | None" = None,
    ) -> list[dict[str, Any]]:
        async with self._pool.acquire() as conn:
            if source is None:
                rows = await conn.fetch(
                    "SELECT * FROM spots WHERE ts >= $1 AND ts < $2 ORDER BY ts",
                    since,
                    until,
                )
            else:
                rows = await conn.fetch(
                    "SELECT * FROM spots WHERE ts >= $1 AND ts < $2"
                    " AND source = $3 ORDER BY ts",
                    since,
                    until,
                    source,
                )
            return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Rollup
    # ------------------------------------------------------------------

    async def rollup_rows(self) -> list[dict[str, Any]]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch("SELECT * FROM spot_rollup_hourly ORDER BY hour_ts")
            return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Connected users
    # ------------------------------------------------------------------

    async def replace_connected_users(
        self,
        users: list[ConnectedUser],
        snapshot_ts: dt.datetime,
    ) -> None:
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute("DELETE FROM connected_users")
                if users:
                    await conn.executemany(
                        """
                        INSERT INTO connected_users (callsign, conn_type, snapshot_ts)
                        VALUES ($1, $2, $3)
                        """,
                        [(u.callsign, u.conn_type, snapshot_ts) for u in users],
                    )

    async def connected_users(self) -> list[dict[str, Any]]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM connected_users ORDER BY callsign"
            )
            return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

async def make_pg_repo(dsn: str) -> PgRepo:
    """Create a connection pool, apply the schema, and return a ready PgRepo."""
    if asyncpg is None:
        raise RuntimeError(
            "asyncpg is not installed.  Install it with: pip install asyncpg"
        )
    pool = await asyncpg.create_pool(dsn)
    async with pool.acquire() as conn:
        await conn.execute(SCHEMA_SQL)
    return PgRepo(pool)
