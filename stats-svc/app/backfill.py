"""DXSpider spot-file backfill for ``stats-svc``.

Expected file format (v1)
-------------------------
Files must match the glob ``**/*.spots`` relative to *spot_files_dir*.
Each line is a comma-separated or tab-separated record with exactly five
fields (extra trailing fields are ignored):

    freq_khz , dx_call , iso_timestamp , spotter , comment

Examples::

    14025.0,JA1XYZ,2024-01-01T12:34:00Z,K1ABC,CW 599 up 5
    7040.0\tDL1ABC\t2024-01-01T13:00:00Z\tG3XYZ\tCW DX

Field rules
~~~~~~~~~~~
* ``freq_khz``      — floating-point frequency in kilohertz.
* ``dx_call``       — DX station callsign (upper-cased on import).
* ``iso_timestamp`` — ISO-8601 UTC timestamp; ``Z`` suffix or ``+00:00`` both
                       accepted.  Must be parseable by ``datetime.fromisoformat``
                       after replacing a trailing ``Z`` with ``+00:00``.
* ``spotter``       — Spotter callsign (upper-cased on import).
* ``comment``       — Free-text comment (may contain commas if tab-separated).

Lines starting with ``#`` are treated as comments and skipped.
Blank lines are skipped.
Malformed lines (wrong field count, bad freq, bad timestamp) are skipped with
a warning; they do not abort the run.

Idempotency
~~~~~~~~~~~
``backfill`` uses ``repo.insert_spot_dedup`` so that running it twice against
the same files inserts 0 rows the second time.

Phase 2 extension
~~~~~~~~~~~~~~~~~
Native DXSpider spot files are Perl Data::Dumper (or binary) dumps stored
under ``/spider/local_data/spots/``.  Parse support for that format can be added
in a Phase 2 by extending ``parse_backfill_line`` with a format-detection
branch, keeping this module as the single entry point for all backfill work.
"""

from __future__ import annotations

import datetime as dt
import logging
from pathlib import Path
from typing import Callable

from app.bands import band_for_khz, mode_for_khz_comment
from app.dxcc import resolve
from app.parsers import SpotRecord
from app.repo import Repo

__all__ = ["backfill", "parse_backfill_line"]

logger = logging.getLogger(__name__)

UTC = dt.timezone.utc

_DEFAULT_CLOCK: Callable[[], dt.datetime] = lambda: dt.datetime.now(tz=UTC)


# ---------------------------------------------------------------------------
# Line parser
# ---------------------------------------------------------------------------

def parse_backfill_line(line: str) -> "tuple[SpotRecord, dt.datetime] | None":
    """Parse a single backfill file line into a (SpotRecord, datetime) pair.

    Returns None for blank lines, comment lines, or malformed records.
    Never raises.
    """
    if not isinstance(line, str):
        return None
    line = line.strip()
    if not line or line.startswith("#"):
        return None

    # Accept tab or comma as field separator; split on whichever appears first
    sep = "\t" if "\t" in line else ","
    parts = line.split(sep)

    # Need at least 5 fields
    if len(parts) < 5:
        return None

    freq_str, dx_call_raw, ts_str, spotter_raw, *comment_parts = parts
    comment = sep.join(comment_parts).strip()

    # Parse frequency
    try:
        freq_khz = float(freq_str.strip())
    except ValueError:
        return None

    # Parse timestamp: replace trailing Z with +00:00 for fromisoformat
    ts_clean = ts_str.strip().replace("Z", "+00:00")
    try:
        ts = dt.datetime.fromisoformat(ts_clean)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=UTC)
    except ValueError:
        return None

    dx_call = dx_call_raw.strip().upper()
    spotter = spotter_raw.strip().upper()

    if not dx_call or not spotter:
        return None

    # Enrich with band/mode/DXCC — mirroring parsers.py logic
    band = band_for_khz(freq_khz)
    mode = mode_for_khz_comment(freq_khz, comment)
    sp_dxcc = resolve(spotter)
    dx_dxcc = resolve(dx_call)

    rec = SpotRecord(
        kind="spot",
        spotter=spotter,
        dx_call=dx_call,
        freq_khz=freq_khz,
        band=band,
        mode=mode,
        source="human",          # backfill spots are treated as human by default
        spotter_dxcc=sp_dxcc.entity,
        spotter_continent=sp_dxcc.continent,
        dx_dxcc=dx_dxcc.entity,
        dx_continent=dx_dxcc.continent,
        comment=comment,
        when_z=None,             # no HHMM time embedded in this format
        raw=line,
    )
    return rec, ts


# ---------------------------------------------------------------------------
# Backfill entry point
# ---------------------------------------------------------------------------

async def backfill(
    repo: Repo,
    spot_files_dir: str,
    *,
    clock: Callable[[], dt.datetime] = _DEFAULT_CLOCK,
) -> int:
    """Scan *spot_files_dir* for ``*.spots`` files and insert new spots.

    Parameters
    ----------
    repo:
        Async repository; ``insert_spot_dedup`` is used for idempotency.
    spot_files_dir:
        Root directory to scan (recursively) for ``*.spots`` files.
    clock:
        Callable returning the current UTC datetime (injectable for tests).
        Used as a fallback timestamp if needed but the primary timestamp
        comes from each record's ISO field.

    Returns
    -------
    int
        Number of spots actually inserted (duplicates return 0).
    """
    base = Path(spot_files_dir)
    if not base.exists():
        logger.info("Spot files dir %s does not exist; skipping backfill", base)
        return 0

    files = sorted(base.rglob("*.spots"))
    if not files:
        logger.info("No *.spots files found under %s", base)
        return 0

    inserted = 0
    for path in files:
        logger.info("Backfilling from %s", path)
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            logger.warning("Cannot read %s; skipping", path)
            continue

        for raw_line in text.splitlines():
            result = parse_backfill_line(raw_line)
            if result is None:
                continue
            rec, ts = result
            try:
                was_inserted = await repo.insert_spot_dedup(rec, ts)
                if was_inserted:
                    inserted += 1
            except Exception:
                logger.exception("DB error inserting spot from %s: %r", path, raw_line)

    logger.info("Backfill complete: %d new spots inserted", inserted)
    return inserted
