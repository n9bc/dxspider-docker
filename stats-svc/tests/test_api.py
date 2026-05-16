"""Tests for app.api — FastAPI REST + WebSocket + static dashboard.

Strategy
--------
- All REST tests use FastAPI's Starlette TestClient (sync) with a seeded MemoryRepo.
- Hub unit tests are async (pytest-asyncio auto mode) and test the hub class directly.
- WebSocket integration test uses TestClient.websocket_connect with a
  pre-seeded asyncio.Queue injected into the hub before the WS connects.
- No mocking of the aggregate layer — real MemoryRepo with real spots.

Seed
----
3 spots + 2 connected users so every endpoint returns non-empty data.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import json

import pytest
from fastapi.testclient import TestClient

from app.repo import MemoryRepo
from app.parsers import SpotRecord, ConnectedUser

_UTC = dt.timezone.utc

# ---------------------------------------------------------------------------
# Shared fixture: seeded repo and app
# ---------------------------------------------------------------------------

def _make_repo() -> MemoryRepo:
    """Return a MemoryRepo seeded with 3 spots and 2 connected users."""
    repo = MemoryRepo()

    # We need to insert via asyncio since insert_spot is async
    async def _seed():
        # Use real current UTC time so activity_series / top_spotters / top_dx
        # (which call _now_utc() internally) pick up the spots within the
        # default 24-hour window.
        now = dt.datetime.now(tz=_UTC)
        h0 = now - dt.timedelta(hours=2)
        h1 = now - dt.timedelta(hours=1)

        spot_a = SpotRecord(
            spotter="K1ABC", dx_call="JA1XX", freq_khz=14025.0,
            band="20m", mode="CW", source="human",
            spotter_dxcc="USA", dx_dxcc="Japan", dx_continent="AS",
        )
        spot_b = SpotRecord(
            spotter="G3XYZ", dx_call="VK2YY", freq_khz=7050.0,
            band="40m", mode="SSB", source="rbn",
            spotter_dxcc="England", dx_dxcc="Australia", dx_continent="OC",
        )
        spot_c = SpotRecord(
            spotter="K1ABC", dx_call="JA1XX", freq_khz=14025.0,
            band="20m", mode="CW", source="human",
            spotter_dxcc="USA", dx_dxcc="Japan", dx_continent="AS",
        )

        await repo.insert_spot(spot_a, h0)
        await repo.insert_spot(spot_b, h1)
        await repo.insert_spot(spot_c, h1)

        users = [
            ConnectedUser(callsign="K1ABC", conn_type="telnet"),
            ConnectedUser(callsign="W0YVA", conn_type="web"),
        ]
        await repo.replace_connected_users(users, now)

    asyncio.run(_seed())
    return repo


@pytest.fixture()
def repo() -> MemoryRepo:
    return _make_repo()


@pytest.fixture()
def client(repo: MemoryRepo) -> TestClient:
    from app.api import create_app
    application = create_app(repo)
    return TestClient(application, raise_server_exceptions=True)


@pytest.fixture()
def app(repo: MemoryRepo):
    from app.api import create_app
    return create_app(repo)


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

def test_health_returns_ok(client: TestClient):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


# ---------------------------------------------------------------------------
# Activity series
# ---------------------------------------------------------------------------

def test_activity_default_params(client: TestClient):
    resp = client.get("/api/activity")
    assert resp.status_code == 200
    data = resp.json()
    # Should return exactly 24 buckets
    assert isinstance(data, list)
    assert len(data) == 24
    # Each bucket has "hour" and "count"
    for item in data:
        assert "hour" in item
        assert "count" in item
    # Total across all buckets should equal total spots (3)
    assert sum(item["count"] for item in data) == 3


def test_activity_source_rbn(client: TestClient):
    resp = client.get("/api/activity?source=rbn")
    assert resp.status_code == 200
    data = resp.json()
    # Only 1 rbn spot (spot_b)
    assert sum(item["count"] for item in data) == 1


def test_activity_source_human(client: TestClient):
    resp = client.get("/api/activity?source=human")
    assert resp.status_code == 200
    data = resp.json()
    # 2 human spots
    assert sum(item["count"] for item in data) == 2


def test_activity_invalid_source_returns_422(client: TestClient):
    resp = client.get("/api/activity?source=bogus")
    assert resp.status_code == 422


def test_activity_hours_param(client: TestClient):
    resp = client.get("/api/activity?hours=6")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 6


# ---------------------------------------------------------------------------
# Band breakdown
# ---------------------------------------------------------------------------

def test_bands_returns_list(client: TestClient):
    resp = client.get("/api/bands")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    # Seeded: 20m x2, 40m x1
    labels = {item["label"] for item in data}
    assert "20m" in labels
    assert "40m" in labels


def test_bands_shape(client: TestClient):
    resp = client.get("/api/bands")
    assert resp.status_code == 200
    for item in resp.json():
        assert "label" in item
        assert "value" in item


def test_bands_invalid_source_422(client: TestClient):
    resp = client.get("/api/bands?source=bogus")
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Mode breakdown
# ---------------------------------------------------------------------------

def test_modes_returns_list(client: TestClient):
    resp = client.get("/api/modes")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    labels = {item["label"] for item in data}
    # spot_a=CW, spot_b=SSB, spot_c=CW
    assert "CW" in labels
    assert "SSB" in labels


def test_modes_shape(client: TestClient):
    resp = client.get("/api/modes")
    assert resp.status_code == 200
    for item in resp.json():
        assert "label" in item
        assert "value" in item


# ---------------------------------------------------------------------------
# Geo breakdown
# ---------------------------------------------------------------------------

def test_geo_default(client: TestClient):
    resp = client.get("/api/geo")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    # All spots in AS or OC
    labels = {item["label"] for item in data}
    assert "AS" in labels


def test_geo_by_dx_continent(client: TestClient):
    resp = client.get("/api/geo?by=dx_continent")
    assert resp.status_code == 200


def test_geo_by_dx_dxcc(client: TestClient):
    resp = client.get("/api/geo?by=dx_dxcc")
    assert resp.status_code == 200
    data = resp.json()
    labels = {item["label"] for item in data}
    assert "Japan" in labels


def test_geo_by_spotter_dxcc(client: TestClient):
    resp = client.get("/api/geo?by=spotter_dxcc")
    assert resp.status_code == 200


def test_geo_invalid_by_returns_error(client: TestClient):
    resp = client.get("/api/geo?by=bogus")
    # 422 from FastAPI validation or 400 from handler — must be 4xx
    assert resp.status_code in (400, 422)


def test_geo_invalid_source_422(client: TestClient):
    resp = client.get("/api/geo?source=bogus")
    assert resp.status_code == 422


def test_geo_shape(client: TestClient):
    resp = client.get("/api/geo")
    assert resp.status_code == 200
    for item in resp.json():
        assert "label" in item
        assert "value" in item


def test_geo_top_param(client: TestClient):
    resp = client.get("/api/geo?top=1")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) <= 1


# ---------------------------------------------------------------------------
# Top spotters
# ---------------------------------------------------------------------------

def test_top_spotters_returns_list(client: TestClient):
    resp = client.get("/api/top/spotters")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    # K1ABC spotted 2 times (spot_a, spot_c)
    callsigns = {item["callsign"] for item in data}
    assert "K1ABC" in callsigns


def test_top_spotters_shape(client: TestClient):
    resp = client.get("/api/top/spotters")
    assert resp.status_code == 200
    for item in resp.json():
        assert "callsign" in item
        assert "count" in item


def test_top_spotters_k1abc_count(client: TestClient):
    resp = client.get("/api/top/spotters")
    assert resp.status_code == 200
    data = resp.json()
    k1abc = next((x for x in data if x["callsign"] == "K1ABC"), None)
    assert k1abc is not None
    assert k1abc["count"] == 2


def test_top_spotters_invalid_source_422(client: TestClient):
    resp = client.get("/api/top/spotters?source=bogus")
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Top DX
# ---------------------------------------------------------------------------

def test_top_dx_returns_list(client: TestClient):
    resp = client.get("/api/top/dx")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    callsigns = {item["callsign"] for item in data}
    # JA1XX spotted by K1ABC (spot_a) and K1ABC (spot_c) = 2 times
    assert "JA1XX" in callsigns


def test_top_dx_shape(client: TestClient):
    resp = client.get("/api/top/dx")
    assert resp.status_code == 200
    for item in resp.json():
        assert "callsign" in item
        assert "count" in item


def test_top_dx_ja1xx_count(client: TestClient):
    resp = client.get("/api/top/dx")
    assert resp.status_code == 200
    data = resp.json()
    ja1xx = next((x for x in data if x["callsign"] == "JA1XX"), None)
    assert ja1xx is not None
    assert ja1xx["count"] == 2


def test_top_dx_invalid_source_422(client: TestClient):
    resp = client.get("/api/top/dx?source=bogus")
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Rare DX
# ---------------------------------------------------------------------------

def test_rare_dx_returns_list(client: TestClient):
    resp = client.get("/api/top/rare-dx")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)


def test_rare_dx_shape(client: TestClient):
    resp = client.get("/api/top/rare-dx")
    assert resp.status_code == 200
    for item in resp.json():
        assert "callsign" in item
        assert "count" in item


def test_rare_dx_ascending_order(client: TestClient):
    """Counts must be ascending (rarest first)."""
    resp = client.get("/api/top/rare-dx?limit=100")
    assert resp.status_code == 200
    data = resp.json()
    counts = [item["count"] for item in data]
    assert counts == sorted(counts)


def test_rare_dx_invalid_source_422(client: TestClient):
    resp = client.get("/api/top/rare-dx?source=bogus")
    assert resp.status_code == 422


def test_rare_dx_source_filter(client: TestClient):
    """source=human filters out rbn-only calls (spot_b is rbn: G3XYZ/VK2YY)."""
    resp = client.get("/api/top/rare-dx?source=human")
    assert resp.status_code == 200
    data = resp.json()
    # spot_b is rbn source; with source=human only spot_a and spot_c remain
    # Both are by K1ABC spotting JA1XX → only JA1XX appears with count=2
    callsigns = {item["callsign"] for item in data}
    assert "JA1XX" in callsigns
    assert "VK2YY" not in callsigns


def test_rare_dx_limit_param(client: TestClient):
    resp = client.get("/api/top/rare-dx?limit=1")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) <= 1


# ---------------------------------------------------------------------------
# Callsign detail
# ---------------------------------------------------------------------------

def test_callsign_detail_returns_dict(client: TestClient):
    resp = client.get("/api/callsign/K1ABC")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, dict)
    assert set(data.keys()) == {"callsign", "as_spotter", "as_dx", "recent"}


def test_callsign_detail_callsign_uppercased(client: TestClient):
    resp = client.get("/api/callsign/k1abc")
    assert resp.status_code == 200
    data = resp.json()
    assert data["callsign"] == "K1ABC"


def test_callsign_detail_k1abc_counts(client: TestClient):
    """In seeded repo: K1ABC spots spot_a and spot_c → as_spotter=2, as_dx=0."""
    resp = client.get("/api/callsign/K1ABC")
    assert resp.status_code == 200
    data = resp.json()
    assert data["as_spotter"] == 2
    assert data["as_dx"] == 0


def test_callsign_detail_ja1xx_counts(client: TestClient):
    """JA1XX is dx in spot_a and spot_c → as_dx=2, as_spotter=0."""
    resp = client.get("/api/callsign/JA1XX")
    assert resp.status_code == 200
    data = resp.json()
    assert data["as_dx"] == 2
    assert data["as_spotter"] == 0


def test_callsign_detail_recent_newest_first(client: TestClient):
    """recent entries must be sorted newest first."""
    resp = client.get("/api/callsign/K1ABC")
    assert resp.status_code == 200
    recent = resp.json()["recent"]
    if len(recent) > 1:
        ts_list = [r["ts"] for r in recent]
        assert ts_list == sorted(ts_list, reverse=True)


def test_callsign_detail_recent_fields(client: TestClient):
    """Each recent entry must have the required fields."""
    resp = client.get("/api/callsign/K1ABC")
    assert resp.status_code == 200
    recent = resp.json()["recent"]
    for entry in recent:
        assert "ts" in entry
        assert "spotter" in entry
        assert "dx_call" in entry
        assert "freq_khz" in entry
        assert "band" in entry
        assert "mode" in entry
        assert "source" in entry


def test_callsign_detail_no_spots_returns_zeros_empty(client: TestClient):
    """A callsign with no spots returns zeros and an empty recent list."""
    resp = client.get("/api/callsign/XX0NOBODY")
    assert resp.status_code == 200
    data = resp.json()
    assert data["callsign"] == "XX0NOBODY"
    assert data["as_spotter"] == 0
    assert data["as_dx"] == 0
    assert data["recent"] == []


# ---------------------------------------------------------------------------
# Connected users
# ---------------------------------------------------------------------------

def test_users_returns_dict(client: TestClient):
    resp = client.get("/api/users")
    assert resp.status_code == 200
    data = resp.json()
    assert "count" in data
    assert "users" in data


def test_users_count(client: TestClient):
    resp = client.get("/api/users")
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] == 2


def test_users_callsigns(client: TestClient):
    resp = client.get("/api/users")
    assert resp.status_code == 200
    data = resp.json()
    callsigns = {u["callsign"] for u in data["users"]}
    assert callsigns == {"K1ABC", "W0YVA"}


def test_users_shape(client: TestClient):
    resp = client.get("/api/users")
    assert resp.status_code == 200
    for user in resp.json()["users"]:
        assert "callsign" in user
        assert "conn_type" in user


# ---------------------------------------------------------------------------
# Static files
# ---------------------------------------------------------------------------

def test_root_returns_html_dashboard(client: TestClient):
    resp = client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert "DX Cluster Stats" in resp.text


def test_app_js_served(client: TestClient):
    resp = client.get("/app.js")
    assert resp.status_code == 200


def test_style_css_served(client: TestClient):
    resp = client.get("/style.css")
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# WebSocket hub unit tests (async, no TestClient)
# ---------------------------------------------------------------------------

async def test_hub_broadcast_delivers_to_connected_sinks():
    """Hub broadcast sends event to all connected asyncio.Queue sinks."""
    from app.api import BroadcastHub

    hub = BroadcastHub()
    q1: asyncio.Queue = asyncio.Queue()
    q2: asyncio.Queue = asyncio.Queue()

    hub.connect(q1)
    hub.connect(q2)

    event = {"type": "spot", "data": {"dx_call": "JA1XX"}}
    await hub.broadcast(event)

    assert q1.get_nowait() == event
    assert q2.get_nowait() == event


async def test_hub_disconnect_removes_sink():
    """After disconnect, broadcast no longer delivers to that sink."""
    from app.api import BroadcastHub

    hub = BroadcastHub()
    q1: asyncio.Queue = asyncio.Queue()
    q2: asyncio.Queue = asyncio.Queue()

    hub.connect(q1)
    hub.connect(q2)
    hub.disconnect(q1)

    await hub.broadcast({"type": "users", "data": {}})

    # q1 should be empty (was disconnected)
    assert q1.empty()
    # q2 should have the event
    assert not q2.empty()
    assert q2.get_nowait() == {"type": "users", "data": {}}


async def test_hub_broadcast_empty_no_error():
    """Broadcast with no connected sinks should not raise."""
    from app.api import BroadcastHub

    hub = BroadcastHub()
    # Should not raise
    await hub.broadcast({"type": "spot", "data": {}})


async def test_hub_multiple_broadcasts():
    """Multiple sequential broadcasts all arrive in order."""
    from app.api import BroadcastHub

    hub = BroadcastHub()
    q: asyncio.Queue = asyncio.Queue()
    hub.connect(q)

    events = [{"type": "spot", "data": {"n": i}} for i in range(5)]
    for e in events:
        await hub.broadcast(e)

    received = [q.get_nowait() for _ in range(5)]
    assert received == events


# ---------------------------------------------------------------------------
# WebSocket endpoint integration test
# ---------------------------------------------------------------------------

def test_websocket_receives_broadcast():
    """WS client receives a message broadcast via hub.broadcast().

    Approach: pre-seed the hub's internal queue before opening the WS
    connection. The WS endpoint drains the queue and sends to the client.
    We verify the client receives the expected JSON.
    """
    from app.api import create_app

    repo = _make_repo()
    application = create_app(repo)

    # Pre-seed a message into the hub's pending queue before any WS connects
    event = {"type": "spot", "data": {"dx_call": "VK2YY", "freq_khz": 7050.0}}
    application.state.hub.pending.put_nowait(event)

    with TestClient(application) as tc:
        with tc.websocket_connect("/ws") as ws:
            received = ws.receive_json()
            assert received == event


def test_websocket_accepts_connection(client: TestClient):
    """WS endpoint accepts a connection (no immediate disconnect)."""
    # We just verify the connect+close cycle works without error
    with client.websocket_connect("/ws") as ws:
        # Connection accepted; no exception means success
        pass


def test_websocket_receives_live_broadcast():
    """WS client receives an event placed on the live sink after connecting.

    Covers the real ingestor scenario: client connects first, then an event
    is broadcast into the hub's live sinks (not the pending queue).

    We use the TestClient's anyio BlockingPortal (tc.portal) to call
    hub.broadcast() on the background event loop that owns the asyncio.Queue,
    so the WS send-loop coroutine wakes up correctly across threads.
    """
    from app.api import create_app

    app = create_app(_make_repo())
    event = {"type": "spot", "data": {"dx_call": "ZL3NW", "freq_khz": 21225.5}}

    with TestClient(app) as tc:
        with tc.websocket_connect("/ws") as ws:
            hub = app.state.hub
            assert len(hub._sinks) == 1
            # Run broadcast() on the background event loop via the portal
            tc.portal.call(hub.broadcast, event)
            assert ws.receive_json() == event
