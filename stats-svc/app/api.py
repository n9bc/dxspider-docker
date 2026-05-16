"""FastAPI application factory for DX Cluster Stats.

Usage
-----
    from app.api import create_app
    from app.repo import MemoryRepo

    app = create_app(MemoryRepo())

Design notes
------------
* ``create_app`` is a factory; no Postgres pool is created at import time.
* Uvicorn and asyncpg are NOT imported at module level so test collection works
  without those packages installed.
* The broadcast hub (``BroadcastHub``) uses an asyncio.Queue per WebSocket
  connection plus a ``pending`` queue for messages injected before any client
  connects (used by tests and the ingestor bootstrap path).
* Static files are mounted at ``/`` with html=True so ``/`` returns index.html.
  The ``/api`` prefix and ``/ws`` routes are registered before the static mount
  and therefore take precedence.
"""

from __future__ import annotations

import asyncio
from enum import Enum
from typing import Any

from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
import pathlib

from app.repo import Repo

__all__ = ["create_app", "BroadcastHub"]

# ---------------------------------------------------------------------------
# Source enum — used for query-param validation
# ---------------------------------------------------------------------------

class Source(str, Enum):
    human = "human"
    rbn = "rbn"
    both = "both"


# ---------------------------------------------------------------------------
# Broadcast hub
# ---------------------------------------------------------------------------

class BroadcastHub:
    """Lightweight in-process pub/sub hub for WebSocket clients.

    Each connected WebSocket gets its own asyncio.Queue.  ``broadcast``
    puts the event into every connected queue.

    ``pending`` is a small asyncio.Queue used to pre-seed events before any
    WebSocket connects (useful in tests and on ingestor start-up).
    """

    def __init__(self) -> None:
        self._sinks: set[asyncio.Queue] = set()
        # Messages placed here are forwarded to the *first* client that connects.
        # Used by tests to inject events without needing an async caller.
        self.pending: asyncio.Queue = asyncio.Queue()

    def connect(self, q: asyncio.Queue) -> None:
        self._sinks.add(q)

    def disconnect(self, q: asyncio.Queue) -> None:
        self._sinks.discard(q)

    async def broadcast(self, event: dict[str, Any]) -> None:
        """Deliver *event* to every connected sink."""
        for q in list(self._sinks):
            await q.put(event)


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------

def create_app(repo: Repo) -> FastAPI:
    """Create and return a configured FastAPI application.

    Parameters
    ----------
    repo:
        A ``Repo`` implementation.  Injected so tests can pass a MemoryRepo
        without touching environment variables or a database.
    """
    app = FastAPI(title="DX Cluster Stats", version="1.0.0")

    # Attach hub to app state so the ingestor (Task 8) can reach it via
    # ``app.state.hub``.
    app.state.hub = BroadcastHub()

    # -----------------------------------------------------------------------
    # Lazy aggregate imports (aggregate.py imports repo.py which is fine,
    # but we import here to keep the api module clean at module level)
    # -----------------------------------------------------------------------
    from app import aggregate

    # -----------------------------------------------------------------------
    # REST routes
    # -----------------------------------------------------------------------

    @app.get("/api/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/activity")
    async def activity(
        source: Source = Query(Source.both),
        hours: int = Query(24, ge=1, le=168),
    ) -> list[dict[str, Any]]:
        return await aggregate.activity_series(repo, source=source.value, hours=hours)

    @app.get("/api/bands")
    async def bands(
        source: Source = Query(Source.both),
    ) -> list[dict[str, Any]]:
        return await aggregate.band_breakdown(repo, source=source.value)

    @app.get("/api/modes")
    async def modes(
        source: Source = Query(Source.both),
    ) -> list[dict[str, Any]]:
        return await aggregate.mode_breakdown(repo, source=source.value)

    _GEO_BY_VALUES = {"dx_continent", "dx_dxcc", "spotter_dxcc"}

    @app.get("/api/geo")
    async def geo(
        source: Source = Query(Source.both),
        by: str = Query("dx_continent"),
        top: int = Query(15, ge=1, le=100),
    ) -> list[dict[str, Any]]:
        if by not in _GEO_BY_VALUES:
            raise HTTPException(
                status_code=422,
                detail=f"'by' must be one of {sorted(_GEO_BY_VALUES)!r}",
            )
        return await aggregate.geo_breakdown(repo, source=source.value, by=by, top=top)

    @app.get("/api/top/spotters")
    async def top_spotters(
        source: Source = Query(Source.both),
        limit: int = Query(10, ge=1, le=100),
        hours: int = Query(24, ge=1, le=168),
    ) -> list[dict[str, Any]]:
        return await aggregate.top_spotters(repo, source=source.value, limit=limit, hours=hours)

    @app.get("/api/top/dx")
    async def top_dx(
        source: Source = Query(Source.both),
        limit: int = Query(10, ge=1, le=100),
        hours: int = Query(24, ge=1, le=168),
    ) -> list[dict[str, Any]]:
        return await aggregate.top_dx(repo, source=source.value, limit=limit, hours=hours)

    @app.get("/api/users")
    async def users() -> dict[str, Any]:
        return await aggregate.connected(repo)

    # -----------------------------------------------------------------------
    # WebSocket endpoint
    # -----------------------------------------------------------------------

    @app.websocket("/ws")
    async def ws_endpoint(websocket: WebSocket) -> None:
        """Accept a WebSocket connection and stream broadcast events.

        On connect:
        1. Flush any events pre-seeded into ``hub.pending`` to this client.
        2. Register a personal asyncio.Queue with the hub.
        3. Stream events from the queue until disconnect.
        """
        hub: BroadcastHub = app.state.hub
        await websocket.accept()

        # Drain any pending messages (for tests / early ingestor events)
        personal_q: asyncio.Queue = asyncio.Queue()

        # Move pending messages into personal queue so they are delivered first
        while not hub.pending.empty():
            try:
                msg = hub.pending.get_nowait()
                await personal_q.put(msg)
            except asyncio.QueueEmpty:
                break

        hub.connect(personal_q)
        try:
            while True:
                event = await personal_q.get()
                await websocket.send_json(event)
        except WebSocketDisconnect:
            pass
        except Exception:
            pass
        finally:
            hub.disconnect(personal_q)

    # -----------------------------------------------------------------------
    # Static files (mount last so /api/* and /ws take precedence)
    # -----------------------------------------------------------------------
    _static_dir = pathlib.Path(__file__).parent / "static"
    app.mount("/", StaticFiles(directory=str(_static_dir), html=True), name="static")

    return app
