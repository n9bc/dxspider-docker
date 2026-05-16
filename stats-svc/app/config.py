"""Application configuration loaded from environment variables.

All fields are immutable (frozen dataclass). Use ``Settings.from_env()`` to
construct an instance; no third-party libraries required.
"""

import os
from dataclasses import dataclass

__all__ = ["Settings"]

_TRUTHY = {"true", "1", "yes"}


@dataclass(frozen=True)
class Settings:
    db_dsn: str
    dx_host: str
    dx_port: int
    dx_monitor_user: str
    dx_monitor_password: str
    users_poll_seconds: int = 20
    backfill_on_start: bool = True
    spot_files_dir: str = "/spider-spots/spots"

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            db_dsn=os.environ.get(
                "DX_DB_DSN",
                "postgresql://dxstats:dxstats@postgres:5432/dxstats",
            ),
            dx_host=os.environ.get("DX_HOST", "dxspider"),
            dx_port=int(os.environ.get("DX_PORT", "7300")),
            dx_monitor_user=os.environ.get("DX_MONITOR_USER", "statsmon"),
            dx_monitor_password=os.environ.get("DX_MONITOR_PASSWORD", "changeme"),
            users_poll_seconds=int(os.environ.get("DX_USERS_POLL_SECONDS", "20")),
            backfill_on_start=os.environ.get(
                "DX_BACKFILL_ON_START", "true"
            ).strip().lower() in _TRUTHY,
            spot_files_dir=os.environ.get(
                "DX_SPOT_FILES_DIR", "/spider-spots/spots"
            ),
        )
