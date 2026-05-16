# Dockerized Feature-Rich DX Cluster — Design Spec

Date: 2026-05-16
Status: Approved (user authorized autonomous build)

## 1. Goal

A fully working, feature-rich amateur-radio DX cluster running as a Docker
Compose stack. DXSpider provides the cluster engine (telnet + peering + its
own web console). A custom Python service ingests the live spot stream and
serves a rich statistics dashboard (graphs, pie charts, leaderboards, live
connected-users panel).

Deployment intent: a public node, built **standalone first** with partner
peering and the RBN aggregator feed as a documented, config-gated Phase 2.

## 2. Architecture

Four-service Docker Compose stack on a single host:

- **dxspider** — DXSpider cluster engine. Telnet `7300` (published to host),
  built-in Mojolicious web console, PC-protocol peering (Phase 2). Configured
  standalone. Non-root. Persistent volume for `/spider/local_data`.
- **stats-svc** — Python. Two cooperating roles in one container:
  - *ingestor*: persistent telnet "monitor" session to dxspider, parses
    spots/announce/WWV and polls `show/users`; writes Postgres.
  - *web*: FastAPI REST + WebSocket + static dashboard (server-rendered page +
    JS chart library, no SPA build toolchain).
- **postgres** — durable store for raw spots, connected-users snapshots, and
  rollup aggregates.
- **caddy** — single web entrypoint; automatic HTTPS when `DOMAIN` is set,
  plain HTTP for local. Routes `/` → dashboard, `/cluster` → DXSpider console.

Telnet (7300) is published directly to the host (not proxied). All HTTP(S)
goes through Caddy.

```
Internet/LAN → caddy → stats-svc (/) and dxspider web console (/cluster)
ham operators → host:7300 → dxspider (telnet)
partner nodes → dxspider PC protocol (Phase 2)
stats-svc ingestor → dxspider telnet (monitor user) → postgres
stats-svc backfill → dxspider spot files (read-only, first boot)
```

## 3. DXSpider service

- Image built from pinned DXSpider source on a Debian-slim base, Perl runtime,
  required CPAN modules, runs as a non-root `sysop` user.
- Configuration templated from environment at container start:
  `NODE_CALL`, `SYSOP_CALL`, `SYSOP_NAME`, `LOCATOR`, `SYSOP_PASSWORD`,
  `MONITOR_USER`, `MONITOR_PASSWORD`. Standalone: no partner connect statements.
- A dedicated low-privilege monitor user is provisioned at first boot for the
  stats ingestor to log in with (registered, no sysop rights).
- Persistent named volume `dxspider-data` → `/spider/local_data` (spot files, user
  db, messages) so history/state survive restarts and image upgrades.
- Phase 2 (documented, not active in v1): partner `connect` config block and
  outbound RBN aggregator connection, both env-gated.

## 4. Stats service

### 4.1 Ingestor
- Maintains a persistent telnet session as the monitor user; sets wide filters
  to receive all DX + RBN spots, announcements, and WWV/WCY.
- Line parsers produce normalized records. Every spot tagged
  `source = human | rbn` (RBN detected from spotter-of-spotter `-#`/skimmer
  comment markers and the RBN comment grammar).
- Periodic `show/users` poll (`USERS_POLL_SECONDS`, default 20s) → replace the
  connected-users snapshot table.
- Reconnect with exponential backoff + jitter; on first boot, optional
  one-time backfill reading existing DXSpider spot files into Postgres so
  charts are not empty (`BACKFILL_ON_START`, default true).

### 4.2 Web API + dashboard
- FastAPI. REST endpoints return aggregated data per chart, all accepting
  `source` (`human|rbn|both`) and time-range filters. WebSocket pushes new
  spots and connected-users snapshots.
- Dashboard: one responsive HTML page served by FastAPI with static assets and
  a charting library (Apache ECharts). No Node/SPA build step.

## 5. Data model

- `spots(id, ts, spotter, dx_call, freq_khz, band, mode, source,
  spotter_dxcc, dx_dxcc, dx_continent, comment, raw)`
- `connected_users(callsign, conn_type, since_ts, snapshot_ts)` —
  replace-all per poll.
- `spot_rollup_hourly(hour_ts, band, mode, source, dx_dxcc, dx_continent,
  spotter_dxcc, count)` — maintained incrementally for fast charts.
- Band/mode/DXCC/continent derived at ingest from frequency + callsign prefix
  using a bundled prefix→DXCC/continent table (data file in the repo).

## 6. Dashboard views

All filterable by `human | rbn | both` and time range:

- **Activity over time** — spots per hour/day, last-24h trend (line).
- **Band & mode** — distribution (pie/bar).
- **Geographic** — top DX entities, top spotting entities, by continent.
- **Top lists** — most-active spotters, most-spotted DX, rare-DX highlights,
  per-callsign drill-down.
- **Live panel** — currently connected users + callsigns, live spot ticker
  (WebSocket).

## 7. Web exposure & TLS

- Caddy routes `/` → stats dashboard, `/cluster*` → DXSpider web console.
- `DOMAIN` set → automatic Let's Encrypt HTTPS; unset → HTTP on localhost.
- Security headers and sane proxy timeouts.

## 8. Persistence & operations

- Named volumes: `dxspider-data`, `postgres-data`, `caddy-data`.
- All identity/secrets via `.env`; `.env.example` documents every variable.
- `docker compose up -d` is the entire deployment. README documents standalone
  bring-up and the Phase 2 peering/RBN enablement procedure.
- DB backup guidance (scheduled `pg_dump`) documented; not automated in v1.

## 9. Testing strategy

- **Parser unit tests (TDD, highest risk):** fixture lines — human spot, RBN
  spot, WWV/WCY, announce, and `show/users` output across DXSpider format
  variants — assert exact normalized records. Pure-Python, runnable without
  Docker.
- **Aggregation/API tests:** endpoints against a seeded test DB return correct
  aggregates and honor `source`/time filters. SQLite-compatible query layer or
  Postgres test fixture.
- **Integration smoke test:** compose stack boots; a known spot injected via
  telnet appears in the API and over the WebSocket. (Requires Docker host.)
- Charting/UI verified manually after build.

## 10. Build phases

1. Compose skeleton + DXSpider container standalone (telnet reachable).
2. Stats DB schema + ingestor with TDD'd parsers + backfill.
3. FastAPI endpoints + WebSocket.
4. Dashboard charts + live panel.
5. Caddy + TLS + docs.
6. Phase 2 (documented, ready to enable): partner peering + RBN aggregator.

## 11. Scope guardrails (YAGNI)

- No dashboard auth in v1 (read-only public stats).
- No SPA framework / JS build toolchain.
- No automated backups in v1.
- Peering and RBN *aggregator* connection are config-gated Phase 2; the stats
  side handles RBN-tagged spots from day one.

## 12. Decision protocol for the autonomous build

When a genuine design/implementation decision arises (ambiguous, consequential,
not already settled here), dispatch 3 independent agents to propose and then
critique each other's answers. Proceed only on unanimous consensus; otherwise
dispatch a fresh set of 3. Non-consequential choices use existing conventions
and good judgment without a debate.

## 13. Environment note

The build host for this autonomous session has no Docker available. All
Docker-independent verification (parsers, aggregation/API logic) is executed
locally with Python. Container build and compose integration are produced and
peer-reviewed but must be brought up on a Docker-capable host (the user's
machine) — this is the only step deferred to post-build hand verification, per
the user's instruction that hand testing occurs after completion.
