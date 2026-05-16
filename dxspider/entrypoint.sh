#!/usr/bin/env bash
# entrypoint.sh — DXSpider container entrypoint
# Runs as root; drops privileges to sysop (uid 1000 / gid 251) for
# cluster.pl and ttyd after doing root-only setup tasks.
#
# tini is PID 1 (set in Dockerfile ENTRYPOINT), so SIGTERM is forwarded
# correctly and zombie reaping is handled automatically.
set -euo pipefail

# ---------------------------------------------------------------------------
# 1. Resolve configuration env vars with safe defaults
# ---------------------------------------------------------------------------
NODE_CALL="${NODE_CALL:-N0CALL-2}"
SYSOP_CALL="${SYSOP_CALL:-N0CALL}"
SYSOP_NAME="${SYSOP_NAME:-Sysop}"
LOCATOR="${LOCATOR:-AA00aa}"
NODE_QTH="${NODE_QTH:-Unknown QTH}"
SYSOP_EMAIL="${SYSOP_EMAIL:-sysop@example.com}"
NODE_TELNET_PORT="${NODE_TELNET_PORT:-7300}"
SYSOP_WEB_PORT="${SYSOP_WEB_PORT:-8080}"
TTYD_USER="${TTYD_USER:-sysop}"
TTYD_PASSWORD="${TTYD_PASSWORD:-changeme}"
OVERWRITE_CONFIG="${OVERWRITE_CONFIG:-no}"

echo "[entrypoint] NODE_CALL=${NODE_CALL}  SYSOP_CALL=${SYSOP_CALL}  LOCATOR=${LOCATOR}"
echo "[entrypoint] Telnet port=${NODE_TELNET_PORT}  Web console port=${SYSOP_WEB_PORT}"

# ---------------------------------------------------------------------------
# 2. Render /spider/local/DXVars.pm from template (only when absent or forced)
# ---------------------------------------------------------------------------
DXVARS_TARGET="/spider/local/DXVars.pm"
DXVARS_TMPL="/spider/templates/DXVars.pm.tmpl"

if [[ ! -f "${DXVARS_TARGET}" || "${OVERWRITE_CONFIG}" == "yes" ]]; then
    echo "[entrypoint] Writing ${DXVARS_TARGET} from template..."
    # Use sed with | delimiter to avoid clashes with / in paths or callsigns.
    sed \
        -e "s|__NODE_CALL__|${NODE_CALL}|g" \
        -e "s|__SYSOP_CALL__|${SYSOP_CALL}|g" \
        -e "s|__SYSOP_NAME__|${SYSOP_NAME}|g" \
        -e "s|__LOCATOR__|${LOCATOR}|g" \
        -e "s|__QTH__|${NODE_QTH}|g" \
        -e "s|__EMAIL__|${SYSOP_EMAIL}|g" \
        "${DXVARS_TMPL}" > "${DXVARS_TARGET}"
    echo "[entrypoint] DXVars.pm written."
else
    echo "[entrypoint] ${DXVARS_TARGET} exists and OVERWRITE_CONFIG!=yes — preserving operator config."
fi

# ---------------------------------------------------------------------------
# 3. Render /spider/local/Listeners.pm from template (same overwrite logic)
# ---------------------------------------------------------------------------
LISTENERS_TARGET="/spider/local/Listeners.pm"
LISTENERS_TMPL="/spider/templates/Listeners.pm.tmpl"

if [[ ! -f "${LISTENERS_TARGET}" || "${OVERWRITE_CONFIG}" == "yes" ]]; then
    echo "[entrypoint] Writing ${LISTENERS_TARGET} from template..."
    sed \
        -e "s|__TELNET_PORT__|${NODE_TELNET_PORT}|g" \
        "${LISTENERS_TMPL}" > "${LISTENERS_TARGET}"
    echo "[entrypoint] Listeners.pm written."
else
    echo "[entrypoint] ${LISTENERS_TARGET} exists and OVERWRITE_CONFIG!=yes — preserving operator config."
fi

# ---------------------------------------------------------------------------
# 4. Ensure runtime directories exist and are owned by sysop:spider
# ---------------------------------------------------------------------------
echo "[entrypoint] Ensuring runtime directories..."
mkdir -p \
    /spider/local \
    /spider/local_data \
    /spider/local_data/users \
    /spider/local_data/spots \
    /spider/local_data/log \
    /spider/local_data/debug \
    /spider/local_data/msg

chown -R sysop:spider /spider/local /spider/local_data
echo "[entrypoint] Ownership set on /spider/local and /spider/local_data."

# ---------------------------------------------------------------------------
# 5. First-run only: create sysop user record in DXSpider's users DB
#    Guard on the users directory being empty (idempotent across restarts).
#
#    DXSpider stores users as DB_File or flat files under local_data/users/;
#    the exact filename varies by version (e.g., dxspider_users or users.db).
#    We guard on ANY file existing in that directory rather than a hardcoded
#    filename — this is robust across DXSpider versions.
# ---------------------------------------------------------------------------
if [[ -z "$(ls -A /spider/local_data/users 2>/dev/null)" ]]; then
    echo "[entrypoint] First run detected — creating sysop user record..."
    runuser -u sysop -- perl /spider/perl/create_sysop.pl \
        || echo "[entrypoint] WARN: create_sysop.pl exited non-zero (may be harmless on first run)."
else
    echo "[entrypoint] Users directory not empty — skipping create_sysop.pl."
fi

# ---------------------------------------------------------------------------
# 6. Signal trap — forward SIGTERM/SIGINT to all children cleanly
# ---------------------------------------------------------------------------
_kill_if_set() {
    # Kill a process only if the PID variable is non-empty (guards the case
    # where shutdown fires before a child has been started and its PID set).
    local pid="${1:-}"
    [[ -n "${pid}" ]] && kill "${pid}" 2>/dev/null || true
}

_shutdown() {
    echo "[entrypoint] Received shutdown signal — terminating children..."
    _kill_if_set "${CLUSTER_PID:-}"
    _kill_if_set "${TTYD_PID:-}"
    # Wait only on PIDs that were actually started.
    [[ -n "${CLUSTER_PID:-}" ]] && wait "${CLUSTER_PID}" 2>/dev/null || true
    [[ -n "${TTYD_PID:-}" ]]    && wait "${TTYD_PID}"    2>/dev/null || true
    echo "[entrypoint] Children stopped. Goodbye."
    exit 0
}
trap _shutdown SIGTERM SIGINT

# ---------------------------------------------------------------------------
# 7. Start cluster.pl in background (as sysop)
# ---------------------------------------------------------------------------
echo "[entrypoint] Starting cluster.pl..."
runuser -u sysop -- perl -w /spider/perl/cluster.pl &
CLUSTER_PID=$!
echo "[entrypoint] cluster.pl PID=${CLUSTER_PID}"

# Brief settle window then liveness check.
sleep 3
if ! kill -0 "${CLUSTER_PID}" 2>/dev/null; then
    echo "[entrypoint] ERROR: cluster.pl (PID ${CLUSTER_PID}) exited immediately." >&2
    echo "[entrypoint] Check /spider/local_data/debug/ for DXSpider logs." >&2
    exit 1
fi
echo "[entrypoint] cluster.pl is alive."

# ---------------------------------------------------------------------------
# 8. Start ttyd web console (as sysop) on SYSOP_WEB_PORT
#
#    ttyd wraps console.pl in a browser-accessible terminal.
#    SECURITY: Basic auth is enabled via -c user:pass.
#              CHANGE THE DEFAULT PASSWORD and put ttyd behind a reverse
#              proxy (TLS + IP allowlist) before exposing to the internet.
#              Default credentials: sysop / changeme  (MUST be overridden
#              via TTYD_USER and TTYD_PASSWORD env vars in production).
# ---------------------------------------------------------------------------
echo "[entrypoint] Starting ttyd on port ${SYSOP_WEB_PORT}..."
runuser -u sysop -- \
    /usr/local/bin/ttyd \
        --port "${SYSOP_WEB_PORT}" \
        --credential "${TTYD_USER}:${TTYD_PASSWORD}" \
        perl /spider/perl/console.pl &
TTYD_PID=$!
echo "[entrypoint] ttyd PID=${TTYD_PID}"

# ---------------------------------------------------------------------------
# 9. Wait for both background processes; exit if either dies unexpectedly
# ---------------------------------------------------------------------------
echo "[entrypoint] Cluster running. Waiting for children..."
wait -n "${CLUSTER_PID}" "${TTYD_PID}" 2>/dev/null || true

# If we reach here without a trap signal, one process exited unexpectedly.
echo "[entrypoint] ERROR: A child process exited unexpectedly." >&2
_kill_if_set "${CLUSTER_PID:-}"
_kill_if_set "${TTYD_PID:-}"
exit 1
