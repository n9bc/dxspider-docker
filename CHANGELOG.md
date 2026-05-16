# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Planned (Phase 2 — documented, config-gated, not active in v1)

- Partner / inter-cluster peering (DXSpider PC-protocol `connect` blocks).
- Outbound RBN aggregator feed (the stats layer already tags
  `source = human | rbn`, so no stats changes are required to enable it).
- Native-format spot-file backfill (parsing DXSpider's Perl `Data::Dumper`
  spot files; v1 backfill only reads CSV/TSV `*.spots`).
- Proper `show/users` stream multiplexing (v1 uses a 1-second shared-stream
  collection window).
- Optional dashboard authentication.

See [docs/phase-2.md](docs/phase-2.md) for details.

## [0.1.0] - 2026-05-16

Initial release.

### Added

- **DXSpider cluster engine** container (Debian-slim, non-root `sysop`,
  `tini` PID 1) built from a SHA-pinned source with overridable build args;
  env-templated `DXVars.pm` / `Listeners.pm`; telnet listener on port 7300.
- **ttyd-based sysop web console** wrapping `console.pl` (the DXSpider `mojo`
  branch has no native web UI), reachable via Caddy at `/cluster`.
- **`stats-svc`** (Python / FastAPI):
  - Telnet "monitor" ingestor: parses DX spots (human + RBN), WWV/WCY, and
    announcements; periodic `show/users` polling; reconnect with exponential
    backoff.
  - Postgres persistence with a `Repo` abstraction (in-memory for tests,
    asyncpg-backed for production), hourly rollups, and idempotent dedup.
  - REST API + WebSocket live feed.
  - Single-page ECharts dashboard: activity-over-time, band & mode
    breakdowns, geographic breakdown, top spotters, top DX, rare DX,
    per-callsign drill-down, live spot ticker, connected-users panel, and a
    human / RBN / both source filter.
  - Optional first-boot backfill from existing spot files.
- **Postgres 16** durable store.
- **Caddy 2.8** reverse proxy with automatic HTTPS (Let's Encrypt) when
  `DOMAIN` is set, plain HTTP otherwise; security headers; WebSocket-aware
  routing.
- **Docker Compose** orchestration, `.env.example` documenting every variable,
  named volumes for durable state.
- Test suite: **171 passing, 0 skipped** (parsers, band/DXCC resolution,
  aggregation, REST + WebSocket API, ingestor, backfill, config).
- Dashboard XSS hardening for telnet-sourced data.
- Full documentation set under `docs/` plus contributing/security/CI scaffolding.

[Unreleased]: https://github.com/n9bc/dxspider-docker/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/n9bc/dxspider-docker/releases/tag/v0.1.0
