# Verification Report — Dockerized DX Cluster

Date: 2026-05-16
Branch: `feature/dockerized-dx-cluster` (23 commits, HEAD `f1eb525`)

## Summary

The full stack was built spec-first via the brainstorming → writing-plans →
subagent-driven-development workflow. Every implementation task went through an
independent spec-compliance + code-quality review by a separate agent, with
fix/re-review loops. The one genuine open design decision (how to source and
pin DXSpider, and whether the `mojo` branch has a native web console) was
resolved by a **3-round multi-agent consensus debate** (the second and third
rounds were triggered because the first two were not unanimous).

## What was verified automatically (in this environment)

Docker is **not available** on the build host, so all Docker-independent logic
was implemented test-first and the suite was executed locally with Python 3.14
in `stats-svc/.venv`.

- Command: `python -m pytest -q` run from `C:\dev\dxspider\stats-svc`
- Result: **171 passed, 0 skipped, 0 failures**

> Note: pytest **must** be run from `stats-svc/` so `pytest.ini`
> (`asyncio_mode=auto`, `pythonpath=.`) applies. Running from elsewhere causes
> async tests to skip — that is an invocation artifact, not a code issue.

Coverage by module:

| Area | Tests | Notes |
|---|---|---|
| `bands` | band/mode classification incl. boundaries, USB/LSB→SSB, PSK31 | pure |
| `dxcc` | longest-prefix, portable prefix/suffix, /MM /AM, unknown | pure |
| `parsers` (highest risk) | human/RBN spot, WWV, WCY, announce, users block, None-safety, comment-less | pure |
| `config` | env parsing + defaults | pure |
| `repo` | MemoryRepo insert/dedup/rollup/replace-all; NULL-key coalescing | fakes |
| `aggregate` | activity/band/mode/geo/top/rare-dx/callsign-detail, source & window filters | fakes |
| `api` | all REST routes, 422 validation, static, **WebSocket live broadcast** | ASGI client |
| `ingestor` | process_lines, dedup-on-live-path, users poll, backoff bounds | fake streams |
| `backfill` | idempotency, malformed-line tolerance | temp files |
| `main` | imports without uvicorn/asyncpg present | import guard |

Key correctness items confirmed by review + probes: WS payloads are
JSON-serializable; `parse_line` never raises; the MemoryRepo↔PgRepo
duplicate-spot divergence on the live ingest path is **closed** (ingestor uses
the dedup path; both repos share the `(ts,spotter,dx_call,freq_khz)` key and
rollup-only-on-insert); asyncpg SQL parameter order / `ON CONFLICT` targets /
`COALESCE` reviewed against the schema; dashboard tables HTML-escape
telnet-sourced data.

## Decisions locked by the multi-agent debate

- **DXSpider source:** Dockerfile `ARG SPIDER_REPO`/`SPIDER_BRANCH`/`SPIDER_SHA`,
  default `https://github.com/EA3CV/dx-spider.git` branch `mojo` pinned to SHA
  `63d47180dc195e026bae23446eb9b798a0e923d6` (only HTTPS source carrying
  current code; `git://scm.dxcluster.org` has no HTTPS and port 9418 is
  CI-hostile; `latchdevel/DXspider` is a faithful full-history mirror but
  frozen 2022-02). Documented overrides: self-hosted mirror (recommended for
  production) and the latchdevel pin, both via `docker compose build
  --build-arg`.
- **Base image:** `debian:bookworm-slim`, Debian `lib*-perl` packages first
  (musl/Alpine rejected for Mojolicious/XS reliability).
- **Web console:** the `mojo` branch has **no native web UI** (Mojolicious is
  only its event loop; `dxweb` is an unfinished scaffold). The browser sysop
  console is `ttyd` (pinned 1.7.7) wrapping `console.pl`; Caddy `/cluster*`
  proxies to it.

## NOT verified here — must be done on a Docker host (first bring-up)

These require Docker and are the user's first-run steps:

1. `docker compose build` (DXSpider clone + CPAN/apt install) and
   `docker compose up -d` succeed; containers reach healthy.
2. **DXVars.pm fields:** the templated `local/DXVars.pm` is accepted by the
   pinned EA3CV `mojo` source — confirm no additional required vars vs the
   repo's `DXVars.pm.issue`.
3. **Monitor login:** the stats ingestor logs into DXSpider as
   `DX_MONITOR_USER` (default `statsmon`). DXSpider may reject a non-callsign
   login; if so set `DX_MONITOR_USER` to a callsign-shaped value or register
   the user via the sysop console (documented in README "Known integration
   notes").
4. **Native-format backfill is a v1 no-op:** backfill parses CSV/TSV `*.spots`;
   DXSpider writes Perl `Data::Dumper` files. First boot inserts 0 historical
   spots (charts fill from the live ingestor). Phase 2 item — documented.
5. **`ttyd` arch:** the pinned binary is x86_64; arm64 hosts override the URL.
6. **`show/users` interleaving:** the v1 poll shares the telnet stream with
   spots over a 1 s window (documented Phase-2 simplification).
7. End-to-end smoke (spec §9): inject a telnet spot → assert it appears in
   `/api/*` and over `/ws`.

## Phase 2 (config-gated, documented, intentionally inactive in v1)

Partner peering and the outbound RBN aggregator connection (DXVars template
has commented, env-gated blocks). The stats side already tags `source = rbn |
human` from day one, so enabling RBN upstream needs no stats changes.

## Conclusion

The system is **code-complete and fully green on all Docker-independent
verification** (171/171). Container build and compose integration are authored,
cross-checked for consistency, and peer-reviewed but — per the environment
constraint and the user's instruction that hand testing occurs after
completion — must be brought up on a Docker-capable host using the steps in
`README.md`. No claim is made that the containers have been run here.
