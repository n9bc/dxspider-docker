# DX Cluster — Dockerized DXSpider + Stats Dashboard

A self-hosted amateur-radio DX cluster running as a four-service Docker Compose
stack. DXSpider provides the cluster engine (telnet on port 7300, inter-cluster
peering in Phase 2). A Python sidecar ingests the live spot stream, stores spots
in Postgres, and serves a statistics dashboard with real-time charts and a live
user panel.

## Architecture

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
  caddy → stats-svc:8000          Dashboard and API (all paths except /cluster)
  caddy → dxspider:8080           Sysop web console via ttyd (path /cluster)
  stats-svc ingestor → dxspider:7300 → postgres   Live spot ingestion
  stats-svc backfill ← dxspider-data (read-only)  First-boot history load
  ham operators → host:7300 → dxspider            Telnet cluster access
```

## Quick start

### Prerequisites

- Docker Engine 24+ and Docker Compose v2
- Ports 80, 443, and 7300 open in your host firewall
- A registered amateur radio callsign

### Steps

```bash
# 1. Clone the repo (if you haven't already)
git clone https://github.com/your-org/dxcluster.git
cd dxcluster

# 2. Create your local env file
cp .env.example .env

# 3. Edit .env — at minimum set:
#      NODE_CALL, SYSOP_CALL, SYSOP_NAME, LOCATOR, NODE_QTH
#      TTYD_PASSWORD, DX_MONITOR_PASSWORD, POSTGRES_PASSWORD + DX_DB_DSN
#      DOMAIN (leave as localhost for local testing)
nano .env   # or your editor of choice

# 4. Build images and start the stack
docker compose up -d --build

# 5. Watch logs until all services are healthy
docker compose logs -f
```

The first build clones DXSpider source from GitHub and may take 2–3 minutes
depending on network speed.

### URLs

| What | URL |
|---|---|
| Stats dashboard | `http(s)://DOMAIN/` |
| Sysop web console | `http(s)://DOMAIN/cluster` |
| Telnet cluster access | `telnet DOMAIN 7300` |

Replace `DOMAIN` with the value you set in `.env` (e.g., `localhost` for local
testing, or your public FQDN when `DOMAIN` is set for auto-TLS).

### Verifying the stack is up

```bash
# All four services should show "healthy" or "running"
docker compose ps

# Quick API health check
curl http://localhost/api/health

# Telnet smoke test
telnet localhost 7300
```

## How stats ingestion works

`stats-svc` contains two cooperating components running in a single container:

1. **Ingestor** — maintains a persistent telnet connection to DXSpider as the
   `DX_MONITOR_USER` account. It sets a wide filter to receive all DX spots,
   announcements, and WWV/WCY bulletins. Each line is parsed and normalized:
   - Frequency → band + mode (from a bundled lookup table)
   - Callsign prefix → DXCC entity + continent
   - Spotter signature → `source=human` or `source=rbn` (RBN skimmers are
     detected from comment markers and spotter patterns)
   - Normalized records are written to the `spots` table in Postgres.
   - Every `DX_USERS_POLL_SECONDS` seconds (default: 20), `show/users` is
     sent and the `connected_users` snapshot table is replaced.

2. **Web server** — FastAPI serves the stats dashboard as a single HTML page
   with ECharts charts. All chart data comes from REST endpoints that query
   Postgres aggregates. A WebSocket endpoint pushes new spots and user
   snapshots to connected browsers in real time.

**Backfill:** On first start (if `DX_BACKFILL_ON_START=true`), the ingestor
reads DXSpider's existing spot files from the shared `dxspider-data` volume
before connecting to the telnet stream, so charts are populated with historical
data immediately rather than starting from zero.

## Known integration notes — verify on first real run

### (a) DX_MONITOR_USER must be callsign-shaped

DXSpider validates telnet logins against its internal user database by
callsign. The default value `statsmon` is not a valid callsign and may be
rejected by some DXSpider versions with a "not a valid callsign" error.

**Resolution:** Set `DX_MONITOR_USER` in `.env` to a callsign-shaped value
(for example `N0CALL-9`, using an SSID you do not use on air) and register
that user in DXSpider before or immediately after first boot:

```bash
# Inside the dxspider container (after it is running)
docker compose exec dxspider perl /spider/perl/create_user.pl N0CALL-9
```

Or use the sysop web console at `/cluster` to create the user interactively.

### (b) DXVars.pm required fields

The required fields in `DXVars.pm` are verified against the cloned EA3CV mojo
source on first build. If the build fails with a Perl error referencing a
missing or mismatched variable, check `/spider/local/DXVars.pm` against the
template in `dxspider/templates/DXVars.pm.tmpl` and the DXSpider source.

### (c) ttyd version and architecture

The `dxspider` image installs ttyd 1.7.7 as a static binary from GitHub
releases (x86_64 only). On arm64 hosts (e.g., Raspberry Pi 4, Apple Silicon
under Docker Desktop) the binary will fail to execute. Override at build time:

```bash
docker compose build \
  --build-arg TTYD_URL=https://github.com/tsl0922/ttyd/releases/download/1.7.7/ttyd.aarch64 \
  dxspider
```

Or build ttyd from source: https://github.com/tsl0922/ttyd

## Phase 2 — Partner peering and RBN aggregator (not active in v1)

The following features are designed and documented but intentionally disabled
in the initial deployment. Enable them when you are ready for a public node.

### Inter-cluster peering

Add partner node `connect` configuration to `/spider/local/DXVars.pm` (or a
separate connect script) via the sysop console or by editing the volume.
DXSpider supports the PC protocol for node-to-node peering. Peering config is
entirely in the DXSpider volume — no compose changes needed.

### RBN aggregator feed

Connect to the Reverse Beacon Network aggregator as an additional DXSpider
cluster link (a DXSpider-to-DXSpider or AR-Cluster-compatible connection).
The stats ingestor already tags spots `source=rbn` vs `source=human` based on
comment patterns, so RBN spots are correctly classified from day one — only
the upstream DXSpider connection needs to be configured.

## Backup

### Database backup

```bash
# Run pg_dump against the running postgres container
docker compose exec postgres \
    pg_dump -U dxstats dxstats | gzip > backup-$(date +%Y%m%d).sql.gz
```

Schedule this via cron on the host for automated backups. Recommended: daily
at a low-traffic time, with at least 7 days of retention.

### Volume backup

```bash
# Backup dxspider config and data volumes
docker run --rm \
    -v dxcluster_dxspider-config:/vol/config:ro \
    -v dxcluster_dxspider-data:/vol/data:ro \
    -v $(pwd)/backups:/backup \
    debian:bookworm-slim \
    tar czf /backup/dxspider-volumes-$(date +%Y%m%d).tar.gz -C /vol .
```

Note: the compose project name (`dxcluster`, set via `name:` in
`docker-compose.yml`) is prepended to volume names by Docker.

## Security notes

- **Change all default passwords** in `.env` before exposing the node to the
  internet: `TTYD_PASSWORD`, `DX_MONITOR_PASSWORD`, `POSTGRES_PASSWORD` (and
  `DX_DB_DSN` to match), and any DXSpider sysop password set via the console.
- **Telnet (port 7300)** is published directly to the host with no
  authentication beyond DXSpider's own callsign validation. Consider firewall
  rules or a VPN if you want to restrict access before your node is ready for
  public use.
- **The sysop console** at `/cluster` is protected by ttyd HTTP basic auth
  (`TTYD_USER` / `TTYD_PASSWORD`). Use a strong password and consider adding
  an IP allowlist in Caddy for `/cluster` if your node is public.
- **The stats dashboard** (`/`) is unauthenticated read-only public data.
  This is intentional in v1. Dashboard auth is out of scope (see spec §11).
- **HTTPS:** Set `DOMAIN` to your FQDN to enable automatic Let's Encrypt TLS.
  Caddy renews certificates automatically. Ensure ports 80 and 443 are
  reachable from the internet for the ACME HTTP-01 challenge.

## Verification status

The Python test suite (parsers, aggregation, API) passes locally. The Docker
images and Compose stack are authored and peer-reviewed but have **not been
brought up in the authoring environment** (no Docker available). Container
bring-up and integration smoke-testing are the first step for the operator on
a Docker-capable host. See "Known integration notes" above for the main items
to verify on first run.
