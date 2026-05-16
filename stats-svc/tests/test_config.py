import os
from app.config import Settings

def test_settings_from_env(monkeypatch):
    monkeypatch.setenv("DX_DB_DSN","postgres://u:p@db/x")
    monkeypatch.setenv("DX_HOST","dxspider")
    monkeypatch.setenv("DX_PORT","7300")
    monkeypatch.setenv("DX_MONITOR_USER","statsmon")
    monkeypatch.setenv("DX_MONITOR_PASSWORD","secret")
    s = Settings.from_env()
    assert s.db_dsn == "postgres://u:p@db/x"
    assert s.dx_host == "dxspider"
    assert s.dx_port == 7300
    assert s.users_poll_seconds == 20
    assert s.backfill_on_start is True

def test_settings_defaults(monkeypatch):
    for k in ["DX_DB_DSN","DX_HOST","DX_PORT","DX_MONITOR_USER","DX_MONITOR_PASSWORD",
              "DX_USERS_POLL_SECONDS","DX_BACKFILL_ON_START","DX_SPOT_FILES_DIR"]:
        monkeypatch.delenv(k, raising=False)
    s = Settings.from_env()
    assert s.dx_port == 7300
    assert s.users_poll_seconds == 20
    assert s.backfill_on_start is True
    assert s.spot_files_dir == "/spider-spots/spots"
