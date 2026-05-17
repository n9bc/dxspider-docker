#!/usr/bin/env sh
# Derive the dashboard URL. Single source of truth, sourced by
# entrypoint.sh and exercised directly by the test suite.
# Explicit DASHBOARD_URL wins; else derive from DOMAIN.
derive_dashboard_url() {
    if [ -n "${DASHBOARD_URL:-}" ]; then
        printf '%s' "${DASHBOARD_URL}"
        return 0
    fi
    _domain="${DOMAIN:-localhost}"
    if [ "${_domain}" = "localhost" ]; then
        printf 'http://localhost/'
    else
        printf 'https://%s/' "${_domain}"
    fi
}
