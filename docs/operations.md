# Operations Runbook

## Routine Operations

### Start / Stop / Restart

```bash
# Start all services in the background
docker compose up -d

# Stop all services (containers stopped, volumes preserved)
docker compose down

# Restart a single service (e.g., after changing its env vars in .env)
docker compose restart stats-svc

# Restart all services
docker compose restart

# Stop and remove containers, networks (volumes NOT removed)
docker compose down

# Stop and remove everything including volumes — DESTROYS ALL DATA
# docker compose down -v  # do not run this in production
```

### Viewing Logs

```bash
# All services, follow
docker compose logs -f

# Single service, last 100 lines, follow
docker compose logs -f --tail=100 dxspider
docker compose logs -f --tail=100 stats-svc
docker compose logs -f --tail=100 postgres
docker compose logs -f --tail=100 caddy
```

**What to look for:**

| Service | Normal startup indicators |
|---|---|
| `dxspider` | `[entrypoint] cluster.pl is alive.` then `[entrypoint] ttyd PID=...` |
| `stats-svc` | `Logged in as <monitor-user>; setup commands sent` |
| `postgres` | `database system is ready to accept connections` |
| `caddy` | No errors; TLS certificate obtained if DOMAIN is set |

---

## Health Monitoring

Check the status of all services at a glance:

```bash
docker compose ps
```

All services should show `healthy`. If a service shows `unhealthy` or `restarting`, check its logs immediately.

**Spot arrival check:** Query the health endpoint and the spot count:

```bash
curl -s http://localhost/api/health
curl -s http://localhost/api/activity | python -m json.tool
```

**Postgres connectivity check from stats-svc:**

```bash
docker compose exec stats-svc python -c "
import asyncio, asyncpg, os
dsn = os.environ.get('DX_DB_DSN', 'postgresql://dxstats:dxstats@postgres:5432/dxstats')
async def check():
    conn = await asyncpg.connect(dsn)
    n = await conn.fetchval('SELECT COUNT(*) FROM spots')
    print(f'spots: {n}')
    await conn.close()
asyncio.run(check())
"
```

**Ingestor connection check:** Look for connection log lines:

```bash
docker compose logs stats-svc | grep -i "connect\|login\|disconnect\|reconnect"
```

---

## Backups

Automated backups are not included in v1 of the stack. The following procedures are recommended for any node that accumulates data you want to preserve.

### Postgres Backup (`pg_dump`)

```bash
# One-shot dump to a gzip-compressed file on the host
docker compose exec postgres pg_dump -U dxstats dxstats \
  | gzip > /backups/dxstats-$(date +%Y%m%d-%H%M%S).sql.gz
```

**Cron snippet** (run daily at 02:00 UTC; adapt `COMPOSE_DIR` and `BACKUP_DIR`):

```cron
COMPOSE_DIR=/home/youruser/dxcluster
BACKUP_DIR=/backups/dxcluster

0 2 * * * cd $COMPOSE_DIR && docker compose exec -T postgres pg_dump -U dxstats dxstats | gzip > $BACKUP_DIR/dxstats-$(date +\%Y\%m\%d-\%H\%M\%S).sql.gz 2>&1
```

Retain and prune old dumps:

```cron
0 3 * * * find /backups/dxcluster -name "dxstats-*.sql.gz" -mtime +30 -delete
```

### Volume Backup (full Docker volume snapshot)

The `dxspider-data` volume contains the users database, spot files, and logs. Back it up without stopping the container by streaming a tar archive:

```bash
# Backup dxspider-data to a tar.gz on the host
docker run --rm \
  -v dxcluster_dxspider-data:/source:ro \
  -v /backups/dxcluster:/backup \
  debian:bookworm-slim \
  tar czf /backup/dxspider-data-$(date +%Y%m%d-%H%M%S).tar.gz -C /source .
```

The volume name prefix (`dxcluster_`) comes from the `name: dxcluster` key in `docker-compose.yml`. Verify with `docker volume ls`.

### Restore Procedure

**Postgres restore:**

```bash
# Stop stats-svc first to avoid writes during restore
docker compose stop stats-svc

# Drop and recreate the database (connect as the postgres superuser)
docker compose exec postgres psql -U dxstats -c "DROP DATABASE dxstats;"
docker compose exec postgres psql -U dxstats -c "CREATE DATABASE dxstats;"

# Restore from dump
gunzip -c /backups/dxcluster/dxstats-<timestamp>.sql.gz \
  | docker compose exec -T postgres psql -U dxstats dxstats

# Restart stats-svc (it will re-apply the schema idempotently)
docker compose start stats-svc
```

**Volume restore (dxspider-data):**

```bash
docker compose stop dxspider stats-svc

# Clear volume and restore
docker run --rm \
  -v dxcluster_dxspider-data:/target \
  -v /backups/dxcluster:/backup \
  debian:bookworm-slim \
  bash -c "rm -rf /target/* && tar xzf /backup/dxspider-data-<timestamp>.tar.gz -C /target"

docker compose start dxspider stats-svc
```

---

## Disaster Recovery

If a container or volume is lost:

1. **Lost container only (volume intact):** `docker compose up -d` recreates containers from images and reattaches volumes. No data loss.

2. **Lost `postgres-data` volume:** Restore from the most recent `pg_dump` backup using the procedure above. Spot data since the last backup is lost; charts recover as the live ingestor ingests new spots.

3. **Lost `dxspider-data` volume:** Restore from the volume backup. The users database, spot files, and cluster logs are in this volume. If no backup exists, DXSpider reinitializes on first boot; the stats-svc backfill will find no parseable spot files (v1 no-op) and charts fill from live traffic.

4. **Lost `caddy-data` volume:** Caddy re-obtains a Let's Encrypt certificate automatically on next startup, subject to ACME rate limits. No manual action needed.

5. **Lost `dxspider-config` volume:** The config files (`DXVars.pm`, `Listeners.pm`) are regenerated from templates on next container start, using current `.env` values. Operator customizations made directly in the volume are lost — keep a copy of any edits outside the volume.

---

## Log Locations

Container stdout/stderr is captured by Docker and accessible via `docker compose logs`. DXSpider also writes debug logs inside the `dxspider-data` volume:

| Log | Path inside container | Volume |
|---|---|---|
| DXSpider debug log | `/spider/local_data/debug/` | `dxspider-data` |
| DXSpider cluster log | `/spider/local_data/log/` | `dxspider-data` |
| stats-svc logs | Container stdout (structured) | — (Docker logging driver) |
| Caddy access/error | Container stdout | — (Docker logging driver) |
| Postgres logs | Container stdout | — (Docker logging driver) |

To read DXSpider debug logs:

```bash
docker compose exec dxspider ls /spider/local_data/debug/
docker compose exec dxspider tail -f /spider/local_data/debug/<date>.log
```

---

## Rotating ttyd / Sysop Credentials

The ttyd basic auth credentials are read from `TTYD_USER` and `TTYD_PASSWORD` in `.env` each time the container starts. To rotate them:

1. Update `TTYD_USER` and/or `TTYD_PASSWORD` in `.env`.
2. Restart the dxspider container:
   ```bash
   docker compose up -d dxspider
   ```

The new credentials take effect immediately on restart. There is no credential store to flush — the password is passed to `ttyd` as a command-line argument at startup.

---

## Ingestor Cannot Connect to DXSpider

If `docker compose logs stats-svc` shows repeated disconnection or login failure:

**1. Check DXSpider is healthy:**
```bash
docker compose ps dxspider
telnet localhost 7300
```
If the telnet connection is refused, DXSpider has not started correctly. Check `docker compose logs dxspider`.

**2. Monitor-user callsign caveat.** The default `DX_MONITOR_USER=statsmon` is not a callsign-shaped value. Some DXSpider versions reject non-callsign logins. The symptom is a connection that opens but produces no spots in the dashboard.

Fix:
- Change `DX_MONITOR_USER` in `.env` to a callsign-shaped value, e.g., `N0CALL-9`.
- Register the user in DXSpider (only needed once; the record persists in the `dxspider-data` volume):
  ```bash
  docker compose exec dxspider perl /spider/perl/create_user.pl N0CALL-9
  ```
- Restart stats-svc:
  ```bash
  docker compose restart stats-svc
  ```

**3. Backoff state.** The ingestor uses exponential back-off (base 1 s, cap 60 s) before retrying. After fixing the issue, restart stats-svc to reset the back-off counter immediately rather than waiting.

---

## `show/users` Stream-Interleaving Caveat (v1)

The ingestor polls `show/users` every `DX_USERS_POLL_SECONDS` seconds (default 20) on the same telnet stream it uses to receive spots. The response is collected using a 1-second window. Spots that arrive from DXSpider during this 1-second collection window are buffered by the OS TCP stack and processed immediately after the window closes — they are not lost, but they are delayed by up to 1 second every 20 seconds.

This is a documented v1 design simplification. Protocol multiplexing (maintaining separate state-machine tracks for command/response and streaming data on the same connection) is planned for Phase 2.

---

## Capacity Notes

The stack is designed for a single public standalone node. Observed limits from the design:

- **Spot storage:** Postgres with a named volume has no inherent size limit beyond disk space. The `spots` table grows indefinitely; plan a retention policy (e.g., `DELETE FROM spots WHERE ts < NOW() - INTERVAL '90 days'`) or use PostgreSQL table partitioning for long-running nodes.
- **Connected users:** The `connected_users` table is replaced entirely on each poll (DELETE + INSERT). Performance scales with the number of connected users, not history. Suitable for typical single-node user counts.
- **WebSocket clients:** Each connected WebSocket gets its own `asyncio.Queue(maxsize=256)`. Slow clients that fall behind have their oldest queued event dropped (non-blocking broadcast). There is no explicit client limit; practical limits depend on host resources.
- **Rollup table:** `spot_rollup_hourly` grows at roughly (distinct band × mode × source × dxcc combinations) rows per hour. With typical amateur traffic this is small. The table is queried by chart endpoints and benefits from the composite primary key index.

---

## Security Hardening Checklist for a Public Node

Before exposing the stack to the internet:

- [ ] **Change all default passwords.** `POSTGRES_PASSWORD`, `DX_MONITOR_PASSWORD`, and `TTYD_PASSWORD` all default to `changeme` or `dxstats`. These are well-known values.
- [ ] **Change the `DX_DB_DSN` password to match `POSTGRES_PASSWORD`.**
- [ ] **Set real callsign identity.** `NODE_CALL`, `SYSOP_CALL`, `SYSOP_NAME`, `LOCATOR`, `NODE_QTH`, `SYSOP_EMAIL` must all be real values for a public node.
- [ ] **Enable TLS.** Set `DOMAIN` to your FQDN. Do not run a public node on plain HTTP.
- [ ] **Firewall rules.** Only ports 7300, 80, and 443 should be reachable from the internet. Ports 8080, 8000, and 5432 are internal and must not be exposed.
- [ ] **Do not publish port 5432.** The `docker-compose.yml` does not publish Postgres. Verify with `docker compose ps` that no `5432->5432` port mapping appears.
- [ ] **Do not publish port 8080.** The ttyd console is internal-only; Caddy proxies it. Verify there is no `8080->8080` mapping in `docker compose ps`.
- [ ] **Review `OVERWRITE_CONFIG=no`.** The default preserves operator-edited configs. Only set `yes` for initial templating.
- [ ] **Register the monitor user with minimal privileges.** The `DX_MONITOR_USER` account is used only for receiving the spot stream. Ensure it has no sysop rights in DXSpider.
- [ ] **Consider IP allowlisting for `/cluster`.** The ttyd console exposes a root shell via `console.pl`. If only the sysop needs access, restrict `/cluster` to known IPs (e.g., via Caddy `remote_ip` matcher or an upstream firewall rule).
- [ ] **Keep images updated.** `postgres:16` and `caddy:2.8` receive security patches via image tags. Pull and restart periodically: `docker compose pull postgres caddy && docker compose up -d postgres caddy`.
- [ ] **Rebuild dxspider and stats-svc images** periodically to pick up OS-level security updates in the base layers: `docker compose build --no-cache && docker compose up -d`.
- [ ] **Dashboard has no authentication.** The stats dashboard (`/`) is intentionally public-read in v1 (read-only aggregated data, no personal information). If your deployment requires access control, add it via Caddy `basicauth` or an upstream reverse proxy.
- [ ] **Back up before any major upgrade.** Take a `pg_dump` and a volume snapshot before updating images or changing configuration.
