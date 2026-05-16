"""Tests for app.ingestor — pure async-iterable injection, no real sockets.

TDD: these tests were written BEFORE the implementation.
"""
from __future__ import annotations

import asyncio
import json
import datetime as dt
from typing import AsyncIterator

import pytest

from app.repo import MemoryRepo
from app.parsers import SpotRecord


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _lines(*lines: str) -> AsyncIterator[str]:
    """Async generator that yields each string — a fake line source."""
    for line in lines:
        yield line


class FakeHub:
    """Record every broadcast call for assertions."""

    def __init__(self) -> None:
        self.events: list[dict] = []

    async def broadcast(self, event: dict) -> None:
        self.events.append(event)


def _make_settings(**overrides):
    """Build a minimal Settings-like object without touching env vars."""
    from app.config import Settings
    defaults = dict(
        db_dsn="postgresql://x:y@localhost/z",
        dx_host="localhost",
        dx_port=7300,
        dx_monitor_user="mon",
        dx_monitor_password="pw",
        users_poll_seconds=20,
        backfill_on_start=False,
        spot_files_dir="/tmp/spots",
    )
    defaults.update(overrides)
    return Settings(**defaults)


# ---------------------------------------------------------------------------
# Test: process_lines ingests spots and broadcasts
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_process_lines_two_spots_inserted_and_broadcast():
    """Human spot and RBN spot are inserted; broadcasts are JSON-serialisable."""
    from app.ingestor import Ingestor

    repo = MemoryRepo()
    hub = FakeHub()
    settings = _make_settings()
    fixed_ts = dt.datetime(2024, 1, 1, 12, 0, 0, tzinfo=dt.timezone.utc)
    ingestor = Ingestor(settings, repo, hub, clock=lambda: fixed_ts)

    human_spot = "DX de K1ABC:     14025.0  JA1XYZ       CW 599 up 2          1234Z"
    rbn_spot   = "DX de OH6BG-#:   14025.0  JA2XYZ       CW 12 dB 24 WPM CQ   1234Z"
    wwv_line   = "WWV de AR0NL <18>:   SFI=140, A=7, K=2, No Storms -> No Storms"
    junk_line  = "random garbage that parses to nothing"

    await ingestor.process_lines(_lines(human_spot, rbn_spot, wwv_line, junk_line))

    # Both spots inserted
    assert await repo.spot_count() == 2

    # Three broadcasts: 2 spots + 1 wwv
    spot_events = [e for e in hub.events if e["type"] == "spot"]
    wwv_events  = [e for e in hub.events if e["type"] == "wwv"]
    assert len(spot_events) == 2
    assert len(wwv_events) == 1

    # All spot broadcast payloads must be JSON-serialisable
    for event in spot_events:
        serialised = json.dumps(event)   # raises if not serialisable
        assert '"type": "spot"' in serialised or "spot" in serialised

    # Spot data contains expected fields
    dx_calls = {e["data"]["dx_call"] for e in spot_events}
    assert "JA1XYZ" in dx_calls
    assert "JA2XYZ" in dx_calls

    # WWV broadcast carries kind info
    assert wwv_events[0]["type"] == "wwv"
    assert "sfi" in wwv_events[0]["data"] or "text" in wwv_events[0]["data"]


@pytest.mark.asyncio
async def test_process_lines_no_hub_does_not_raise():
    """When hub=None, process_lines still inserts spots without crashing."""
    from app.ingestor import Ingestor

    repo = MemoryRepo()
    settings = _make_settings()
    ingestor = Ingestor(settings, repo, hub=None)

    spot_line = "DX de K1ABC:     14025.0  JA1XYZ       CW 599 up 2          1234Z"
    await ingestor.process_lines(_lines(spot_line))

    assert await repo.spot_count() == 1


@pytest.mark.asyncio
async def test_process_lines_junk_only_is_ignored():
    """Lines that don't parse must not raise or insert anything."""
    from app.ingestor import Ingestor

    repo = MemoryRepo()
    hub = FakeHub()
    settings = _make_settings()
    ingestor = Ingestor(settings, repo, hub)

    await ingestor.process_lines(_lines("garbage", "", "   ", "123 ???"))

    assert await repo.spot_count() == 0
    assert hub.events == []


# ---------------------------------------------------------------------------
# Test: spot_to_dict produces JSON-safe values
# ---------------------------------------------------------------------------

def test_spot_to_dict_json_serialisable():
    """spot_to_dict should produce a dict that json.dumps handles without error."""
    from app.ingestor import spot_to_dict

    rec = SpotRecord(
        kind="spot",
        spotter="K1ABC",
        dx_call="JA1XYZ",
        freq_khz=14025.0,
        band="20m",
        mode="CW",
        source="human",
        spotter_dxcc="United States",
        spotter_continent="NA",
        dx_dxcc="Japan",
        dx_continent="AS",
        comment="CW 599",
        when_z="1234Z",
        raw="DX de K1ABC ...",
    )
    d = spot_to_dict(rec)
    serialised = json.dumps(d)
    assert "JA1XYZ" in serialised
    assert "14025" in serialised
    # All values must be JSON-native types (str, int, float, None, bool)
    for v in d.values():
        assert v is None or isinstance(v, (str, int, float, bool))


# ---------------------------------------------------------------------------
# Test: backoff helper
# ---------------------------------------------------------------------------

def test_next_backoff_grows_and_caps():
    """next_backoff(attempt) returns values that grow and cap at 60 s."""
    from app.ingestor import next_backoff

    # Use a fixed RNG to make jitter deterministic
    import random
    rng = random.Random(42)

    values = [next_backoff(i, rng=rng) for i in range(10)]

    # All values must be within [0, 60]
    for v in values:
        assert 0 <= v <= 60, f"backoff {v} out of range"

    # Cap kicks in: attempts 7+ should be <= 60 s
    high_values = [next_backoff(i, rng=rng) for i in range(7, 20)]
    for v in high_values:
        assert v <= 60

    # Early attempts grow (attempt 5 median > attempt 0 median)
    low_samples = [next_backoff(0, rng=random.Random(s)) for s in range(50)]
    high_samples = [next_backoff(5, rng=random.Random(s)) for s in range(50)]
    assert sum(high_samples) > sum(low_samples)


# ---------------------------------------------------------------------------
# Test: handle_users_block updates repo + broadcasts
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_handle_users_block_updates_repo_and_broadcasts():
    """handle_users_block parses the fixture, writes repo, and emits users broadcast."""
    from app.ingestor import Ingestor
    from pathlib import Path

    repo = MemoryRepo()
    hub = FakeHub()
    settings = _make_settings()
    fixed_ts = dt.datetime(2024, 1, 1, 12, 0, 0, tzinfo=dt.timezone.utc)
    ingestor = Ingestor(settings, repo, hub, clock=lambda: fixed_ts)

    fixture = Path(__file__).parent / "fixtures" / "users_block.txt"
    text = fixture.read_text()

    await ingestor.handle_users_block(text)

    # Repo should have connected users
    users = await repo.connected_users()
    assert len(users) >= 4  # fixture has at least K1ABC, G7XYZ, VK2DX, OH6BG

    callsigns = {u["callsign"] for u in users}
    assert "K1ABC" in callsigns
    assert "G7XYZ" in callsigns

    # Hub should have a 'users' broadcast
    users_events = [e for e in hub.events if e["type"] == "users"]
    assert len(users_events) == 1
    payload = users_events[0]["data"]
    assert "count" in payload
    assert "users" in payload
    assert payload["count"] == len(users)


# ---------------------------------------------------------------------------
# Test: MONITOR_SETUP_COMMANDS is a module constant and looks right
# ---------------------------------------------------------------------------

def test_monitor_setup_commands_present():
    """MONITOR_SETUP_COMMANDS must exist as a module-level list of strings."""
    from app.ingestor import MONITOR_SETUP_COMMANDS

    assert isinstance(MONITOR_SETUP_COMMANDS, list)
    assert len(MONITOR_SETUP_COMMANDS) >= 5
    # Must include the critical ones
    cmd_str = " ".join(MONITOR_SETUP_COMMANDS)
    assert "set/page" in cmd_str.lower() or "set/page 0" in cmd_str
    assert any("set/dx" in c.lower() for c in MONITOR_SETUP_COMMANDS)
    assert any("set/wwv" in c.lower() for c in MONITOR_SETUP_COMMANDS)
