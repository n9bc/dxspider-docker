# Architecture

## Overview

The DX Cluster stack is a four-service Docker Compose application. Each service has a single, well-defined responsibility. Together they implement a publicly accessible amateur-radio DX cluster with a live statistics dashboard.

```
Internet / LAN
    │
    ├─── ham operators ──► host:7300 ──────────────────────► dxspider (telnet, cluster.pl)
    │                                                              │
    └─── browsers/ops ──► caddy :80/:443                          │
                               │                                   │
                  ┌────────────┴──────────────┐                    │
                  │ /cluster*                 │ /                  │
                  ▼                           ▼                    │
          dxspider:8080               stats-svc:8000               │
          (ttyd console)           (FastAPI + WebSocket)           │
                                          │                        │
                               ┌──────────┴─────────┐             │
                               │ ingestor (background)│            │
                               │ asyncio.create_task  │◄───────────┘
                               │   telnet monitor     │  (internal telnet connection)
                               └──────────┬─────────┘
                                          │
                                          ▼
                                    postgres:5432
                                  (asyncpg pool)
                                          │
                              ┌───────────┘
                              │ also reads (read-only) on startup:
                              ▼
                       /spider-spots/spots
                    (dxspider-data volume, :ro mount)
                         backfill *.spots files
```

---

## Services

### dxspider

**Purpose:** The DXSpider cluster engine. Accepts telnet connections from ham operators on port 7300 and from the stats-svc ingestor on the same port. Manages spot propagation, user sessions, and (in Phase 2) inter-cluster peering.

**Image:** Built locally from `./dxspider`. Base image is `debian:bookworm-slim`. The DXSpider Perl source is cloned from the EA3CV `mojo` fork at build time (SHA-pinned; see Source Provenance below). The `mojo` branch uses Mojolicious as an async I/O event loop — it does not provide a native web UI.

**Processes inside the container (managed by entrypoint.sh):**
- `cluster.pl` — the DXSpider node process, runs as user `sysop` (uid 1000, gid 251).
- `ttyd` — a pinned static binary (v1.7.7, x86_64) that wraps `console.pl` in a browser-accessible terminal session on port 8080. Protected by HTTP basic auth (`TTYD_USER` / `TTYD_PASSWORD`).

**PID 1:** `tini` (from Debian `bookworm` apt), which forwards signals correctly and reaps zombie processes.

**Config files generated at first boot:**
- `/spider/local/DXVars.pm` — node identity (callsign, locator, QTH, paths).
- `/spider/local/Listeners.pm` — telnet listener address and port.

Both files are rendered from templates under `/spider/templates/` by `entrypoint.sh` using `sed` substitution. They are written only on first run or when `OVERWRITE_CONFIG=yes`; operator edits in the named volume survive restarts.

**Persistent volumes:**
- `dxspider-config` → `/spider/local` — rendered config files.
- `dxspider-data` → `/spider/local_data` — runtime state: users DB, spot files, log, debug, messages.

**Ports published to host:** `7300` (telnet). Port `8080` (ttyd) is internal-only; Caddy reverse-proxies it.

---

### stats-svc

**Purpose:** Two cooperating roles in a single Python container.

1. **Ingestor** — a persistent background `asyncio` task that connects to DXSpider via telnet as a monitor user, parses the live stream of DX spots, WWV/WCY propagation data, and announcements, then writes to Postgres. Periodically polls `show/users` to update the connected-users snapshot.
2. **Web API + dashboard** — a FastAPI application serving REST endpoints, a WebSocket live feed (`/ws`), and a static HTML dashboard.

**Image:** Built locally from `./stats-svc`. Base image is `python:3.12-slim`. Runs as `appuser` (uid 10001).

**Startup sequence (see `app/main.py`):**
1. Load `Settings` from environment.
2. Connect to Postgres via `asyncpg`; apply `SCHEMA_SQL` idempotently (`CREATE TABLE IF NOT EXISTS`).
3. Run backfill if `DX_BACKFILL_ON_START=true` and the spot-files directory exists.
4. Create the `FastAPI` app via `create_app(repo)`.
5. Start the `Ingestor` as a background `asyncio.Task`.
6. Serve with Uvicorn on `0.0.0.0:8000`.

**Port:** `8000` (internal only; Caddy proxies it).

---

### postgres

**Image:** `postgres:16` (official image, no local build).

**Purpose:** Durable storage for DX spots, connected-user snapshots, and pre-computed hourly rollup aggregates. Schema is applied idempotently by stats-svc at startup.

**Persistent volume:** `postgres-data` → `/var/lib/postgresql/data`.

**Port:** `5432` (internal only; never published to the host).

**Credentials:** Set via `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` in `docker-compose.yml`. The database name and user are both `dxstats` (hardcoded in compose; only the password is configurable via `.env`).

---

### caddy

**Image:** `caddy:2.8` (official image, no local build).

**Purpose:** Single ingress point for all HTTP(S) traffic. Performs TLS termination, security header injection, and reverse-proxy routing.

**Routing:**
| Path | Upstream | Notes |
|---|---|---|
| `/cluster` and `/cluster/*` | `dxspider:8080` | Prefix stripped before forwarding (`handle_path`); WebSocket upgrade handled automatically for ttyd terminal stream |
| Everything else | `stats-svc:8000` | Includes `/`, `/api/*`, `/ws` |

**TLS:** Controlled by the `DOMAIN` environment variable.
- `DOMAIN=localhost` (default) — plain HTTP on port 80.
- `DOMAIN=dx.example.com` (any FQDN) — Caddy obtains a Let's Encrypt certificate automatically; both ports 80 and 443 are used.

**Security headers applied to all responses:** `X-Content-Type-Options: nosniff`, `X-Frame-Options: SAMEORIGIN`, `Referrer-Policy: strict-origin-when-cross-origin`, `Server` header removed.

**Ports published to host:** `80`, `443`.

**Persistent volume:** `caddy-data` → `/data` (ACME account key and certificate cache).

---

## Ingestor → Parser → Repo → Postgres Path

```
DXSpider telnet stream
        │
        ▼
  asyncio.open_connection(dxspider:7300)
        │  (login + MONITOR_SETUP_COMMANDS)
        │
        ▼
  Ingestor.process_lines(line_iter)
        │
        ├── parse_line(line)
        │       ├── _RE_DX match  → SpotRecord (kind="spot", source="human"|"rbn")
        │       ├── _RE_WWV match → InfoRecord (kind="wwv")
        │       ├── _RE_WCY match → InfoRecord (kind="wcy")
        │       ├── _RE_ANN match → InfoRecord (kind="announce")
        │       └── no match      → None (line silently discarded)
        │
        ├── SpotRecord → repo.insert_spot_dedup(rec, ts)
        │       └── PgRepo → INSERT INTO spots ... ON CONFLICT DO NOTHING
        │               └── _upsert_rollup → INSERT INTO spot_rollup_hourly ... ON CONFLICT DO UPDATE count+1
        │
        ├── InfoRecord → hub.broadcast({"type": rec.kind, "data": ...})
        │       (no DB write for v1)
        │
        └── spot inserted → hub.broadcast({"type": "spot", "data": ...})
                └── WebSocket clients receive JSON event
```

**Users poll (concurrent task):**
Every `DX_USERS_POLL_SECONDS` seconds (default 20), the ingestor sends `show/users\n` on the same telnet connection and accumulates response lines for up to 1 second, then calls `parse_users_block(text)` → `repo.replace_connected_users(users, snapshot_ts)` (DELETE then INSERT in a single transaction). The result is also broadcast to WebSocket clients.

**v1 limitation:** The `show/users` response is collected using a fixed 1-second window on the same stream that carries spot lines. This means spots arriving during the collection window are buffered by the OS and processed after the window closes rather than in real time. Protocol multiplexing is a documented Phase 2 item.

**Reconnect:** On any connection failure the ingestor uses exponential back-off with full jitter (base 1 s, cap 60 s) before retrying. A successful session resets the attempt counter.

---

## Repo Abstraction

`app/repo.py` defines an abstract base class `Repo` with six async methods:

| Method | Description |
|---|---|
| `insert_spot(spot, ts)` | Unconditional insert + rollup update |
| `insert_spot_dedup(spot, ts) → bool` | Insert only if `(ts, spotter, dx_call, freq_khz)` is new; returns `True` on insert |
| `spot_count() → int` | Total spots stored |
| `fetch_spots(since, until, source=None)` | Time-range query, optional source filter |
| `rollup_rows()` | All rows from the hourly rollup table |
| `replace_connected_users(users, snapshot_ts)` | Atomic replace of the entire users table |
| `connected_users()` | Current user snapshot |

**Two implementations:**

| Implementation | Module | Used by |
|---|---|---|
| `MemoryRepo` | `app/repo.py` | Unit tests (171 passing); no database, no `asyncpg` required |
| `PgRepo` | `app/db.py` | Production; built via `make_pg_repo(dsn)` which creates an `asyncpg` connection pool and applies the schema |

The live ingestor always calls `insert_spot_dedup` so that duplicate spots (e.g., from a reconnect) are silently dropped. Backfill also uses `insert_spot_dedup` for idempotency — running it twice produces 0 new rows the second time.

**Dedup key:** `(ts, spotter, dx_call, freq_khz)` — enforced as a unique index in Postgres (`spots_dedup_uidx`) and mirrored as a Python `set` in `MemoryRepo`.

**Rollup model:** Every successful spot insert also increments the matching row in `spot_rollup_hourly` (keyed by `hour_ts, band, mode, source, dx_dxcc, dx_continent, spotter_dxcc`). The rollup is maintained incrementally at insert time rather than computed on query, making chart endpoints fast even for large datasets.

---

## Data Model

Schema is defined in `app/db.py` (`SCHEMA_SQL`) and applied idempotently on startup.

### `spots`

| Column | Type | Notes |
|---|---|---|
| `id` | `BIGSERIAL` | Primary key |
| `ts` | `TIMESTAMPTZ NOT NULL` | Spot timestamp (UTC, set by ingestor clock at receipt time) |
| `spotter` | `TEXT NOT NULL` | Spotter callsign (RBN `-#` suffix stripped) |
| `dx_call` | `TEXT NOT NULL` | DX station callsign |
| `freq_khz` | `DOUBLE PRECISION NOT NULL` | Frequency in kilohertz |
| `band` | `TEXT` | Derived from frequency (e.g., `"40m"`) |
| `mode` | `TEXT` | Derived from frequency + comment (e.g., `"CW"`, `"SSB"`) |
| `source` | `TEXT NOT NULL DEFAULT 'human'` | `"human"` or `"rbn"` |
| `spotter_dxcc` | `TEXT` | DXCC entity of spotter (from prefix lookup) |
| `dx_dxcc` | `TEXT` | DXCC entity of DX station |
| `dx_continent` | `TEXT` | Continent of DX station |
| `comment` | `TEXT` | Free-text comment from spot line |
| `raw` | `TEXT` | Original unparsed telnet line |

**Indexes:** `spots_dedup_uidx` (unique, on `ts, spotter, dx_call, freq_khz`), `spots_ts_idx` (on `ts`), `spots_source_idx` (on `source`).

### `connected_users`

| Column | Type | Notes |
|---|---|---|
| `callsign` | `TEXT NOT NULL` | Primary key; upper-cased callsign |
| `conn_type` | `TEXT NOT NULL` | Connection type string from DXSpider |
| `since_ts` | `TIMESTAMPTZ` | Not populated in v1 (column exists for Phase 2) |
| `snapshot_ts` | `TIMESTAMPTZ NOT NULL` | Time of the `show/users` poll that produced this row |

The entire table is replaced atomically (DELETE then INSERT) on each poll.

### `spot_rollup_hourly`

| Column | Type | Notes |
|---|---|---|
| `hour_ts` | `TIMESTAMPTZ NOT NULL` | UTC hour boundary (minutes/seconds zeroed) |
| `band` | `TEXT NOT NULL DEFAULT ''` | Band string or empty string |
| `mode` | `TEXT NOT NULL DEFAULT ''` | Mode string or empty string |
| `source` | `TEXT NOT NULL` | `"human"` or `"rbn"` |
| `dx_dxcc` | `TEXT NOT NULL DEFAULT ''` | DX DXCC entity or empty string |
| `dx_continent` | `TEXT NOT NULL DEFAULT ''` | DX continent or empty string |
| `spotter_dxcc` | `TEXT NOT NULL DEFAULT ''` | Spotter DXCC entity or empty string |
| `count` | `BIGINT NOT NULL DEFAULT 0` | Running spot count for this combination |

**Primary key:** `(hour_ts, band, mode, source, dx_dxcc, dx_continent, spotter_dxcc)`.

`NULL` values from spots are coalesced to `''` at insert time so the composite primary key remains unique.

---

## Backfill

On startup (when `DX_BACKFILL_ON_START=true` and `DX_SPOT_FILES_DIR` exists), `app/backfill.py` scans recursively for `*.spots` files under `spot_files_dir`. Each file is expected to contain CSV or TSV lines with five fields: `freq_khz, dx_call, iso_timestamp, spotter, comment`.

**Important v1 limitation:** DXSpider natively writes spot files as Perl `Data::Dumper` format under `/spider/local_data/spots/`. The backfill parser handles only the CSV/TSV `*.spots` format. On a fresh first boot with no pre-converted spot files present, backfill inserts 0 historical spots — charts fill from the live ingestor stream. Native-format parsing is a documented Phase 2 extension.

---

## Network and Port Topology

| Port | Protocol | Published to host | Service | Purpose |
|---|---|---|---|---|
| `7300` | TCP | Yes | dxspider | DX cluster telnet (users + inter-cluster peering) |
| `80` | TCP | Yes | caddy | HTTP (and ACME HTTP-01 challenge) |
| `443` | TCP | Yes | caddy | HTTPS (when `DOMAIN` is an FQDN) |
| `8080` | TCP | No (internal) | dxspider | ttyd web console (accessed via `/cluster` through Caddy) |
| `8000` | TCP | No (internal) | stats-svc | FastAPI dashboard + WebSocket |
| `5432` | TCP | No (internal) | postgres | PostgreSQL |

All four services are on the Docker bridge network `cluster-net`. Service names resolve via Docker's internal DNS. The stats-svc ingestor connects to `dxspider:7300`. The API connects to `postgres:5432`. Caddy connects to `stats-svc:8000` and `dxspider:8080`.

---

## DXSpider Source: Trust and Provenance

The DXSpider source is cloned and pinned at image build time. The Dockerfile has three `ARG` declarations that control the source:

| Build arg | Default |
|---|---|
| `SPIDER_REPO` | `https://github.com/EA3CV/dx-spider.git` |
| `SPIDER_BRANCH` | `mojo` |
| `SPIDER_SHA` | `63d47180dc195e026bae23446eb9b798a0e923d6` |

The build clones the full branch history (no `--depth`), then checks out the exact SHA. The SHA is printed to the build log (`git log -1`) for audit.

**Why EA3CV mojo:** At the time of design, this was the only publicly available HTTPS source carrying current DXSpider code with the Mojolicious event-loop backend. The upstream `git://scm.dxcluster.org` server uses port 9418 (no HTTPS, CI-hostile). The `latchdevel/DXspider` mirror is a full-history faithful copy but was frozen at 2022-02-07.

**Alternatives documented in `dxspider/Dockerfile` and `.env.example`:**
- **Self-hosted mirror (recommended for production):** Mirror the EA3CV `mojo` branch to your own git server, verify the SHA, then pass `--build-arg SPIDER_REPO=https://git.example.com/dxspider.git` at build time.
- **latchdevel full-history mirror:** `--build-arg SPIDER_REPO=https://github.com/latchdevel/DXspider.git --build-arg SPIDER_BRANCH=master --build-arg SPIDER_SHA=e61ab5eeea22241ea8d8f1f6d072f5249901d788`

These `SPIDER_*` overrides are **build-time arguments only** — they are not environment variables read from `.env` or `docker-compose.yml`. They must be passed on the `docker compose build` CLI.

**ttyd:** The pinned static binary (`tsl0922/ttyd` v1.7.7) is x86_64. arm64 hosts must override `TTYD_URL` with an arm64 build: `--build-arg TTYD_URL=<arm64-url>`.
