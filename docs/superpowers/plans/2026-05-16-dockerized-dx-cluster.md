# Dockerized DX Cluster Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A Docker Compose stack running DXSpider (telnet + web console + peering-ready) plus a custom Python stats service that ingests the live spot stream and serves a rich statistics dashboard.

**Architecture:** Four services — `dxspider` (cluster engine), `stats-svc` (Python ingestor + FastAPI dashboard), `postgres` (storage), `caddy` (TLS reverse proxy). The stats ingestor logs into DXSpider as a monitor telnet user, parses the live stream, and writes normalized spots to Postgres; FastAPI serves aggregated charts and a WebSocket live panel.

**Tech Stack:** Docker Compose, DXSpider (Perl), Python 3.12 (FastAPI, asyncpg/SQLAlchemy-core, pytest), Apache ECharts, Caddy 2, PostgreSQL 16.

---

## File Structure

```
docker-compose.yml          Orchestration of the four services
.env.example                Documented configuration variables
README.md                   Bring-up + Phase 2 enablement docs
caddy/Caddyfile             Reverse proxy + auto-TLS routing
dxspider/Dockerfile         DXSpider image from pinned source
dxspider/entrypoint.sh      Templates config from env, provisions monitor user
dxspider/templates/         DXSpider config templates (DXVars, etc.)
stats-svc/Dockerfile        Python service image
stats-svc/requirements.txt  Pinned Python deps
stats-svc/app/config.py     Env-driven settings
stats-svc/app/bands.py      freq_khz -> band; mode heuristics
stats-svc/app/dxcc.py       callsign prefix -> DXCC entity + continent
stats-svc/app/parsers.py    Telnet line parsers -> normalized records
stats-svc/app/db.py         Pool + schema DDL + upsert/rollup helpers
stats-svc/app/ingestor.py   Telnet monitor client, reconnect, users poll
stats-svc/app/backfill.py   First-boot spot-file import
stats-svc/app/aggregate.py  Chart aggregation queries
stats-svc/app/api.py        FastAPI REST + WebSocket + static mount
stats-svc/app/static/       index.html, app.js, style.css
stats-svc/data/dxcc_prefixes.csv  Bundled prefix table
stats-svc/tests/            pytest suite + fixtures
```

Files split by responsibility; parsers/bands/dxcc are pure functions (fully
unit-testable without Docker) and are the highest-risk components.

---

## Task 1: Repo scaffold + stats-svc package skeleton

**Files:**
- Create: `stats-svc/requirements.txt`, `stats-svc/app/__init__.py`,
  `stats-svc/tests/__init__.py`, `stats-svc/pytest.ini`

- [ ] Create `requirements.txt`: `fastapi`, `uvicorn[standard]`, `asyncpg`,
  `pytest`, `pytest-asyncio`, `httpx`, `websockets`, `python-dotenv`
  (versions pinned at implementation time to current stable).
- [ ] Create empty `app/__init__.py`, `tests/__init__.py`.
- [ ] Create `pytest.ini` with `asyncio_mode = auto` and `testpaths = tests`.
- [ ] Commit: `chore: scaffold stats-svc package`.

## Task 2: Band/mode mapping (TDD)

**Files:** Create `stats-svc/app/bands.py`, `stats-svc/tests/test_bands.py`

- [ ] **Write failing tests** in `test_bands.py`:

```python
from app.bands import band_for_khz, mode_for_khz_comment

def test_band_for_khz_hf():
    assert band_for_khz(14025.0) == "20m"
    assert band_for_khz(7005.0) == "40m"
    assert band_for_khz(3573.0) == "80m"
    assert band_for_khz(28400.0) == "10m"
    assert band_for_khz(50130.0) == "6m"

def test_band_for_khz_out_of_band_returns_none():
    assert band_for_khz(12345.0) is None

def test_mode_from_comment_keywords():
    assert mode_for_khz_comment(14074.0, "FT8 -12 dB") == "FT8"
    assert mode_for_khz_comment(14025.0, "CW") == "CW"
    assert mode_for_khz_comment(14200.0, "59 SSB") == "SSB"

def test_mode_falls_back_to_band_plan_segment():
    # 14025 in CW segment with empty comment
    assert mode_for_khz_comment(14025.0, "") == "CW"
    # 14250 in phone segment
    assert mode_for_khz_comment(14250.0, "") == "SSB"
```

- [ ] Run `pytest tests/test_bands.py -v` → FAIL (module missing).
- [ ] Implement `bands.py`: an ordered list of `(low_khz, high_khz, name)`
  band edges (160m–70cm IARU), `band_for_khz` returns the matching name or
  `None`; `mode_for_khz_comment` scans comment for `FT8|FT4|CW|RTTY|PSK|SSB|
  USB|LSB|AM|FM` keywords (case-insensitive, longest match), else infers from
  per-band CW/data/phone sub-segments table.
- [ ] Run tests → PASS.
- [ ] Commit: `feat(stats): band and mode classification`.

## Task 3: DXCC prefix resolution (TDD)

**Files:** Create `stats-svc/data/dxcc_prefixes.csv`,
`stats-svc/app/dxcc.py`, `stats-svc/tests/test_dxcc.py`

- [ ] Create `dxcc_prefixes.csv` with columns
  `prefix,entity,continent,cq_zone` covering the common allocations
  (a curated practical set — at minimum all ITU prefix blocks mapped to
  entity + continent; expandable). Longest-prefix match is the contract.
- [ ] **Write failing tests**:

```python
from app.dxcc import resolve

def test_resolve_simple():
    r = resolve("W1AW")
    assert r.entity == "United States" and r.continent == "NA"

def test_resolve_uses_longest_prefix():
    assert resolve("VP8LP").entity == "Falkland Islands"  # VP8 not V/VP
    assert resolve("VK9XX").continent == "OC"

def test_resolve_strips_portable_suffix():
    assert resolve("G3XYZ/P").entity == "England"
    assert resolve("DL1ABC/MM").entity == "England" or resolve("DL1ABC/MM").entity == "Germany"

def test_resolve_handles_portable_prefix():
    # F/G3XYZ operating in France -> France
    assert resolve("F/G3XYZ").continent == "EU"

def test_unknown_returns_none_entity():
    assert resolve("").entity is None
```

(Adjust the `/MM` maritime-mobile expectation in implementation: `/MM` and
`/AM` resolve to `None` entity, continent `None` — assert that explicitly.)

- [ ] Run tests → FAIL.
- [ ] Implement `dxcc.py`: load CSV once into a prefix trie / sorted list;
  `resolve(call)` normalizes (uppercase, strip whitespace), handles
  `PFX/CALL` (use left part as operating prefix) and `CALL/SFX` (ignore
  common suffixes `P,M,QRP,A,0-9`; `MM`/`AM` → unknown), then longest-prefix
  match. Returns dataclass `Dxcc(entity, continent, cq_zone)`.
- [ ] Finalize test expectations to match the documented suffix rules, run →
  PASS.
- [ ] Commit: `feat(stats): DXCC prefix resolution`.

## Task 4: Telnet line parsers (TDD — highest risk)

**Files:** Create `stats-svc/app/parsers.py`,
`stats-svc/tests/test_parsers.py`, `stats-svc/tests/fixtures/lines.txt`

- [ ] Collect fixture lines covering DXSpider output variants:
  - Human DX spot: `DX de K1ABC:     14025.0  JA1XYZ       CW 599        1234Z`
  - RBN/skimmer spot: `DX de OH6BG-#:   14025.0  JA1XYZ       CW 12 dB 24 WPM CQ   1234Z`
  - WWV: `WWV de AR0NL <18>:   SFI=140, A=7, K=2, ...`
  - WCY: `WCY de DK0WCY-1 <12> : K=2 expK=0 A=10 R=120 SFI=140 ...`
  - Announce: `To ALL de G1ABC: Test announcement <1234Z>`
  - `show/users` block lines (multiple known DXSpider layouts).
- [ ] **Write failing tests** asserting each parser returns the exact
  normalized dict/dataclass:

```python
from app.parsers import parse_line, SpotRecord

def test_parse_human_spot():
    line = "DX de K1ABC:     14025.0  JA1XYZ       CW 599        1234Z"
    rec = parse_line(line)
    assert isinstance(rec, SpotRecord)
    assert rec.spotter == "K1ABC"
    assert rec.dx_call == "JA1XYZ"
    assert rec.freq_khz == 14025.0
    assert rec.source == "human"
    assert "CW 599" in rec.comment

def test_parse_rbn_spot_detected_by_skimmer_marker():
    line = "DX de OH6BG-#:   14025.0  JA1XYZ       CW 12 dB 24 WPM CQ   1234Z"
    rec = parse_line(line)
    assert rec.spotter == "OH6BG"
    assert rec.source == "rbn"

def test_parse_wwv():
    rec = parse_line("WWV de AR0NL <18>:   SFI=140, A=7, K=2")
    assert rec.kind == "wwv" and rec.sfi == 140 and rec.k == 2

def test_parse_announce():
    rec = parse_line("To ALL de G1ABC: Hello world <1234Z>")
    assert rec.kind == "announce" and rec.origin == "G1ABC"

def test_unparseable_returns_none():
    assert parse_line("random console noise") is None

def test_parse_users_block():
    from app.parsers import parse_users_block
    block = open("tests/fixtures/users_block.txt").read()
    users = parse_users_block(block)
    assert any(u.callsign == "K1ABC" for u in users)
```

- [ ] Run tests → FAIL.
- [ ] Implement `parsers.py`: regexes per line kind; `SpotRecord` carries
  `kind` (`spot|wwv|wcy|announce`), spot fields, RBN detection (spotter
  ending `-#`/`-#:` or skimmer comment grammar `\d+ dB \d+ WPM` / `dB ... Z`),
  uses `bands.band_for_khz`, `bands.mode_for_khz_comment`, `dxcc.resolve` to
  enrich. `parse_users_block` tolerant of the known column layouts.
- [ ] Iterate parsers until all fixtures pass; run → PASS.
- [ ] Commit: `feat(stats): telnet stream parsers`.

## Task 5: Config + DB layer

**Files:** Create `stats-svc/app/config.py`, `stats-svc/app/db.py`,
`stats-svc/tests/test_db_schema.py`

- [ ] `config.py`: `Settings` dataclass from env — DB DSN, DXSpider host/port,
  monitor user/pass, `USERS_POLL_SECONDS=20`, `BACKFILL_ON_START=true`,
  `SPOT_FILES_DIR=/spider/data/spots`.
- [ ] `db.py`: asyncpg pool factory; `SCHEMA_SQL` DDL for `spots`,
  `connected_users`, `spot_rollup_hourly` (per spec §5); `init_schema(pool)`;
  `insert_spot`, `replace_connected_users`, `bump_rollup` helpers; an idempotent
  `CREATE TABLE IF NOT EXISTS` design.
- [ ] **Test** (uses a Postgres test DSN if available, else marks skip): apply
  schema twice (idempotent), insert a spot, read it back, assert rollup count
  incremented. Provide a SQLite-free path: a thin `Repo` abstraction tested
  with a fake in-memory implementation so logic is verifiable without
  Postgres; integration against real Postgres covered in Task 10.
- [ ] Run tests → PASS (Repo logic tests pass without a DB).
- [ ] Commit: `feat(stats): config and database layer`.

## Task 6: Aggregation queries (TDD via Repo abstraction)

**Files:** Create `stats-svc/app/aggregate.py`,
`stats-svc/tests/test_aggregate.py`

- [ ] **Write failing tests** with a seeded fake repo: given a known set of
  spots, assert `activity_series`, `band_breakdown`, `mode_breakdown`,
  `geo_breakdown`, `top_spotters`, `top_dx`, all honoring
  `source in {human,rbn,both}` and a time window.
- [ ] Run → FAIL.
- [ ] Implement `aggregate.py`: functions taking a repo + filters returning
  plain serializable structures (lists of `{label, value}` / time buckets).
- [ ] Run → PASS.
- [ ] Commit: `feat(stats): chart aggregation logic`.

## Task 7: FastAPI app — REST + WebSocket + static (TDD)

**Files:** Create `stats-svc/app/api.py`, `stats-svc/app/static/index.html`,
`stats-svc/app/static/app.js`, `stats-svc/app/static/style.css`,
`stats-svc/tests/test_api.py`

- [ ] **Write failing tests** with httpx ASGI client + a seeded fake repo
  injected via dependency override: `/api/health` 200; `/api/activity`,
  `/api/bands`, `/api/modes`, `/api/geo`, `/api/top/spotters`,
  `/api/top/dx`, `/api/users` return expected JSON shapes; `source` and
  `range` query params validated; WebSocket `/ws` accepts and receives a
  pushed spot event.
- [ ] Run → FAIL.
- [ ] Implement `api.py`: FastAPI app, dependency-injected repo, the routes
  above, a broadcast hub for the WebSocket, static files mounted at `/`,
  serving the dashboard `index.html`.
- [ ] Build `index.html`/`app.js`/`style.css`: ECharts (vendored or CDN-pinned)
  rendering activity line, band & mode pies, geo bars, top-lists tables, and
  a live panel subscribing to `/ws` for the spot ticker + connected users.
- [ ] Run → PASS.
- [ ] Commit: `feat(stats): FastAPI API, WebSocket and dashboard UI`.

## Task 8: Ingestor + backfill

**Files:** Create `stats-svc/app/ingestor.py`, `stats-svc/app/backfill.py`,
`stats-svc/app/main.py`, `stats-svc/tests/test_ingestor.py`,
`stats-svc/tests/test_backfill.py`

- [ ] **Write failing tests**: feed a scripted async byte stream (fake reader)
  through the ingestor's line loop → assert parsed spots are written to the
  fake repo and broadcast; simulate disconnect → assert reconnect/backoff is
  attempted; `backfill` given a temp spot-file fixture → asserts rows
  inserted once and not duplicated on re-run.
- [ ] Run → FAIL.
- [ ] Implement `ingestor.py`: asyncio telnet client (open_connection),
  login as monitor user, send filter-set commands, read lines → `parse_line`
  → repo + broadcast; periodic `show/users` task; reconnect with
  exponential backoff + jitter. `backfill.py`: parse DXSpider spot files into
  `parse_line`-compatible records, idempotent insert (dedupe by
  ts+spotter+dx+freq). `main.py`: wires config → pool → schema → optional
  backfill → ingestor + uvicorn API together.
- [ ] Run → PASS.
- [ ] Commit: `feat(stats): telnet ingestor, users poll, backfill`.

## Task 9: stats-svc Dockerfile

**Files:** Create `stats-svc/Dockerfile`, `stats-svc/.dockerignore`

- [ ] `Dockerfile`: `python:3.12-slim`, non-root user, copy app, install
  pinned requirements, `CMD ["python","-m","app.main"]`, healthcheck hitting
  `/api/health`.
- [ ] Verify the image build instructions are internally consistent (paths,
  module entrypoint). (Build executed on Docker host.)
- [ ] Commit: `feat: stats-svc Dockerfile`.

## Task 10: DXSpider image + entrypoint

**Files:** Create `dxspider/Dockerfile`, `dxspider/entrypoint.sh`,
`dxspider/templates/DXVars.pm.tmpl`, `dxspider/templates/Listeners.pm.tmpl`

> Decision point — DXSpider source/version: resolve via the 3-agent
> consensus debate protocol (spec §12) before pinning.

- [ ] `Dockerfile`: Debian-slim base, install Perl + required CPAN modules
  (`Curses`, `Net::Telnet`, `Mojolicious`, `DBI`, `DBD::SQLite`, `Time::HiRes`,
  `Data::Dumper`, `JSON`, `Math::Round` per DXSpider needs), create non-root
  `sysop` user, clone DXSpider at the pinned ref into `/spider`, set perms.
- [ ] `entrypoint.sh`: render `DXVars.pm`/`Listeners.pm` from env via the
  templates, ensure `/spider/data` initialized on first run, create the
  registered monitor user (non-sysop) idempotently, then exec the cluster
  (`/spider/perl/cluster.pl`), with telnet listener on 7300 and the
  Mojolicious web console enabled.
- [ ] Templates use placeholders for `NODE_CALL`, `SYSOP_CALL`, `SYSOP_NAME`,
  `LOCATOR`, `SYSOP_PASSWORD`, `MONITOR_USER`, `MONITOR_PASSWORD`; a
  commented, env-gated Phase 2 partner-connect + RBN block included.
- [ ] Commit: `feat: DXSpider image and entrypoint`.

## Task 11: Compose, Caddy, env, README

**Files:** Create `docker-compose.yml`, `caddy/Caddyfile`, `.env.example`,
`README.md`

- [ ] `docker-compose.yml`: services `dxspider`, `stats-svc`, `postgres:16`,
  `caddy:2`; named volumes `dxspider-data`, `postgres-data`, `caddy-data`;
  `stats-svc` depends_on postgres + dxspider; only `7300` and Caddy `80/443`
  published; healthchecks; restart policies.
- [ ] `Caddyfile`: `{$DOMAIN}` site — `/cluster*` reverse_proxy to dxspider
  web console, everything else to `stats-svc:8000`; auto-HTTPS when DOMAIN
  set, `:80` fallback otherwise; security headers.
- [ ] `.env.example`: every variable documented with safe defaults and
  Phase-2 vars commented.
- [ ] `README.md`: quick start (`cp .env.example .env`, edit,
  `docker compose up -d`), architecture diagram, dashboard URL, telnet
  instructions, Phase 2 peering/RBN enablement steps, backup guidance,
  the no-Docker verification status note.
- [ ] Commit: `feat: compose stack, Caddy, env, README`.

## Task 12: Full verification pass

- [ ] Run the entire pytest suite from `stats-svc/` → all green; capture
  output.
- [ ] Static review of every Dockerfile/compose/Caddyfile for path and
  variable consistency against `.env.example`.
- [ ] Use the requesting-code-review skill for a final review.
- [ ] Write `VERIFICATION.md` recording what was tested automatically and the
  exact `docker compose up -d` steps the user runs on a Docker host.
- [ ] Final commit: `docs: verification report`.

---

## Self-Review

**Spec coverage:** §2 architecture → Tasks 9–11. §3 DXSpider → Task 10. §4
ingestor/web → Tasks 7,8. §5 data model → Task 5. §6 dashboard views → Task
7. §7 Caddy/TLS → Task 11. §8 persistence → Task 11. §9 testing → Tasks
2–8,12. §10 phases → ordered Tasks. §11 YAGNI → no auth/SPA/backup tasks
present. §12 decision protocol → Task 10 flagged. §13 env note → Task 12.
No gaps.

**Placeholder scan:** No TBD/TODO; test code shown for high-risk units;
infra tasks specify exact files and contents.

**Type consistency:** `SpotRecord`/`parse_line`/`resolve`/`band_for_khz`/
`mode_for_khz_comment` names used consistently across Tasks 2–8; `Repo`
abstraction introduced Task 5, reused Tasks 6–8.
