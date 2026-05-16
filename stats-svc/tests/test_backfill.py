"""Tests for app.backfill — temp-dir injection, no real FS side-effects.

TDD: these tests were written BEFORE the implementation.
"""
from __future__ import annotations

import json
import datetime as dt
from pathlib import Path

import pytest

from app.repo import MemoryRepo


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fixed_clock():
    return dt.datetime(2024, 6, 1, 0, 0, 0, tzinfo=dt.timezone.utc)


# ---------------------------------------------------------------------------
# Test: parse_backfill_line
# ---------------------------------------------------------------------------

def test_parse_backfill_line_valid():
    """A well-formed CSV line produces (SpotRecord, datetime)."""
    from app.backfill import parse_backfill_line

    result = parse_backfill_line("14025.0,JA1XYZ,2024-01-01T12:34:00Z,K1ABC,CW 599")
    assert result is not None
    rec, ts = result
    assert rec.dx_call == "JA1XYZ"
    assert rec.spotter == "K1ABC"
    assert abs(rec.freq_khz - 14025.0) < 0.01
    assert ts.year == 2024
    assert ts.tzinfo is not None


def test_parse_backfill_line_malformed_returns_none():
    """Malformed lines must return None, not raise."""
    from app.backfill import parse_backfill_line

    assert parse_backfill_line("") is None
    assert parse_backfill_line("only one field") is None
    assert parse_backfill_line("not,enough") is None
    assert parse_backfill_line("bad_freq,JA1XYZ,2024-01-01T12:00:00Z,K1,CW") is None
    assert parse_backfill_line("#comment line") is None


def test_parse_backfill_line_tab_separated():
    """Tab-separated lines are also accepted."""
    from app.backfill import parse_backfill_line

    result = parse_backfill_line("14025.0\tJA1XYZ\t2024-01-01T12:34:00Z\tK1ABC\tCW 599")
    assert result is not None
    rec, ts = result
    assert rec.dx_call == "JA1XYZ"


def test_parse_backfill_line_enriches_band():
    """parse_backfill_line should populate band via bands module."""
    from app.backfill import parse_backfill_line

    result = parse_backfill_line("14025.0,JA1XYZ,2024-01-01T12:34:00Z,K1ABC,CW 599")
    assert result is not None
    rec, _ = result
    assert rec.band == "20m"


# ---------------------------------------------------------------------------
# Test: backfill function
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_backfill_inserts_valid_skips_malformed(tmp_path: Path):
    """backfill inserts valid lines and skips malformed ones."""
    from app.backfill import backfill

    spots_file = tmp_path / "test.spots"
    spots_file.write_text(
        "14025.0,JA1XYZ,2024-01-01T12:34:00Z,K1ABC,CW 599\n"
        "this is garbage and should be skipped\n"
        "7040.0,DL1ABC,2024-01-01T13:00:00Z,G3XYZ,CW DX\n"
        "another bad line\n",
        encoding="utf-8",
    )

    repo = MemoryRepo()
    count = await backfill(repo, str(tmp_path), clock=_fixed_clock)

    assert count == 2
    assert await repo.spot_count() == 2


@pytest.mark.asyncio
async def test_backfill_is_idempotent(tmp_path: Path):
    """Running backfill twice inserts 0 on the second run."""
    from app.backfill import backfill

    spots_file = tmp_path / "run.spots"
    spots_file.write_text(
        "14025.0,JA1XYZ,2024-01-01T12:34:00Z,K1ABC,CW 599\n"
        "7040.0,DL1ABC,2024-01-01T13:00:00Z,G3XYZ,CW DX\n",
        encoding="utf-8",
    )

    repo = MemoryRepo()
    first = await backfill(repo, str(tmp_path), clock=_fixed_clock)
    second = await backfill(repo, str(tmp_path), clock=_fixed_clock)

    assert first == 2
    assert second == 0
    assert await repo.spot_count() == 2  # unchanged


@pytest.mark.asyncio
async def test_backfill_scans_subdirectories(tmp_path: Path):
    """backfill finds .spots files nested in year/month sub-dirs."""
    from app.backfill import backfill

    subdir = tmp_path / "2024" / "01"
    subdir.mkdir(parents=True)
    (subdir / "jan.spots").write_text(
        "21025.0,VK2DX,2024-01-15T09:00:00Z,W1AW,CW 599\n",
        encoding="utf-8",
    )

    repo = MemoryRepo()
    count = await backfill(repo, str(tmp_path), clock=_fixed_clock)
    assert count == 1


@pytest.mark.asyncio
async def test_backfill_empty_dir_returns_zero(tmp_path: Path):
    """backfill on an empty directory returns 0 without error."""
    from app.backfill import backfill

    repo = MemoryRepo()
    count = await backfill(repo, str(tmp_path), clock=_fixed_clock)
    assert count == 0


@pytest.mark.asyncio
async def test_backfill_spot_values_correct(tmp_path: Path):
    """The inserted spot has the right field values."""
    from app.backfill import backfill

    spots_file = tmp_path / "check.spots"
    spots_file.write_text(
        "14025.0,JA1XYZ,2024-01-01T12:34:00Z,K1ABC,CW 599 up 5\n",
        encoding="utf-8",
    )

    repo = MemoryRepo()
    await backfill(repo, str(tmp_path), clock=_fixed_clock)

    spots = await repo.fetch_spots(
        since=dt.datetime(2024, 1, 1, tzinfo=dt.timezone.utc),
        until=dt.datetime(2024, 1, 2, tzinfo=dt.timezone.utc),
    )
    assert len(spots) == 1
    s = spots[0]
    assert s["dx_call"] == "JA1XYZ"
    assert s["spotter"] == "K1ABC"
    assert abs(s["freq_khz"] - 14025.0) < 0.01
    assert s["band"] == "20m"
    assert "599" in s["comment"]
