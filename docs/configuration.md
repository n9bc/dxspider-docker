# Configuration Reference

All runtime configuration is supplied via environment variables. Copy `.env.example` to `.env`, edit it, and `docker compose up -d` picks it up automatically.

```
cp .env.example .env
# Edit .env — at minimum: NODE_CALL, SYSOP_CALL, LOCATOR, passwords
docker compose up -d
```

`.env` is listed in `.gitignore`. Never commit real secrets or callsign data.

---

## dxspider service

These variables are declared in `docker-compose.yml` under the `dxspider` service and consumed by `dxspider/entrypoint.sh`. They are used to render `/spider/local/DXVars.pm` and `/spider/local/Listeners.pm` from templates at container start.

| Variable | Default | Meaning | Must change for public deployment |
|---|---|---|---|
| `NODE_CALL` | `N0CALL-2` | Node callsign including SSID, e.g. `W1AW-2`. Becomes `$mycall` in `DXVars.pm`. | Yes |
| `SYSOP_CALL` | `N0CALL` | Sysop personal callsign (no SSID). Becomes `$myalias` in `DXVars.pm`. | Yes |
| `SYSOP_NAME` | `Sysop` | Sysop display name shown in welcome banners. Becomes `$myname`. | Yes |
| `LOCATOR` | `AA00aa` | 6-character Maidenhead grid locator, e.g. `FN31pr`. Becomes `$mylocator`. | Yes |
| `NODE_QTH` | `Unknown QTH` | Free-text QTH description shown to connected users. Becomes `$myqth`. | Yes |
| `SYSOP_EMAIL` | `sysop@example.com` | Contact email shown in node info. Becomes `$myemail`. | Yes |
| `NODE_TELNET_PORT` | `7300` | Telnet port DXSpider listens on inside the container. Also the port that is published to the host. Becomes the port in `Listeners.pm`. | No (unless you have a port conflict) |
| `SYSOP_WEB_PORT` | `8080` | Port ttyd listens on inside the container. Internal only — Caddy proxies this. | No |
| `TTYD_USER` | `sysop` | HTTP basic auth username for the ttyd web console at `/cluster`. | Yes |
| `TTYD_PASSWORD` | `changeme` | HTTP basic auth password for the ttyd web console. | Yes |
| `OVERWRITE_CONFIG` | `no` | Set to `yes` to re-render `DXVars.pm` and `Listeners.pm` from env vars on every container start, overwriting any manual edits in the volume. Leave as `no` (default) to preserve operator-edited configs across restarts. | No |

**Config rendering detail:** On container start, `entrypoint.sh` checks for the existence of `/spider/local/DXVars.pm`. If absent, or if `OVERWRITE_CONFIG=yes`, it renders the file from `/spider/templates/DXVars.pm.tmpl` using `sed` token substitution. The same logic applies to `Listeners.pm`. Because `/spider/local` is a named volume, rendered files persist across container restarts and image upgrades until explicitly overwritten.

---

## postgres service

These variables are passed directly to the official `postgres:16` image. They are hardcoded in `docker-compose.yml` with the exception of `POSTGRES_PASSWORD`, which is pulled from `.env`.

| Variable | Default | Meaning | Notes |
|---|---|---|---|
| `POSTGRES_USER` | `dxstats` | Database user created at first boot. Hardcoded in compose — not overridable via `.env` without editing `docker-compose.yml`. | — |
| `POSTGRES_PASSWORD` | `dxstats` | Password for `POSTGRES_USER`. **Must match the password embedded in `DX_DB_DSN`** (see coupling note below). | Yes — change before public deployment |
| `POSTGRES_DB` | `dxstats` | Database name created at first boot. Hardcoded in compose. | — |

**`POSTGRES_PASSWORD` ↔ `DX_DB_DSN` coupling:** The password in the DSN used by stats-svc must always match the password Postgres was initialized with. If you change `POSTGRES_PASSWORD`, update `DX_DB_DSN` in `.env` to match. Example: if `POSTGRES_PASSWORD=mysecret`, set `DX_DB_DSN=postgresql://dxstats:mysecret@postgres:5432/dxstats`. The default for both is `dxstats` — a well-known default that must be changed before exposing the stack to the internet.

---

## stats-svc service

These variables are declared in `docker-compose.yml` under the `stats-svc` service. They are consumed by `stats-svc/app/config.py` via `Settings.from_env()`. All are optional — the defaults shown are the values used when the variable is absent from the environment.

| Variable | Default | Meaning | Must change for public deployment |
|---|---|---|---|
| `DX_DB_DSN` | `postgresql://dxstats:dxstats@postgres:5432/dxstats` | asyncpg connection string for Postgres. **Must stay consistent with `POSTGRES_PASSWORD`** (see coupling note above). | Yes (update password to match `POSTGRES_PASSWORD`) |
| `DX_HOST` | `dxspider` | Hostname of the DXSpider service as seen from inside the container network. Docker DNS resolves service names; leave as `dxspider` unless the service is renamed in compose. | No |
| `DX_PORT` | `7300` | Telnet port of the DXSpider service. Must match `NODE_TELNET_PORT`. | No |
| `DX_MONITOR_USER` | `statsmon` | Callsign-like login the ingestor uses to connect to DXSpider via telnet. **See the monitor-user caveat below.** | Yes — see caveat |
| `DX_MONITOR_PASSWORD` | `changeme` | Password for the monitor user account in DXSpider. | Yes |
| `DX_USERS_POLL_SECONDS` | `20` | How often (in seconds) the ingestor sends `show/users` to update the connected-users snapshot. | No |
| `DX_BACKFILL_ON_START` | `true` | When `true`, stats-svc reads existing `*.spots` files from `DX_SPOT_FILES_DIR` at startup and inserts any previously unseen spots into Postgres. Idempotent — safe to leave enabled. Set to `false` to skip the scan. | No |
| `DX_SPOT_FILES_DIR` | `/spider-spots/spots` | Path inside the stats-svc container where DXSpider spot files are readable. The `dxspider-data` named volume is mounted read-only at `/spider-spots`; DXSpider writes spot files under `local_data/spots`, so the effective path is `/spider-spots/spots`. Change only if you alter the volume mount path in `docker-compose.yml`. | No |

**Monitor-user caveat (`DX_MONITOR_USER`):** DXSpider validates logins against its internal user database by callsign. The default value `statsmon` is not shaped like a callsign and may be rejected by some DXSpider configurations. If you see repeated connection failures in `docker compose logs stats-svc`:
1. Change `DX_MONITOR_USER` to a callsign-shaped value (e.g., `N0CALL-9`).
2. Register that callsign in DXSpider via the sysop console before bringing up the stack, or run `perl /spider/perl/create_user.pl <callsign>` inside the `dxspider` container.

See `VERIFICATION.md` §3 for the full first-run checklist.

---

## caddy service

| Variable | Default | Meaning | Notes |
|---|---|---|---|
| `DOMAIN` | `localhost` | Controls TLS and the Caddy site address. `localhost` → plain HTTP on port 80. Any FQDN → automatic Let's Encrypt TLS on ports 80 + 443. Before setting a real domain, ensure DNS A/AAAA records point to the host and ports 80 and 443 are open in the firewall. | Yes for a public node |

The `DOMAIN` variable is interpolated in `caddy/Caddyfile` as `{$DOMAIN:localhost}`. Caddy reads the value from the environment at startup.

---

## Build-time overrides: DXSpider source

`SPIDER_REPO`, `SPIDER_BRANCH`, and `SPIDER_SHA` are **not** environment variables consumed at runtime. They are Docker build arguments (`ARG` in `dxspider/Dockerfile`) that control which DXSpider source is cloned and pinned at image build time.

They are **not** passed as `build.args` in `docker-compose.yml`. To override them, pass `--build-arg` on the CLI:

```bash
docker compose build \
  --build-arg SPIDER_REPO=https://github.com/your-org/dxspider.git \
  --build-arg SPIDER_BRANCH=mojo \
  --build-arg SPIDER_SHA=<your-verified-sha> \
  dxspider
```

**Defaults (single source of truth: `dxspider/Dockerfile`):**

| Build arg | Default value |
|---|---|
| `SPIDER_REPO` | `https://github.com/EA3CV/dx-spider.git` |
| `SPIDER_BRANCH` | `mojo` |
| `SPIDER_SHA` | `63d47180dc195e026bae23446eb9b798a0e923d6` |

**latchdevel alternative (full-history mirror, frozen 2022-02-07):**
```bash
docker compose build \
  --build-arg SPIDER_REPO=https://github.com/latchdevel/DXspider.git \
  --build-arg SPIDER_BRANCH=master \
  --build-arg SPIDER_SHA=e61ab5eeea22241ea8d8f1f6d072f5249901d788 \
  dxspider
```

**Production recommendation:** Mirror EA3CV `mojo` to a private git server, verify the SHA matches the audited commit, and pass your mirror URL at build time.

**`TTYD_URL` build arg:** The pinned ttyd binary is x86_64-only. arm64 hosts must override this at build time:
```bash
docker compose build \
  --build-arg TTYD_URL=https://github.com/tsl0922/ttyd/releases/download/1.7.7/ttyd.aarch64 \
  dxspider
```

---

## Variables that must change before public deployment

| Variable | Why |
|---|---|
| `NODE_CALL` | Default `N0CALL-2` is not a real callsign |
| `SYSOP_CALL` | Default `N0CALL` is not a real callsign |
| `SYSOP_NAME` | Default `Sysop` is a placeholder |
| `LOCATOR` | Default `AA00aa` is not a real grid locator |
| `NODE_QTH` | Default `Unknown QTH` is a placeholder |
| `SYSOP_EMAIL` | Default `sysop@example.com` is a placeholder |
| `TTYD_PASSWORD` | Default `changeme` is a well-known insecure value |
| `POSTGRES_PASSWORD` | Default `dxstats` is a well-known insecure value |
| `DX_DB_DSN` | Must be updated whenever `POSTGRES_PASSWORD` changes |
| `DX_MONITOR_USER` | May need to be callsign-shaped; see monitor-user caveat |
| `DX_MONITOR_PASSWORD` | Default `changeme` is insecure |
| `DOMAIN` | Set to your FQDN to enable automatic TLS |
