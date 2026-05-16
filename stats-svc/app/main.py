"""Application entry point for stats-svc.

Wires together:
* Settings (from environment)
* Backfill (optional, on startup)
* PgRepo (via make_pg_repo)
* FastAPI app (via create_app)
* Ingestor (telnet reader, background task)
* Uvicorn (HTTP server)

Lazy imports
------------
``uvicorn`` and ``asyncpg`` (through ``make_pg_repo``) are imported INSIDE
``amain()`` only — never at module level — so ``import app.main`` is safe in
unit tests that run without those packages installed.
"""

from __future__ import annotations

import asyncio
import logging
import os

logger = logging.getLogger(__name__)


async def amain() -> None:
    """Async entry point — load config, run backfill, start server."""
    # Local imports so module-level import is safe without uvicorn/asyncpg
    import uvicorn  # noqa: PLC0415  (lazy import by design)

    from app.config import Settings
    from app.db import make_pg_repo
    from app.api import create_app
    from app.ingestor import Ingestor
    from app.backfill import backfill

    settings = Settings.from_env()

    # ------------------------------------------------------------------
    # Repository (Postgres)
    # ------------------------------------------------------------------
    repo = await make_pg_repo(settings.db_dsn)

    # ------------------------------------------------------------------
    # Optional backfill from spot files
    # ------------------------------------------------------------------
    if settings.backfill_on_start:
        spot_dir = settings.spot_files_dir
        if os.path.isdir(spot_dir):
            logger.info("Running spot-file backfill from %s …", spot_dir)
            count = await backfill(repo, spot_dir)
            logger.info("Backfill inserted %d spots", count)
        else:
            logger.info(
                "backfill_on_start=True but %s does not exist; skipping",
                spot_dir,
            )

    # ------------------------------------------------------------------
    # FastAPI app + ingestor
    # ------------------------------------------------------------------
    app = create_app(repo)
    ingestor = Ingestor(settings, repo, app.state.hub)

    # Start ingestor as a background task
    ingestor_task = asyncio.create_task(ingestor.run(), name="ingestor")

    # ------------------------------------------------------------------
    # Uvicorn server — runs until process is interrupted
    # ------------------------------------------------------------------
    config = uvicorn.Config(
        app,
        host="0.0.0.0",
        port=8000,
        log_level="info",
    )
    server = uvicorn.Server(config)
    try:
        await server.serve()
    finally:
        await ingestor.stop()
        ingestor_task.cancel()
        try:
            await ingestor_task
        except (asyncio.CancelledError, Exception):
            pass


def main() -> None:
    """Synchronous entry point called by the ``stats-svc`` console script."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    asyncio.run(amain())


if __name__ == "__main__":
    main()
