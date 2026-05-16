# Development Guide — Local Development Without Docker

This guide explains how to work on `stats-svc` without Docker: running the test
suite, understanding the module layout, the TDD workflow, and how to spin up the
FastAPI app locally for UI work.

---

## Prerequisites

- Python 3.12 or later (Python 3.14 was used during the verified build; 3.12+ is
  the stated target for containers).
- Git (to clone the repo).
- No Docker required for any step in this guide.

---

## Virtual Environment Setup

All Python work lives under `stats-svc/`. Create a venv there and install the
development dependencies:

```bash
cd stats-svc
python -m venv .venv

# Windows
.venv\Scripts\activate

# macOS / Linux
source .venv/bin/activate

pip install -r requirements-dev.txt
```

`requirements-dev.txt` pins the following packages (as of the last verified
build):

```
-r requirements.txt          # fastapi, uvicorn[standard], asyncpg
pytest==8.3.4
pytest-asyncio==0.25.2
httpx==0.28.1
websockets==14.1
```

`uvicorn` and `asyncpg` are listed in `requirements.txt` but are **lazily
imported** in `app/main.py` and `app/db.py` — neither is imported at module
level — so the test suite runs without them if you choose a minimal install.
The dev requirements include them transitively through `requirements.txt`.

---

## Running the Test Suite

**The working directory matters.** `pytest.ini` sets `asyncio_mode = auto` and
`pythonpath = .`. Both settings are only applied when pytest loads `pytest.ini`,
which it does by searching upward from the invocation directory. If you run
pytest from the repo root instead of `stats-svc/`, pytest finds no `pytest.ini`
and silently disables asyncio auto-mode, causing every async test to be
**wrongly skipped** rather than run.

Always run from `stats-svc/`:

```bash
# From C:\dev\dxspider\stats-svc (Windows) or stats-svc/ (Unix)
python -m pytest -q
```

Expected result: **171 passed, 0 skipped, 0 failures**.

Other useful invocations:

```bash
# Verbose output with test names
python -m pytest -v

# Run a single module
python -m pytest tests/test_parsers.py -v

# Run tests matching a keyword
python -m pytest -k "rbn" -v

# Show the first failure immediately
python -m pytest -x -q
```

---

## pytest.ini Settings

```ini
[pytest]
asyncio_mode = auto
testpaths = tests
pythonpath = .
```

- `asyncio_mode = auto` — every `async def test_*` is automatically treated as
  an async test; no `@pytest.mark.asyncio` decorator needed.
- `testpaths = tests` — pytest only looks in the `tests/` subdirectory.
- `pythonpath = .` — adds `stats-svc/` to `sys.path` so `from app.xxx import ...`
  works without an editable install.

---

## Project Layout — Module by Module

```
stats-svc/
  app/
    bands.py        Band and mode classification
    dxcc.py         DXCC prefix resolution
    parsers.py      Telnet line parsers → typed records
    repo.py         Repo ABC + MemoryRepo (DB-free)
    db.py           PgRepo — asyncpg Postgres implementation
    aggregate.py    Chart aggregation functions
    api.py          FastAPI app factory, REST routes, WebSocket, static mount
    ingestor.py     Telnet monitor client, reconnect, users poll
    backfill.py     One-time spot-file import on startup
    main.py         Entry point — wires everything, starts uvicorn
    config.py       Settings dataclass from environment variables
    static/
      index.html    Dashboard page (ECharts via CDN)
      app.js        Dashboard JS (fetch, WebSocket, ECharts renders)
      style.css     Dashboard CSS
  data/
    dxcc_prefixes.csv  Bundled prefix → DXCC/continent table
  tests/
    test_bands.py
    test_dxcc.py
    test_parsers.py
    test_repo.py
    test_config.py
    test_aggregate.py
    test_api.py
    test_ingestor.py
    test_backfill.py
    test_main_importable.py
  pytest.ini
  requirements.txt
  requirements-dev.txt
```

### `bands.py`

Pure functions with no external dependencies.

- `band_for_khz(khz: float) -> str | None` — returns the IARU amateur band name
  (`"20m"`, `"40m"`, etc.) for a frequency in kHz, or `None` if out-of-band.
  Covers 160m through 70cm.
- `mode_for_khz_comment(khz: float, comment: str) -> str | None` — infers the
  mode by (1) scanning the comment for keywords (`FT8`, `FT4`, `JT65`, `JT9`,
  `RTTY`, `PSK31`, `PSK`, `CW`, `USB`/`LSB`/`SSB`, `AM`, `FM`) then (2) falling
  back to IARU Region 1 band-plan sub-segment inference (below the split point →
  `"CW"`, above → `"SSB"`).

Tests: `tests/test_bands.py`.

### `dxcc.py`

Pure module; loads `data/dxcc_prefixes.csv` once at import time into a
longest-first sorted list.

- `resolve(call: str) -> Dxcc` — normalises the callsign (uppercase, strips
  `/P`/`/M`/`/QRP` portable suffixes, handles `PREFIX/CALL` operating-location
  form, returns `Dxcc(None, None, None)` for `/MM` and `/AM` maritime/aero
  mobile). Returns a frozen `Dxcc(entity, continent, cq_zone)` dataclass.

Tests: `tests/test_dxcc.py`.

### `parsers.py`

Regex-based telnet line dispatcher. No external dependencies beyond `bands` and
`dxcc`.

- `parse_line(line: str) -> SpotRecord | InfoRecord | None` — dispatches a single
  raw telnet line. Returns a `SpotRecord` for DX spots, an `InfoRecord` for WWV,
  WCY, or announce lines, and `None` for blank or unrecognised lines. Never
  raises.
- `parse_users_block(text: str) -> list[ConnectedUser]` — tolerant scanner for
  multi-line `show/users` output.
- RBN detection: a spotter callsign ending in `-#` or a comment containing both
  `\d+ dB` and `\d+ WPM` patterns marks the spot as `source="rbn"`.

Tests: `tests/test_parsers.py` (highest-risk module, most extensive test
coverage).

### `repo.py`

Defines the `Repo` abstract base class (the storage interface) and `MemoryRepo`
(the in-memory implementation used by all unit and integration tests).

`MemoryRepo` stores spots in a plain Python list, maintains a dedup set keyed on
`(ts, spotter, dx_call, freq_khz)`, and builds the hourly rollup incrementally
in a dict. All methods are `async` to match the `Repo` contract even though they
do no I/O. This lets every test in `test_aggregate.py`, `test_api.py`,
`test_ingestor.py`, and `test_backfill.py` run without a database.

### `db.py`

The Postgres-backed `PgRepo` implementation using `asyncpg`. Defines
`SCHEMA_SQL` (idempotent DDL for `spots`, `connected_users`,
`spot_rollup_hourly`) and `make_pg_repo(dsn)`. `asyncpg` is imported lazily so
that `import app.db` is safe in test environments where it is not installed.

### `aggregate.py`

All chart aggregation logic. All functions are `async` and accept a `Repo`
instance plus keyword filters. They return JSON-serialisable plain structures
(lists of dicts or a dict). See `docs/api.md` for return shapes.

The breakdown functions (`activity_series`, `band_breakdown`, `mode_breakdown`,
`geo_breakdown`) work from `repo.rollup_rows()` — the pre-aggregated hourly
table — for efficiency. The callsign-level functions (`top_spotters`, `top_dx`,
`rare_dx`, `callsign_detail`) call `repo.fetch_spots()` because individual
callsigns are not retained in the rollup.

Tests: `tests/test_aggregate.py`.

### `api.py`

FastAPI application factory. `create_app(repo: Repo) -> FastAPI` — no database
connection is created at import time. The app factory pattern lets tests pass a
`MemoryRepo` with zero environment-variable or database setup.

The `BroadcastHub` attached to `app.state.hub` fans out events (spots, WWV/WCY,
announce, users snapshots) to all connected WebSocket clients via per-connection
`asyncio.Queue` instances. Static files are mounted last at `/` so `/api/*` and
`/ws` take precedence.

Tests: `tests/test_api.py` (uses `httpx.AsyncClient` with ASGI transport and a
seeded `MemoryRepo`).

### `ingestor.py`

Async telnet monitor client. `Ingestor.run()` connects to DXSpider, logs in as
the monitor user, sends `MONITOR_SETUP_COMMANDS`, then starts two concurrent
tasks: the line-stream consumer (`process_lines`) and the periodic users poller
(`_users_poll_loop`). Reconnects with full-jitter exponential back-off (base 1 s,
cap 60 s) on failure.

`process_lines(line_iter)` is a pure async method that accepts any
`AsyncIterator[str]` — this is what the tests exercise using a scripted fake
stream without opening a real socket.

Tests: `tests/test_ingestor.py`.

### `backfill.py`

One-time spot-file import run at startup when `DX_BACKFILL_ON_START=true`. Scans
`DX_SPOT_FILES_DIR` recursively for `*.spots` files (CSV or TSV, 5+ fields:
`freq_khz,dx_call,iso_timestamp,spotter,comment`). Uses `repo.insert_spot_dedup`
so re-running is idempotent.

**Important:** DXSpider's native spot files are Perl `Data::Dumper` dumps, not
CSV/TSV. The v1 backfill only handles the custom CSV/TSV format; native-format
parsing is a Phase 2 item. On a fresh bring-up without pre-prepared `.spots`
files the backfill inserts 0 rows (harmless), and charts fill from the live
ingestor.

Tests: `tests/test_backfill.py`.

### `main.py`

Entry point. `amain()` is an async function that: loads `Settings.from_env()`,
creates the `PgRepo` (via `make_pg_repo`), optionally runs backfill, creates the
FastAPI app, starts the `Ingestor` as a background task, then runs uvicorn on
`0.0.0.0:8000`. Both `uvicorn` and `asyncpg` are imported inside `amain()` —
never at module level — so `import app.main` succeeds in test environments
without those packages.

Tests: `tests/test_main_importable.py` (verifies the lazy-import guard).

### `config.py`

`Settings` is a frozen dataclass constructed by `Settings.from_env()`. All
fields are read from environment variables with documented defaults:

| Env var | Default | Description |
|---|---|---|
| `DX_DB_DSN` | `postgresql://dxstats:dxstats@postgres:5432/dxstats` | asyncpg DSN |
| `DX_HOST` | `dxspider` | DXSpider container hostname |
| `DX_PORT` | `7300` | DXSpider telnet port |
| `DX_MONITOR_USER` | `statsmon` | Monitor account callsign |
| `DX_MONITOR_PASSWORD` | `changeme` | Monitor account password |
| `DX_USERS_POLL_SECONDS` | `20` | Seconds between `show/users` polls |
| `DX_BACKFILL_ON_START` | `true` | Run spot-file backfill at startup |
| `DX_SPOT_FILES_DIR` | `/spider-spots/spots` | Directory scanned for `*.spots` files |

---

## How `MemoryRepo` Enables DB-Free Testing

Every test module that exercises logic above the storage layer injects a
`MemoryRepo` directly into the function or factory under test:

```python
from app.repo import MemoryRepo
from app.api import create_app

repo = MemoryRepo()
# seed test data ...
app = create_app(repo)
# test via httpx ASGI client
```

`MemoryRepo` satisfies the full `Repo` abstract interface with pure-Python
in-memory structures. No `asyncpg`, no Postgres, no environment variables are
needed. The dedup key, rollup logic, and query semantics mirror `PgRepo` exactly,
so aggregation and API tests exercise real production logic.

---

## Running the FastAPI App Locally for UI Work

To iterate on the dashboard without Docker:

```bash
# From stats-svc/
DX_DB_DSN=... DX_HOST=localhost DX_PORT=7300 python -m app.main
```

Or, if you want to skip the ingestor and just view static charts with no data,
you can start the app with a `MemoryRepo` by writing a small launcher script:

```python
# dev_server.py (run from stats-svc/)
import uvicorn
from app.repo import MemoryRepo
from app.api import create_app

app = create_app(MemoryRepo())

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)
```

```bash
python dev_server.py
# Open http://localhost:8000
```

The dashboard will load with empty charts. Both `uvicorn` and `asyncpg` are
optional at import of `app.api` and `app.repo` — only `app.main` and `app.db`
import them (lazily). The pattern above avoids both.

---

## TDD Workflow

The project was built test-first. The recommended workflow for new features or
bug fixes:

1. Write a failing test in the appropriate `tests/test_*.py` file.
2. Run `python -m pytest tests/test_<module>.py -v` from `stats-svc/` to confirm
   the failure.
3. Implement the minimum code to make the test pass.
4. Run the full suite (`python -m pytest -q`) to confirm no regressions.
5. Refactor if needed; run the full suite again.

For async code, `pytest-asyncio` with `asyncio_mode = auto` means any
`async def test_*` function is automatically awaited — no decorator needed.

---

## Coding Conventions

- Python 3.12+ type hints throughout; `from __future__ import annotations` at
  the top of every module.
- `__all__` is defined in every public module.
- Async functions use `async def`; synchronous helpers stay synchronous.
- Empty/missing string values from the rollup are normalised to `"unknown"` in
  API responses (handled in `aggregate.py` by `_label()`).
- `parse_line` and all public parsers: never raise — catch all exceptions and
  return `None`.
- Lazy imports for optional heavy dependencies (`uvicorn`, `asyncpg`) — import
  inside the function that needs them, not at module level.

---

## Where the Spec and Plan Live

```
docs/superpowers/specs/2026-05-16-dockerized-dx-cluster-design.md
docs/superpowers/plans/2026-05-16-dockerized-dx-cluster.md
```

The spec (`design.md`) covers architecture, data model, dashboard views, and
Phase 2 scope guardrails. The plan (`plans/*.md`) is the task-by-task
implementation checklist used during the autonomous build session.
