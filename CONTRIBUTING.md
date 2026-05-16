# Contributing to DXSpider Docker

Thank you for your interest in contributing. This document covers how to set up a development environment, run the test suite, and submit changes.

## Code of Conduct

This project follows the [Contributor Covenant Code of Conduct](CODE_OF_CONDUCT.md). By participating you agree to uphold it.

## Development environment

### Requirements

- Python 3.12 (the version pinned in the containers; later versions are likely fine for local dev)
- Git

### Setup

```bash
git clone https://github.com/n9bc/dxspider-docker.git
cd dxspider-docker/stats-svc

python -m venv .venv
# Linux / macOS
source .venv/bin/activate
# Windows PowerShell
.\.venv\Scripts\Activate.ps1

pip install -r requirements-dev.txt
```

`requirements-dev.txt` pulls in the production dependencies (`fastapi`, `uvicorn`, `asyncpg`) plus the test toolchain (`pytest`, `pytest-asyncio`, `httpx`, `websockets`). Docker is not required for Python development.

### Running the tests

Always run pytest from the `stats-svc/` directory so `pytest.ini` is picked up:

```bash
cd stats-svc
python -m pytest -q
```

Expected result: **171 passed, 0 skipped, 0 failures**. Running from the repo root causes `pytest.ini` (`asyncio_mode=auto`, `pythonpath=.`) to be skipped, which breaks async tests — that is an invocation artifact, not a code issue.

### Project layout

```
stats-svc/
  app/
    aggregate.py   # query/aggregation layer
    api.py         # FastAPI app factory, REST routes, WebSocket
    backfill.py    # first-boot spot-file loader
    bands.py       # frequency → band + mode lookup
    config.py      # env-var parsing
    dxcc.py        # callsign prefix → DXCC / continent
    ingestor.py    # async telnet monitor loop
    main.py        # uvicorn entry point
    parsers.py     # DXSpider line parsers (highest-risk module)
    repo.py        # Repo protocol, MemoryRepo, PgRepo
    static/        # dashboard HTML, JS, ECharts assets
  tests/           # pytest test suite
  requirements.txt
  requirements-dev.txt
  pytest.ini
dxspider/          # DXSpider container (Dockerfile, entrypoint, templates)
caddy/             # Caddyfile
docker-compose.yml
.env.example
docs/              # Technical documentation
```

See [docs/development.md](docs/development.md) for deeper coverage of the architecture and contributing workflow.

## Test-driven development

All logic in `stats-svc/app/` was built test-first. When adding new features or fixing bugs:

1. Write a failing test that captures the expected behaviour.
2. Implement just enough to make it pass.
3. Refactor, keeping the suite green.

Do not submit a pull request that reduces the passing test count or introduces skipped tests without a clear documented reason.

## Commit conventions

- Use the imperative mood in the subject line: "Add rare-DX endpoint" not "Added" or "Adding".
- Keep the subject line to 72 characters or fewer.
- Reference an issue or PR number where relevant: `Fixes #42`.
- One logical change per commit; squash fixup commits before opening a PR.

## Pull request process

1. Fork the repository and create a branch from `main` (e.g. `fix/parser-null-comment` or `feat/callsign-ssid-filter`).
2. Make your changes with tests.
3. Ensure `python -m pytest -q` passes from `stats-svc/` with 0 failures and 0 skipped.
4. Update or add documentation in `docs/` if your change affects user-visible behaviour or configuration.
5. Open a pull request against `main`. Fill in the PR template.
6. A maintainer will review. Please respond to feedback within a reasonable timeframe.

## Proposing larger changes

For significant new features or architectural changes, open an issue first to discuss the approach before spending time on implementation. Describe the problem you are solving, the proposed solution, and any alternatives you considered.

The design spec lives at [docs/superpowers/specs/2026-05-16-dockerized-dx-cluster-design.md](docs/superpowers/specs/2026-05-16-dockerized-dx-cluster-design.md).

## Code style

- Python: follow PEP 8. Line length 99. Type-annotate public functions and methods.
- Use `from __future__ import annotations` in modules that use modern type syntax.
- Prefer `async`/`await` throughout `stats-svc`; avoid blocking calls in async contexts.
- Perl (DXSpider config templates): follow the existing style in the `dxspider/` directory.

No external linter/formatter is currently enforced in CI; reviewers may request style fixes.
