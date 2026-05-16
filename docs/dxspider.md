# DXSpider Container

## What Is DXSpider?

DXSpider is an open-source amateur-radio DX cluster server written in Perl,
originally by Dirk Koopman G1TLH. It implements the DX cluster protocol,
allowing amateur radio operators to post and receive DX spot announcements via
telnet. It also supports node-to-node cluster peering via the PC protocol and
can relay propagation bulletins (WWV, WCY) and announcements.

This project uses the **mojo branch** of the
[EA3CV fork](https://github.com/EA3CV/dx-spider), which replaces the classic
event loop with [Mojolicious](https://mojolicious.org/) for modern async I/O.

---

## No Native Web UI in the `mojo` Branch

The `mojo` branch has **no native browser-accessible web console**. Mojolicious
is used solely as the event loop; the `dxweb` scaffold present in the codebase
is unfinished. The browser sysop console provided in this project is
[`ttyd`](https://github.com/tsl0922/ttyd) (version 1.7.7, pinned), a separate
process that wraps `console.pl` in a browser-accessible terminal emulator.

`console.pl` is the standard DXSpider sysop command-line interface. Through
`ttyd` it is reachable via Caddy at `/cluster` (WebSocket-proxied).

---

## Source Provenance and Pinning

The Dockerfile clones DXSpider at build time. Three coordinates are controlled
by build arguments:

| Build arg | Default | Description |
|---|---|---|
| `SPIDER_REPO` | `https://github.com/EA3CV/dx-spider.git` | Git repository URL |
| `SPIDER_BRANCH` | `mojo` | Branch to clone |
| `SPIDER_SHA` | `63d47180dc195e026bae23446eb9b798a0e923d6` | Exact commit SHA pinned |

The clone is full (no `--depth`) and a `git checkout` to the exact SHA follows,
so the build is reproducible regardless of branch tip movement.

### Alternative Source Coordinates

**Self-hosted mirror (recommended for production):**
```bash
docker compose build \
  --build-arg SPIDER_REPO=https://git.example.com/dxspider.git \
  --build-arg SPIDER_BRANCH=mojo \
  --build-arg SPIDER_SHA=<your-verified-sha>
```
Eliminates a build-time dependency on GitHub. Mirror the EA3CV repo (or a
full-history fork) into your own hosting and point `SPIDER_REPO` there.

**`latchdevel/DXspider` full-history mirror (frozen 2022-02-07):**
```bash
docker compose build \
  --build-arg SPIDER_REPO=https://github.com/latchdevel/DXspider.git \
  --build-arg SPIDER_BRANCH=master \
  --build-arg SPIDER_SHA=e61ab5eeea22241ea8d8f1f6d072f5249901d788
```
A faithful mirror of the classic codebase with complete git history, but frozen
as of early 2022 and based on an older DXSpider version (no Mojolicious).

See also `VERIFICATION.md` for the decision rationale from the multi-agent
consensus process that settled these defaults.

---

## `ttyd` Web Console

`ttyd` is a statically linked binary installed at `/usr/local/bin/ttyd`. The
pinned URL is:

```
https://github.com/tsl0922/ttyd/releases/download/1.7.7/ttyd.x86_64
```

This binary is **x86_64 only**. On arm64 hosts (e.g. Raspberry Pi, Apple
Silicon Docker), override the build argument:

```bash
docker compose build \
  --build-arg TTYD_URL=https://github.com/tsl0922/ttyd/releases/download/1.7.7/ttyd.aarch64
```

Alternatively, build `ttyd` from source following the upstream instructions.

`ttyd` is started on port 8080 (the `SYSOP_WEB_PORT` env var) with HTTP basic
authentication. Caddy proxies `/cluster` (and `/cluster/*`) to this port via
WebSocket. **Change the default credentials** (`TTYD_USER` / `TTYD_PASSWORD`)
before exposing to the internet.

---

## Container Configuration — Environment Variables

All DXSpider configuration is rendered from templates at container startup. Set
these environment variables in your `.env` file:

| Variable | Default | Description |
|---|---|---|
| `NODE_CALL` | `N0CALL-2` | Node callsign (used in DXVars.pm) |
| `SYSOP_CALL` | `N0CALL` | Sysop callsign |
| `SYSOP_NAME` | `Sysop` | Sysop name |
| `LOCATOR` | `AA00aa` | Maidenhead locator |
| `NODE_QTH` | `Unknown QTH` | QTH description |
| `SYSOP_EMAIL` | `sysop@example.com` | Sysop e-mail |
| `NODE_TELNET_PORT` | `7300` | Telnet listener port |
| `SYSOP_WEB_PORT` | `8080` | ttyd listening port |
| `TTYD_USER` | `sysop` | ttyd basic-auth username |
| `TTYD_PASSWORD` | `changeme` | ttyd basic-auth password (**change this**) |
| `OVERWRITE_CONFIG` | `no` | Set to `yes` to re-render config from template on restart |

### Template Rendering

Two Perl config files are rendered from templates by `entrypoint.sh` using `sed`
substitution:

- `/spider/templates/DXVars.pm.tmpl` → `/spider/local/DXVars.pm`
  Tokens: `__NODE_CALL__`, `__SYSOP_CALL__`, `__SYSOP_NAME__`, `__LOCATOR__`,
  `__QTH__`, `__EMAIL__`
- `/spider/templates/Listeners.pm.tmpl` → `/spider/local/Listeners.pm`
  Token: `__TELNET_PORT__`

Once rendered, config files are **not overwritten on restart** unless
`OVERWRITE_CONFIG=yes`. This lets operators hand-edit the Perl config files
inside the volume and have changes survive container restarts.

---

## First-Run: Sysop User Creation

On the first container start, when `/spider/local_data/users/` is empty,
`entrypoint.sh` runs:

```bash
perl /spider/perl/create_sysop.pl
```

This registers the sysop user in DXSpider's internal users database. On
subsequent starts the script is skipped (the users directory is non-empty).

---

## Non-Root Operation

The container runs as:
- **User:** `sysop` (uid 1000)
- **Group:** `spider` (gid 251)
- **Home:** `/spider`

The entrypoint script runs as root for initial setup (template rendering,
directory creation, ownership chown), then uses `runuser -u sysop` to start both
`cluster.pl` and `ttyd` as the unprivileged sysop user.

---

## `tini` as PID 1

[`tini`](https://github.com/krallin/tini) (installed from Debian bookworm apt)
is set as the container entrypoint. `tini` correctly forwards signals to child
processes and reaps zombie processes, making it suitable as PID 1 in a
container:

```
ENTRYPOINT ["/usr/bin/tini", "--", "/entrypoint.sh"]
```

---

## Persistent Volumes

| Volume | Mount path | Contents |
|---|---|---|
| `dxspider-data` | `/spider/local_data` | DXSpider runtime state: users DB, spot files, log, debug, msg |
| _(config volume)_ | `/spider/local` | DXVars.pm, Listeners.pm (operator-editable) |

Spot files written by DXSpider are stored under `/spider/local_data/spots/` in
Perl `Data::Dumper` format. These survive container restarts and image upgrades.

---

## Ports

| Port | Protocol | Description |
|---|---|---|
| `7300` | TCP / telnet | DX cluster client connections and node peering |
| `8080` | HTTP (WebSocket) | ttyd sysop console (put behind Caddy; do not expose directly) |

Port 7300 is published directly to the host in `docker-compose.yml`. Port 8080
is internal and accessed only through Caddy's `/cluster` proxy.

---

## Health Check

The container's Docker health check verifies the telnet port is accepting
connections using `nc` (netcat-openbsd):

```
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3
    CMD nc -z 127.0.0.1 7300 || exit 1
```

---

## Stats Ingestor — Monitor User Login

The `stats-svc` ingestor connects to DXSpider over telnet and logs in as the
monitor user (default callsign: `statsmon`, set via `DX_MONITOR_USER`).

**DXSpider may reject a login that does not look like a valid callsign.**
If the ingestor fails to authenticate, set `DX_MONITOR_USER` to a
callsign-shaped value (e.g. `N0STATS`) or register the monitor account via the
sysop console (`console.pl`) before starting the ingestor:

```
# In console.pl:
set/user N0STATS
```

After login, the ingestor sends the following setup commands:

```
set/page 0
set/dx
set/wwv
set/wcy
set/announce
set/no/here
```

These subscribe the monitor session to all spot, WWV, WCY, and announce traffic
and mark the monitor account as not-here (invisible in `show/users`).
