---
name: Bug report
about: Report a problem with the stack
title: "[bug] "
labels: bug
assignees: ''
---

## Description

A clear description of what the bug is and what you expected to happen.

## Affected component

- [ ] dxspider (cluster engine / ttyd console)
- [ ] stats-svc (ingestor / API / dashboard)
- [ ] postgres
- [ ] caddy (reverse proxy / TLS)
- [ ] docker-compose / build
- [ ] documentation

## Steps to reproduce

1.
2.
3.

## Logs

`docker compose logs <service>` for the affected service(s) (please redact
secrets):

```
<paste logs here>
```

## Environment

- OS / architecture (e.g. Ubuntu 24.04 x86_64, Raspberry Pi arm64):
- Docker version (`docker --version`) and Compose version:
- DXSpider build args used (default, or `SPIDER_REPO`/`SPIDER_SHA` override):
- Relevant `.env` settings **with secrets redacted** (e.g. `DOMAIN`,
  `DX_MONITOR_USER`, `DX_BACKFILL_ON_START`):

## Additional context

Anything else that might help (recent changes, first boot vs. upgrade, etc.).
