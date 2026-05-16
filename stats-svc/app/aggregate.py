"""Chart aggregation logic for the DX cluster stats service.

All functions are async, accept a ``Repo`` instance plus keyword filters, and
return JSON-serialisable plain structures (lists of dicts or a dict) ready to
serve from API endpoints.

Design notes
------------
* ``activity_series``, ``band_breakdown``, ``mode_breakdown``, and
  ``geo_breakdown`` work from ``rollup_rows()`` — the pre-aggregated hourly
  table — for efficiency.
* ``top_spotters`` and ``top_dx`` need the individual spotter/dx callsigns
  which are not retained in the rollup, so they derive their data from
  ``fetch_spots()`` over a configurable recent window (default 24 h).
* ``connected`` delegates directly to ``connected_users()``.
* All time arithmetic uses timezone-aware UTC ``datetime`` objects.
* Empty / missing field values (``""`` in rollup) are relabelled ``"unknown"``
  in all label-bearing outputs.
"""

from __future__ import annotations

import datetime as dt
from collections import defaultdict
from typing import Any

from app.repo import Repo

__all__ = [
    "activity_series",
    "band_breakdown",
    "mode_breakdown",
    "geo_breakdown",
    "top_spotters",
    "top_dx",
    "connected",
]

_UTC = dt.timezone.utc

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _now_utc() -> dt.datetime:
    """Return the current UTC time as a timezone-aware datetime."""
    return dt.datetime.now(tz=_UTC)


def _source_filter(source: str) -> "str | None":
    """Translate the public ``source`` parameter to the repo ``source`` arg.

    ``"both"``  → ``None``   (no filter)
    ``"human"`` → ``"human"``
    ``"rbn"``   → ``"rbn"``

    Maps source → the ``source`` argument accepted by ``fetch_spots`` (returns
    ``None`` for "both", meaning no filter); this is distinct from the
    rollup-path filtering performed by ``_filter_rollup`` used in the breakdown
    functions.
    """
    return None if source == "both" else source


def _label(value: str) -> str:
    """Return *value* unchanged, or ``"unknown"`` for the empty string."""
    return value if value else "unknown"


def _filter_rollup(rows: list[dict[str, Any]], source: str) -> list[dict[str, Any]]:
    """Filter rollup rows by source (no-op when source == 'both')."""
    if source == "both":
        return rows
    return [r for r in rows if r["source"] == source]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def activity_series(
    repo: Repo,
    *,
    source: str = "both",
    hours: int = 24,
    _now: "dt.datetime | None" = None,
) -> list[dict[str, Any]]:
    """Return per-hour spot counts for the last *hours* hours.

    Returns a list of ``{"hour": <iso8601 str>, "count": int}`` dicts in
    ascending chronological order.  Hours with no spots appear with
    ``count=0`` so callers always receive exactly *hours* buckets.

    *_now* is an optional override for the current UTC time, intended for
    tests with deterministic fixed timestamps.  The window includes the current
    (still-open) partial hour as the last bucket.
    """
    # Build a map of hour_ts → count from the rollup.
    rows = await repo.rollup_rows()
    rows = _filter_rollup(rows, source)

    hour_count: dict[dt.datetime, int] = defaultdict(int)
    for row in rows:
        hour_count[row["hour_ts"]] += row["count"]

    # Determine the range: the most-recent complete hour boundary ≤ now, then
    # walk back (hours - 1) more steps to form a window of exactly *hours*
    # contiguous buckets.
    now = _now if _now is not None else _now_utc()
    # Truncate to current hour boundary
    latest_hour = now.replace(minute=0, second=0, microsecond=0)
    # We want [latest_hour - (hours-1)*1h  ..  latest_hour] inclusive
    result = []
    for i in range(hours - 1, -1, -1):
        bucket = latest_hour - dt.timedelta(hours=i)
        count = hour_count.get(bucket, 0)
        result.append({"hour": bucket.isoformat(), "count": count})

    return result


async def band_breakdown(
    repo: Repo,
    *,
    source: str = "both",
) -> list[dict[str, Any]]:
    """Return spot counts grouped by band, descending by count.

    Returns ``[{"label": <band>, "value": <count>}, ...]``.
    The empty-string band (unknown) is relabelled ``"unknown"``.
    """
    rows = await repo.rollup_rows()
    rows = _filter_rollup(rows, source)

    totals: dict[str, int] = defaultdict(int)
    for row in rows:
        totals[_label(row["band"])] += row["count"]

    return sorted(
        [{"label": band, "value": cnt} for band, cnt in totals.items()],
        key=lambda x: x["value"],
        reverse=True,
    )


async def mode_breakdown(
    repo: Repo,
    *,
    source: str = "both",
) -> list[dict[str, Any]]:
    """Return spot counts grouped by mode, descending by count.

    Returns ``[{"label": <mode>, "value": <count>}, ...]``.
    The empty-string mode is relabelled ``"unknown"``.
    """
    rows = await repo.rollup_rows()
    rows = _filter_rollup(rows, source)

    totals: dict[str, int] = defaultdict(int)
    for row in rows:
        totals[_label(row["mode"])] += row["count"]

    return sorted(
        [{"label": mode, "value": cnt} for mode, cnt in totals.items()],
        key=lambda x: x["value"],
        reverse=True,
    )


async def geo_breakdown(
    repo: Repo,
    *,
    source: str = "both",
    by: str = "dx_continent",
    top: int = 15,
) -> list[dict[str, Any]]:
    """Return spot counts grouped by a geographic dimension.

    *by* must be one of ``"dx_continent"``, ``"dx_dxcc"``, or
    ``"spotter_dxcc"``.  Returns up to *top* entries as
    ``[{"label": <value>, "value": <count>}, ...]`` descending by count.
    Empty strings are relabelled ``"unknown"``.
    """
    if by not in ("dx_continent", "dx_dxcc", "spotter_dxcc"):
        raise ValueError(f"geo_breakdown: unsupported 'by' value: {by!r}")

    rows = await repo.rollup_rows()
    rows = _filter_rollup(rows, source)

    totals: dict[str, int] = defaultdict(int)
    for row in rows:
        totals[_label(row[by])] += row["count"]

    ranked = sorted(
        [{"label": label, "value": cnt} for label, cnt in totals.items()],
        key=lambda x: x["value"],
        reverse=True,
    )
    return ranked[:top]


async def top_spotters(
    repo: Repo,
    *,
    source: str = "both",
    limit: int = 10,
    hours: int = 24,
    _now: "dt.datetime | None" = None,
) -> list[dict[str, Any]]:
    """Return the top *limit* spotters by spot count over the last *hours* hours.

    Spotter callsigns are not retained in the rollup, so this function fetches
    individual spot rows.  Returns ``[{"callsign": str, "count": int}, ...]``
    descending by count.

    *_now* is an optional override for the current UTC time, intended for
    tests with deterministic fixed timestamps.
    """
    now = _now if _now is not None else _now_utc()
    since = now - dt.timedelta(hours=hours)

    src_filter = _source_filter(source)
    spots = await repo.fetch_spots(since, now, src_filter)

    totals: dict[str, int] = defaultdict(int)
    for spot in spots:
        totals[spot["spotter"]] += 1

    ranked = sorted(
        [{"callsign": cs, "count": cnt} for cs, cnt in totals.items()],
        key=lambda x: x["count"],
        reverse=True,
    )
    return ranked[:limit]


async def top_dx(
    repo: Repo,
    *,
    source: str = "both",
    limit: int = 10,
    hours: int = 24,
    _now: "dt.datetime | None" = None,
) -> list[dict[str, Any]]:
    """Return the top *limit* DX stations by number of times spotted over the
    last *hours* hours.

    Returns ``[{"callsign": str, "count": int}, ...]`` descending by count.

    *_now* is an optional override for the current UTC time, intended for
    tests with deterministic fixed timestamps.
    """
    now = _now if _now is not None else _now_utc()
    since = now - dt.timedelta(hours=hours)

    src_filter = _source_filter(source)
    spots = await repo.fetch_spots(since, now, src_filter)

    totals: dict[str, int] = defaultdict(int)
    for spot in spots:
        totals[spot["dx_call"]] += 1

    ranked = sorted(
        [{"callsign": cs, "count": cnt} for cs, cnt in totals.items()],
        key=lambda x: x["count"],
        reverse=True,
    )
    return ranked[:limit]


async def connected(repo: Repo) -> dict[str, Any]:
    """Return connected user count and user list sorted by callsign.

    Returns ``{"count": int, "users": [{"callsign": str, "conn_type": str}, ...]}``.
    """
    users = await repo.connected_users()
    users_sorted = sorted(users, key=lambda u: u["callsign"])
    return {
        "count": len(users_sorted),
        "users": [
            {"callsign": u["callsign"], "conn_type": u["conn_type"]}
            for u in users_sorted
        ],
    }
