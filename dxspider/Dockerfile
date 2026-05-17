# syntax=docker/dockerfile:1
#
# DXSpider cluster node — Mojolicious/mojo branch
# Base: debian:bookworm-slim (Perl + system libs available via apt)
#
# Source provenance:
#   Default: EA3CV mojo fork — publicly auditable, SHA-pinned.
#            The mojo branch is a single squashed commit; the full clone
#            (no --depth) is intentional so that a self-hosted mirror with
#            full history can be substituted via build args without issues.
#
#   Override options (pass with --build-arg):
#
#   (1) Self-hosted mirror (recommended for production):
#       --build-arg SPIDER_REPO=https://git.example.com/dxspider.git \
#       --build-arg SPIDER_BRANCH=mojo \
#       --build-arg SPIDER_SHA=<your-verified-sha>
#
#   (2) latchdevel full-history mirror (frozen 2022-02-07, older codebase):
#       --build-arg SPIDER_REPO=https://github.com/latchdevel/DXspider.git \
#       --build-arg SPIDER_BRANCH=master \
#       --build-arg SPIDER_SHA=e61ab5eeea22241ea8d8f1f6d072f5249901d788

FROM debian:bookworm-slim

# ---------------------------------------------------------------------------
# Build arguments — source coordinates (overridable; see comment block above)
# ---------------------------------------------------------------------------
ARG SPIDER_REPO=https://github.com/EA3CV/dx-spider.git
ARG SPIDER_BRANCH=mojo
ARG SPIDER_SHA=63d47180dc195e026bae23446eb9b798a0e923d6

# ---------------------------------------------------------------------------
# System dependencies (no --install-recommends; only what cluster.pl needs)
#
# Core runtime:
#   perl make gcc        — Perl + build toolchain for any XS modules
#   tini                 — PID-1 init (in bookworm repos; used in ENTRYPOINT)
#   procps               — provides kill/pgrep used by entrypoint health check
#   netcat-openbsd       — nc used by HEALTHCHECK
#   wget                 — fetches ttyd binary below
#
# Perl modules (apt — prefer system packages over cpanm for reproducibility):
#   libev-perl                — EV event loop (Mojolicious async I/O)
#   libmojolicious-perl       — Mojolicious web/event framework
#   libjson-perl              — JSON (pure-Perl fallback)
#   libjson-xs-perl           — JSON::XS (fast JSON, XS)
#   libdata-structure-util-perl — Data::Structure::Util
#   libmath-round-perl        — Math::Round
#   libnet-cidr-lite-perl     — Net::CIDR::Lite (IP filtering)
#   libcurses-perl            — Curses (console.pl TUI)
#   libdigest-sha-perl        — Digest::SHA (spot/msg checksums)
#   libnet-telnet-perl        — Net::Telnet (cluster link I/O)
#   libtimedate-perl          — Date::Format / Date::Parse
#   libdbi-perl               — DBI (database interface)
#   libdbd-sqlite3-perl       — DBD::SQLite3 (users DB backend)
#   ca-certificates git       — TLS + source clone
# ---------------------------------------------------------------------------
RUN apt-get update && apt-get install -y --no-install-recommends \
        git \
        ca-certificates \
        perl \
        make \
        gcc \
        libev-perl \
        libmojolicious-perl \
        libjson-perl \
        libjson-xs-perl \
        libdata-structure-util-perl \
        libmath-round-perl \
        libnet-cidr-lite-perl \
        libcurses-perl \
        libdigest-sha-perl \
        libnet-telnet-perl \
        libtimedate-perl \
        libdbi-perl \
        libdbd-sqlite3-perl \
        procps \
        netcat-openbsd \
        tini \
        wget \
    && rm -rf /var/lib/apt/lists/*

# ---------------------------------------------------------------------------
# cpanm — install any Perl modules NOT available in bookworm apt.
# Currently empty: all required modules are covered by apt above.
# Add entries here (one per line, no --force) if a build test reveals gaps.
# ---------------------------------------------------------------------------
# RUN cpan App::cpanminus \
#     && cpanm --notest \
#         Some::Missing::Module \
#     && rm -rf /root/.cpanm

# ---------------------------------------------------------------------------
# ttyd — browser terminal wrapping console.pl
# NOT packaged in bookworm; use pinned static binary (version 1.7.7).
# Pinned URL: https://github.com/tsl0922/ttyd/releases/download/1.7.7/ttyd.x86_64
# Architecture note: this binary is x86_64 only.
#   arm64 users: override with --build-arg TTYD_URL=<arm64-static-url>
#   or build ttyd from source: https://github.com/tsl0922/ttyd
# ---------------------------------------------------------------------------
ARG TTYD_URL=https://github.com/tsl0922/ttyd/releases/download/1.7.7/ttyd.x86_64
RUN wget -qO /usr/local/bin/ttyd "${TTYD_URL}" \
    && chmod +x /usr/local/bin/ttyd

# ---------------------------------------------------------------------------
# Non-root user: group spider (gid 251) + user sysop (uid 1000, home /spider)
# Created before cloning so the home dir is /spider (the clone target).
# The image build clones as root; entrypoint chowns runtime dirs at start.
# ---------------------------------------------------------------------------
RUN groupadd --gid 251 spider \
    && useradd --uid 1000 --gid 251 --home-dir /spider --shell /bin/bash \
               --no-create-home sysop

# ---------------------------------------------------------------------------
# Clone DXSpider source (as root; runtime dirs chowned by entrypoint)
# Full clone (no --depth) so a mirror with full history also works.
# git checkout pins to the exact audited SHA.
# ---------------------------------------------------------------------------
RUN git clone --branch "${SPIDER_BRANCH}" "${SPIDER_REPO}" /spider \
    && git -C /spider checkout "${SPIDER_SHA}" \
    && git -C /spider log -1 --format="DXSpider source: %H  %ai  %s"

# ---------------------------------------------------------------------------
# Config templates — copied to /spider/templates/; entrypoint renders them
# into /spider/local/ (volume-mounted, operator-editable).
# ---------------------------------------------------------------------------
RUN mkdir -p /spider/templates
COPY templates/DXVars.pm.tmpl    /spider/templates/DXVars.pm.tmpl
COPY templates/Listeners.pm.tmpl /spider/templates/Listeners.pm.tmpl
COPY templates/motd.tmpl    /spider/templates/motd.tmpl
COPY templates/startup.tmpl /spider/templates/startup.tmpl
COPY templates/cmd_dashboard.tmpl /spider/templates/cmd_dashboard.tmpl
COPY dashboard-url.sh       /spider/dashboard-url.sh

# ---------------------------------------------------------------------------
# Entrypoint script
# ---------------------------------------------------------------------------
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# ---------------------------------------------------------------------------
# Persistent volumes
#   /spider/local      — node config: DXVars.pm, Listeners.pm (operator-editable)
#   /spider/local_data — runtime state: users DB, spots, logs, msgs, debug
# ---------------------------------------------------------------------------
VOLUME ["/spider/local", "/spider/local_data"]

# ---------------------------------------------------------------------------
# Ports
#   7300 — DX cluster telnet (clients + cluster peering)
#   8080 — ttyd web console (put behind reverse proxy + TLS in production)
# ---------------------------------------------------------------------------
EXPOSE 7300 8080

# ---------------------------------------------------------------------------
# Health check — verify telnet port is accepting connections
# Uses nc from netcat-openbsd (installed above); adjust --start-period if
# your hardware is slow to spin up Mojolicious event loop.
# ---------------------------------------------------------------------------
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD nc -z 127.0.0.1 7300 || exit 1

# ---------------------------------------------------------------------------
# tini as PID 1: forwards signals correctly, reaps zombies.
# tini is installed from bookworm apt (/usr/bin/tini).
# ---------------------------------------------------------------------------
ENTRYPOINT ["/usr/bin/tini", "--", "/entrypoint.sh"]
