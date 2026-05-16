# Deployment Guide

## Prerequisites

- **Docker Engine** with the Compose plugin (Docker Desktop or Docker Engine + `docker-compose-plugin`). Compose v2 is required (`docker compose` — note: no hyphen). The stack does not use the legacy `version:` key in `docker-compose.yml`.
- **A licensed amateur-radio callsign.** The cluster node must identify with a real callsign. DXSpider is amateur-radio software; operating with a placeholder callsign on a public node is incorrect.
- **A publicly routable hostname (optional but recommended for TLS).** If you want HTTPS, point a DNS A record to your host before first boot.
- **Ports 7300, 80, and 443 open in your firewall** for a public node. Port 7300 is the cluster telnet port; 80/443 are HTTP/HTTPS.

---

## First Bring-Up

### 1. Clone the repository

```bash
git clone <repo-url> dxcluster
cd dxcluster
```

### 2. Configure environment

```bash
cp .env.example .env
```

Edit `.env`. At minimum set these before first boot:

```ini
# Identity — required; use your real callsign
NODE_CALL=W1AW-2
SYSOP_CALL=W1AW
SYSOP_NAME=Hiram Percy Maxim
LOCATOR=FN31pr
NODE_QTH=Newington, CT, USA
SYSOP_EMAIL=hiram@example.com

# Passwords — must change before any public exposure
TTYD_PASSWORD=choose-a-strong-password
POSTGRES_PASSWORD=another-strong-password
DX_DB_DSN=postgresql://dxstats:another-strong-password@postgres:5432/dxstats
DX_MONITOR_PASSWORD=yet-another-password

# TLS — set to your FQDN for automatic Let's Encrypt, or leave as localhost
DOMAIN=dx.example.com
```

See [configuration.md](configuration.md) for the full variable reference.

### 3. Build the images

```bash
docker compose build
```

This clones DXSpider (EA3CV `mojo` fork, SHA `63d47180dc195e026bae23446eb9b798a0e923d6`) inside the `dxspider` image and installs the Python dependencies for `stats-svc`. Build output includes a `git log -1` line that prints the pinned SHA for audit.

### 4. Start the stack

```bash
docker compose up -d
```

This starts all four services in dependency order:
1. `postgres` starts first; stats-svc waits for its healthcheck to pass.
2. `dxspider` starts; entrypoint renders config, starts `cluster.pl` and `ttyd`.
3. `stats-svc` starts after postgres is healthy and dxspider has started; applies the DB schema, optionally runs backfill, then starts the ingestor and Uvicorn.
4. `caddy` starts after stats-svc and dxspider are started.

All services have `restart: unless-stopped` — they restart automatically on failure or host reboot until explicitly stopped.

---

## Verifying Health

Check service status:

```bash
docker compose ps
```

All four services should show `healthy` (or `running` for services whose healthcheck takes a moment to pass). If a service shows `unhealthy`, inspect its logs:

```bash
docker compose logs dxspider
docker compose logs stats-svc
docker compose logs postgres
docker compose logs caddy
```

**Healthcheck definitions:**

| Service | Check | Interval |
|---|---|---|
| `dxspider` | `nc -z 127.0.0.1 7300` | 30s (start period 30s) |
| `postgres` | `pg_isready -U dxstats` | 15s (start period 20s) |
| `stats-svc` | `GET http://127.0.0.1:8000/api/health` returns HTTP 200 | 30s (start period 20s) |
| `caddy` | `caddy version` | 30s (start period 10s) |

---

## Accessing the Stack

### Statistics dashboard

Open `http://localhost/` (or `https://dx.example.com/` if `DOMAIN` is set) in a browser. The dashboard serves the FastAPI static frontend with live charts and a WebSocket spot ticker.

### Sysop console

Open `http://localhost/cluster` in a browser. You will be prompted for the ttyd HTTP basic auth credentials (`TTYD_USER` / `TTYD_PASSWORD`). The page opens a browser terminal running `console.pl` — the DXSpider sysop command interface.

### Cluster telnet (users and peering)

```bash
telnet <host> 7300
```

Connect with your callsign at the login prompt. This is the standard DX cluster user interface.

---

## First-Run Items to Verify

These items require a Docker host and cannot be verified without running the containers. Complete them after first boot:

1. **`DXVars.pm` fields accepted.** After `docker compose up -d`, check that DXSpider started cleanly and accepted the rendered `DXVars.pm`. Look for errors in `docker compose logs dxspider`. The EA3CV `mojo` source may have additional required variables compared to the template — verify against the `DXVars.pm.issue` file in the cloned source at `/spider/DXVars.pm.issue` inside the container.

2. **Monitor-user login.** Watch `docker compose logs stats-svc` for lines indicating the ingestor connected successfully. If you see repeated connection failures, the `DX_MONITOR_USER` value (`statsmon` by default) may be rejected by DXSpider as a non-callsign value. If so:
   - Change `DX_MONITOR_USER` in `.env` to a callsign-shaped value (e.g., `N0CALL-9`).
   - Register that callsign in DXSpider before restarting stats-svc:
     ```bash
     docker compose exec dxspider perl /spider/perl/create_user.pl N0CALL-9
     ```
   - Or log in to the sysop console at `/cluster` and register the user via DXSpider commands.
   - Restart stats-svc: `docker compose restart stats-svc`.

3. **Backfill is a v1 no-op on native DXSpider spot files.** DXSpider writes spot files in Perl `Data::Dumper` format. The backfill parser handles only CSV/TSV `*.spots` files. On first boot, backfill will scan `/spider-spots/spots`, find no parseable files, log a message, and complete cleanly with 0 inserts. Charts fill from the live ingestor as spots arrive. This is a documented Phase 2 extension.

4. **`show/users` stream interleaving (v1 caveat).** The user list is refreshed every `DX_USERS_POLL_SECONDS` (default 20) seconds using a fixed 1-second collection window on the shared telnet stream. Spots may be buffered during this window. Protocol multiplexing is a Phase 2 item.

5. **ttyd architecture (arm64).** The pinned ttyd binary is x86_64. On arm64 hosts, rebuild with `--build-arg TTYD_URL=<arm64-url>`.

---

## Enabling TLS

Set `DOMAIN` in `.env` to your fully-qualified domain name:

```ini
DOMAIN=dx.example.com
```

Before restarting, ensure:
- DNS A/AAAA record for `dx.example.com` points to the public IP of your host.
- Ports 80 and 443 are open in the firewall.

Caddy will automatically obtain a Let's Encrypt certificate on first request. The certificate and ACME account key are stored in the `caddy-data` named volume and persist across restarts.

Restart Caddy to pick up the new domain:

```bash
docker compose up -d caddy
```

---

## Updating the Pinned DXSpider SHA

To update to a newer EA3CV `mojo` commit:

1. Identify the commit SHA you want on the EA3CV repository.
2. Rebuild the `dxspider` image with the new SHA:
   ```bash
   docker compose build \
     --build-arg SPIDER_SHA=<new-sha> \
     dxspider
   ```
3. Restart the service:
   ```bash
   docker compose up -d dxspider
   ```

To switch to a self-mirror:
```bash
docker compose build \
  --build-arg SPIDER_REPO=https://git.example.com/dxspider.git \
  --build-arg SPIDER_BRANCH=mojo \
  --build-arg SPIDER_SHA=<verified-sha> \
  dxspider
```

---

## Upgrading the Stack

**For services using pre-built images (`postgres`, `caddy`):**

```bash
docker compose pull postgres caddy
docker compose up -d postgres caddy
```

**For locally built services (`dxspider`, `stats-svc`):**

```bash
docker compose build dxspider stats-svc
docker compose up -d dxspider stats-svc
```

Or rebuild and restart everything at once:

```bash
docker compose build
docker compose up -d
```

Compose will only restart containers whose image or configuration has changed.

---

## Data Persistence

Four named Docker volumes hold all persistent state:

| Volume | Mounted at | Contains |
|---|---|---|
| `dxspider-config` | `/spider/local` (in `dxspider`) | Rendered `DXVars.pm`, `Listeners.pm`, operator config edits |
| `dxspider-data` | `/spider/local_data` (in `dxspider`), `/spider-spots:ro` (in `stats-svc`) | DXSpider runtime state: users DB, spot files, logs, messages |
| `postgres-data` | `/var/lib/postgresql/data` (in `postgres`) | All Postgres data files |
| `caddy-data` | `/data` (in `caddy`) | ACME account key and TLS certificate cache |

**Named volumes survive image updates.** When you rebuild and restart a service, its named volume is reattached to the new container unchanged. You do not lose cluster history, spot data, or certificates when upgrading images.

To list volumes:

```bash
docker volume ls | grep dxcluster
```
