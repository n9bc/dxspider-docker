# Troubleshooting

Symptom → likely cause → fix. See also [operations.md](operations.md) and the
first-run notes in [deployment.md](deployment.md).

## Tests appear to "skip"

**Symptom:** `pytest` reports skipped async tests, or a much lower count than
171.
**Cause:** pytest was run from the wrong directory, so `stats-svc/pytest.ini`
(`asyncio_mode = auto`, `pythonpath = .`) is not applied and async tests are
collected but not run.
**Fix:** Always run from the `stats-svc/` directory:

```bash
cd stats-svc
python -m pytest -q          # expect: 171 passed, 0 skipped
```

## `docker compose up` fails at the DXSpider image build (git clone)

**Symptom:** Build fails cloning the DXSpider source.
**Cause:** The default source mirror is unreachable from your network, or you
need a different/self-hosted source.
**Fix:** Override the build args (they are intentionally *not* compose env
vars — single source of truth is the Dockerfile):

```bash
docker compose build \
  --build-arg SPIDER_REPO=https://github.com/your-org/dxspider.git \
  --build-arg SPIDER_BRANCH=mojo \
  --build-arg SPIDER_SHA=<pinned-sha> \
  dxspider
docker compose up -d
```

See [configuration.md](configuration.md) for the default and the
latchdevel full-history alternative.

## DXSpider container exits shortly after start

**Symptom:** `dxspider` restarts in a loop; logs show a Perl error referencing
`DXVars.pm`.
**Cause:** The pinned DXSpider source may require additional `DXVars.pm` fields
not present in the bundled template, or the templated values are invalid.
**Fix:** Inspect logs (`docker compose logs dxspider`), compare the generated
`/spider/local/DXVars.pm` (in the `dxspider-config` volume) against the
upstream `DXVars.pm.issue` from the cloned source, and add any missing required
fields to `dxspider/templates/DXVars.pm.tmpl`. This is the documented first-run
verification item from `VERIFICATION.md`.

## Stats dashboard shows no spots / ingestor not collecting

**Symptom:** Charts stay empty though DXSpider is up and receiving spots; the
connected-users panel is empty.
**Cause:** The ingestor cannot log in to DXSpider. DXSpider validates telnet
logins by callsign; the default `DX_MONITOR_USER=statsmon` may be rejected as
non-callsign-shaped.
**Fix:** Either set `DX_MONITOR_USER` to a callsign-shaped value
(e.g. `N0CALL-9`) and register it, or create the user inside the dxspider
container:

```bash
docker compose exec dxspider perl /spider/perl/create_user.pl statsmon
```

Set `DX_MONITOR_PASSWORD` to match. Then `docker compose restart stats-svc`
and check `docker compose logs stats-svc`.

## Charts empty immediately after first boot (even with backfill enabled)

**Symptom:** `DX_BACKFILL_ON_START=true` but 0 historical spots imported.
**Cause (v1 limitation):** Backfill reads CSV/TSV `*.spots` files. DXSpider's
native spot files use Perl `Data::Dumper`/binary format, which v1 does not
parse. Backfill is a safe no-op on native data.
**Fix:** None required — charts populate from the live ingestor as new spots
arrive. Native-format backfill is a [Phase 2](phase-2.md) item.

## ttyd console fails on ARM (Raspberry Pi, Apple Silicon, arm64 hosts)

**Symptom:** `dxspider` build/run fails fetching or executing the `ttyd`
binary; `/cluster` does not load.
**Cause:** The Dockerfile pins the `ttyd` **x86_64** static binary.
**Fix:** Override the pinned ttyd binary URL for your architecture in
`dxspider/Dockerfile` (use the matching asset from the
[tsl0922/ttyd releases](https://github.com/tsl0922/ttyd/releases)) and rebuild.

## TLS certificate is not issued (site stays on HTTP / shows a cert warning)

**Symptom:** No Let's Encrypt certificate; browser warns or connection is
plain HTTP.
**Cause:** `DOMAIN` is `localhost`/blank, or the FQDN's DNS does not resolve to
this host, or ports 80/443 are not reachable from the internet.
**Fix:** Set `DOMAIN` to a real public FQDN whose A/AAAA records point at the
host, open ports 80 and 443, then `docker compose up -d` and watch
`docker compose logs caddy` for the ACME challenge result.

## Postgres authentication failures in stats-svc logs

**Symptom:** stats-svc cannot connect to the database (password authentication
failed).
**Cause:** `POSTGRES_PASSWORD` and the password embedded in `DX_DB_DSN` do not
match, or the Postgres volume was created with an older password.
**Fix:** Make the two consistent in `.env`. If you changed
`POSTGRES_PASSWORD` after the volume was initialized, the old password persists
in `postgres-data`; either set the DSN to the original password or reset the
database volume (destroys stored spots):

```bash
docker compose down
docker volume rm dxcluster_postgres-data
docker compose up -d
```

## `/cluster` does not load or the terminal does not connect

**Symptom:** Dashboard at `/` works, but `/cluster` is blank or the terminal
never connects.
**Cause:** ttyd not running, wrong `SYSOP_WEB_PORT`, or a proxy/WebSocket
issue.
**Fix:** Confirm `dxspider` is healthy (`docker compose ps`), that
`SYSOP_WEB_PORT` matches between the dxspider env and the Caddyfile upstream
(`dxspider:8080`), and check `docker compose logs caddy` and
`docker compose logs dxspider`. The browser must allow the WebSocket upgrade;
Caddy handles it automatically on a 101 response.

## Connected-users list lags or briefly misses spots

**Symptom:** The connected-users panel updates slowly; occasionally a spot
seems missing right around a user-list refresh.
**Cause (v1 simplification):** `show/users` shares the single telnet stream
with the spot feed using a ~1-second collection window.
**Fix:** Expected in v1; increase `DX_USERS_POLL_SECONDS` to reduce
contention. Proper multiplexing is a [Phase 2](phase-2.md) item.
