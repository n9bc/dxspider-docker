# DXSpider Docker

> A self-hosted amateur-radio DX cluster running as a four-service Docker Compose stack.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/downloads/)
[![Tests](https://img.shields.io/badge/tests-171%20passing-brightgreen.svg)](stats-svc/)
[![Made with FastAPI](https://img.shields.io/badge/Made%20with-FastAPI-009688.svg)](https://fastapi.tiangolo.com/)

**DXSpider** provides the cluster engine (telnet on port 7300, PC-protocol inter-cluster peering in Phase 2). A Python sidecar ingests the live spot stream, stores spots in Postgres, and serves a statistics dashboard with real-time charts and a live connected-users panel. Caddy handles TLS termination and reverse-proxying.

Public repository: **https://github.com/n9bc/dxspider-docker**

---

## Status

**v0.1.0** — initial release.

- Python test suite (parsers, aggregation, API, WebSocket): **171 passing, 0 skipped**.
- Container build and Compose integration are authored and peer-reviewed but **have not yet been brought up in a Docker environment** (the authoring host had no Docker). Bringing the stack up with `docker compose up -d` is the operator's first step; see the first-run checklist in [docs/deployment.md](docs/deployment.md) and [docs/troubleshooting.md](docs/troubleshooting.md). Docker-independent logic was fully tested locally with Python; container images pin Python 3.12.
- See [VERIFICATION.md](VERIFICATION.md) for the full verification report.

---

## Features

- **DXSpider telnet cluster node** — full DXSpider engine on port 7300; operators connect with any telnet client or logging software.
- **Sysop web console** — ttyd wraps `console.pl` and is proxied by Caddy at `/cluster`; protected by HTTP basic auth.
- **Live stats dashboard** — single-page HTML/ECharts dashboard served by FastAPI at `/`:
  - Activity over time (spots per hour/day, up to last 168 h)
  - Band and mode distribution (pie/bar charts)
  - Geographic breakdown — top DX entities, top spotting entities, by continent
  - Top spotters and most-spotted DX leaderboards
  - Rare-DX highlights
  - Per-callsign drill-down
  - Human / RBN source filter on every chart
- **WebSocket live ticker** — new spots and connected-users snapshots pushed to every open browser tab in real time.
- **Spot ingestion** — persistent telnet monitor session; every spot tagged `source=human` or `source=rbn` at ingest time; frequency mapped to band + mode; callsign prefix resolved to DXCC entity + continent.
- **Connected-users panel** — `show/users` polled every 20 s (configurable); live count displayed on the dashboard.
- **Optional first-boot backfill** — reads existing CSV/TSV `*.spots` files from the shared `dxspider-data` volume on first start (`DX_BACKFILL_ON_START=true`). Note: DXSpider's native Perl/Data::Dumper spot-file format is not parsed in v1; backfill is a no-op on a fresh or native-format data volume (Phase 2 item). Charts populate from the live ingestor from the moment the stack starts.
- **Automatic TLS** — Caddy obtains and renews Let's Encrypt certificates automatically when `DOMAIN` is set to a real FQDN.

---

## Architecture

Four-service Docker Compose stack (`docker-compose.yml`):

```
                           ┌─────────────────────────────────────────┐
                           │             Docker host                  │
                           │                                          │
  Internet / LAN           │  ┌─────────┐   /         ┌──────────┐  │
 ──────────────────────────┼──│  caddy  │─────────────▶│stats-svc │  │
   port 80 / 443 (HTTP/S)  │  │  :80    │   /cluster   │  :8000   │  │
                           │  │  :443   │─────────┐   └──────┬───┘  │
                           │  └─────────┘         │          │       │
                           │                      │          │ telnet │
  Ham operators / nodes    │                      ▼          ▼       │
 ──────────────────────────┼─────────── port 7300 ──────────────────▶│
   port 7300 (telnet)      │                  ┌──────────┐           │
                           │                  │ dxspider │           │
                           │                  │  :7300   │           │
                           │                  │  :8080   │◀──────────┤ /cluster
                           │                  └──────────┘           │  (ttyd)
                           │                       │                 │
                           │              shared dxspider-data       │
                           │              volume (spots, read-only)  │
                           │                       │                 │
                           │                  ┌────▼─────┐          │
                           │                  │ postgres  │          │
                           │                  │  :5432    │          │
                           │                  └───────────┘          │
                           └─────────────────────────────────────────┘

Data flows:
  caddy → stats-svc:8000          Dashboard and API  (all paths except /cluster)
  caddy → dxspider:8080           Sysop web console  (/cluster* via ttyd)
  stats-svc ingestor → dxspider:7300 → postgres      Live spot ingestion
  stats-svc backfill ← dxspider-data (read-only)     First-boot history load
  ham operators → host:7300 → dxspider               Telnet cluster access
```

Services at a glance:

| Service | Image | Role |
|---------|-------|------|
| `dxspider` | Custom (Debian slim + Perl) | DXSpider engine + ttyd sysop console |
| `stats-svc` | Custom (Python 3.12) | Telnet ingestor + FastAPI dashboard |
| `postgres` | `postgres:16` | Durable spot and user store |
| `caddy` | `caddy:2.8` | TLS termination + reverse proxy |

---

## Quick Start

### Prerequisites

- Docker Engine 24+ and Docker Compose v2
- Ports 80, 443, and 7300 open in your host firewall
- A registered amateur radio callsign

### Steps

```bash
# 1. Clone
git clone https://github.com/n9bc/dxspider-docker.git
cd dxspider-docker

# 2. Create your local env file
cp .env.example .env

# 3. Edit .env — at minimum set:
#    NODE_CALL, SYSOP_CALL, SYSOP_NAME, LOCATOR, NODE_QTH
#    TTYD_PASSWORD, DX_MONITOR_PASSWORD
#    POSTGRES_PASSWORD  (and update DX_DB_DSN to match)
#    DOMAIN  (leave as "localhost" for local testing)
nano .env   # or your editor of choice

# 4. Build images and start the stack
docker compose up -d --build

# 5. Watch logs until all services are healthy
docker compose logs -f
docker compose ps
```

The first build clones DXSpider source from GitHub and may take 2–3 minutes depending on network speed.

### URLs

| What | URL |
|------|-----|
| Stats dashboard | `http(s)://DOMAIN/` |
| Sysop web console | `http(s)://DOMAIN/cluster` |
| Telnet cluster access | `telnet DOMAIN 7300` |

Replace `DOMAIN` with the value set in `.env` (`localhost` for local testing, or your public FQDN when auto-TLS is enabled).

### Quick smoke test

```bash
# All four services should show "healthy" or "running"
docker compose ps

# API health check
curl http://localhost/api/health

# Telnet
telnet localhost 7300
```

---

## Documentation

Full technical documentation lives under `docs/`. The files listed below are being written as part of this release; link here for orientation and detail.

| Document | Contents |
|----------|----------|
| [docs/architecture.md](docs/architecture.md) | Container design, volumes, networking, data model |
| [docs/configuration.md](docs/configuration.md) | All `.env` variables with defaults and guidance |
| [docs/deployment.md](docs/deployment.md) | Step-by-step bring-up, TLS, firewall, first-run checklist |
| [docs/operations.md](docs/operations.md) | Backup, restore, upgrades, log management |
| [docs/development.md](docs/development.md) | Dev environment, running tests, project layout |
| [docs/api.md](docs/api.md) | REST and WebSocket endpoint reference |
| [docs/dashboard.md](docs/dashboard.md) | Dashboard views, filters, chart descriptions |
| [docs/dxspider.md](docs/dxspider.md) | DXSpider configuration, source/version, ttyd console |
| [docs/troubleshooting.md](docs/troubleshooting.md) | Common first-run problems and resolutions |
| [docs/phase-2.md](docs/phase-2.md) | Partner peering, RBN aggregator — config-gated Phase 2 |

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Cluster engine | DXSpider (EA3CV `mojo` fork, Perl) |
| Sysop console | ttyd 1.7.7 |
| Ingestor + API | Python 3.12, FastAPI 0.115, asyncpg 0.30, uvicorn 0.34 |
| Charts | Apache ECharts (browser, no build step) |
| Database | PostgreSQL 16 |
| Reverse proxy / TLS | Caddy 2.8 (automatic Let's Encrypt) |
| Container runtime | Docker Engine 24+, Compose v2 |
| Tests | pytest 8.3.4, pytest-asyncio 0.25, httpx 0.28 |

---

## Contributing

Contributions are welcome. Please read [CONTRIBUTING.md](CONTRIBUTING.md) for setup instructions, the TDD expectation, and PR conventions.

---

## Security

See [SECURITY.md](SECURITY.md) for the project's security posture, supported versions, and how to report a vulnerability privately.

**Before exposing your node to the internet:** change every default password in `.env` (`TTYD_PASSWORD`, `DX_MONITOR_PASSWORD`, `POSTGRES_PASSWORD` / `DX_DB_DSN`).

---

## License

MIT — see [LICENSE](LICENSE).

---

## Acknowledgements

- **DXSpider** by Dirk Koopman G1TLH and contributors. This project uses the [EA3CV `mojo` fork](https://github.com/EA3CV/dx-spider) (the primary HTTPS-accessible mirror carrying current development). The canonical upstream source is `git://scm.dxcluster.org/scm/spider` (port 9418, git protocol only) — see [docs/dxspider.md](docs/dxspider.md) for source-override instructions and production self-mirror recommendations.
- **ttyd** by Shuanglei Tao — browser-based terminal emulator used for the sysop web console.
