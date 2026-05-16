# Dashboard — Web UI Guide

The DX Cluster Stats dashboard is a single-page HTML application served by the
`stats-svc` container at the root path `/`. It is reachable through Caddy at
`https://<your-domain>/` (or `http://localhost/` in local mode).

The dashboard requires no login (it is read-only public statistics). All
interactive controls are on-page; no page reloads are needed.

---

## Technology

- **Apache ECharts 5.5.1** loaded from `cdnjs.cloudflare.com`. For offline or
  air-gapped deployments, download and vendor the file:
  `https://cdnjs.cloudflare.com/ajax/libs/echarts/5.5.1/echarts.min.js`
  and place it in `stats-svc/app/static/` with a matching `<script>` tag in
  `index.html`.
- **No build toolchain.** The frontend is a single `index.html`, `app.js`, and
  `style.css`. No Node, npm, or bundler is involved.
- **No JavaScript framework.** Plain ES2020 with IIFE module isolation.

---

## Source Filter

The header contains a **Source** dropdown with three options:

| Option | Effect |
|---|---|
| `Both` (default) | Show human + RBN/skimmer spots |
| `Human` | Show only spots submitted by human operators |
| `RBN` | Show only Reverse Beacon Network / skimmer spots |

Changing the dropdown immediately refetches all chart data from `/api/*?source=<value>`.

---

## Refresh Behaviour

- **Polling:** all charts and tables are refreshed every **30 seconds** via
  `setInterval`. This keeps data reasonably current without hammering the API.
- **Live WebSocket updates:** new spots and connected-users snapshots arrive in
  real time over `/ws`. The ticker and user count update immediately on each
  message; the other charts update on the next 30-second poll.
- On WebSocket disconnect the client reconnects automatically using exponential
  back-off starting at 1 second, capped at 30 seconds.

---

## Dashboard Panels

### Activity Over Time

A **smooth line chart** (ECharts `type: 'line'`, `smooth: true`) showing the
number of spots per hour for the last 24 hours. Data comes from
`GET /api/activity?source=<s>&hours=24`. The X axis shows the hour in `HH:MM`
format (UTC); the Y axis shows the spot count. Hours with no spots appear as
zero — the API always returns exactly 24 buckets.

### Band Breakdown

A **donut pie chart** showing spot-count distribution across amateur bands
(160m, 80m, 60m, 40m, 30m, 20m, 17m, 15m, 12m, 10m, 6m, 4m, 2m, 70cm).
Data comes from `GET /api/bands?source=<s>`. Spots whose frequency does not
fall within any known IARU band edge appear in the `"unknown"` slice.

### Mode Breakdown

A **donut pie chart** showing spot-count distribution by mode (CW, SSB, FT8,
FT4, JT65, JT9, RTTY, PSK31, PSK, AM, FM). Data comes from
`GET /api/modes?source=<s>`. Spots where neither the comment nor the frequency
sub-segment allows mode inference appear as `"unknown"`.

### Geographic

A **bar chart** (ECharts `type: 'bar'`) showing the top 15 entries for the
selected geographic dimension. Data comes from
`GET /api/geo?source=<s>&by=<dimension>&top=15`.

The **By** dropdown in the panel header controls grouping:

| Option | Description |
|---|---|
| `DX Continent` (`dx_continent`) | Continent of the DX station spotted |
| `DX Entity` (`dx_dxcc`) | DXCC entity of the DX station spotted |
| `Spotter Entity` (`spotter_dxcc`) | DXCC entity of the spotter |

Changing the dropdown immediately refreshes this panel.

### Top Spotters

A **ranked table** (`#`, `Callsign`, `Spots`) showing the 10 most active
spotters over the last 24 hours. Data comes from
`GET /api/top/spotters?source=<s>&limit=10&hours=24`.

### Top DX

A **ranked table** (`#`, `Callsign`, `Times Spotted`) showing the 10 most
frequently spotted DX stations over the last 24 hours. Data comes from
`GET /api/top/dx?source=<s>&limit=10&hours=24`.

### Rare DX

A **ranked table** (`#`, `Callsign`, `Times Spotted`) showing the 10
least-spotted DX stations over the last 24 hours — rarest first. Useful for
finding rare or unusual DX activity. Data comes from
`GET /api/top/rare-dx?source=<s>&limit=10&hours=24`.

### Callsign Lookup

A **search panel** with a text input and a **Look up** button. Type any amateur
callsign (case-insensitive) and press Enter or click the button to fetch activity
for that callsign over the last 7 days.

Results show:
- A summary line: `<CALLSIGN> — spotted others N×, spotted as DX M× (last 7 days)`.
- A table of up to 25 recent spots (newest first) with columns: `Time`, `Spotter`,
  `DX`, `Freq`, `Band`, `Mode`, `Src`.

Data comes from `GET /api/callsign/<CALL>?hours=168`.

### Live Spot Ticker

A **live list** that prepends new spots as they arrive over the WebSocket
(`type: "spot"` events). Displays up to 50 entries; older entries scroll off the
bottom. Each line shows: `HH:MM:SS  DX_CALL  FREQ kHz  < SPOTTER`.

Shows `"Waiting for live spots…"` until the first WebSocket spot arrives.

### Connected Users

A **list** of callsigns currently connected to the DXSpider cluster, updated by
`type: "users"` WebSocket events (pushed after each `show/users` poll,
approximately every 20 seconds). Each entry shows the callsign and connection
type (e.g. `LOCAL`, `TELNET`). The total connected count is also displayed in the
page header.

---

## Security: XSS Escaping

All values sourced from the telnet stream (callsigns, comments, DXCC entity
names) are passed through an `esc()` function before being inserted into the DOM:

```javascript
function esc(s) {
  return (s == null ? '' : String(s))
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}
```

This prevents stored or reflected XSS from DXSpider telnet-sourced values.
ECharts tooltip and legend rendering is safe because values are passed as data
(not injected as HTML).

---

## How to Access the Dashboard

| Deployment mode | URL |
|---|---|
| Production (DOMAIN set, TLS) | `https://<your-domain>/` |
| Local / HTTP-only | `http://localhost/` |
| Direct to stats-svc (dev) | `http://localhost:8000/` |

Caddy proxies `/` to `stats-svc:8000`. The FastAPI app mounts static files at
`/` (with `html=True`), so `GET /` returns `index.html`. The `/api/*` and `/ws`
routes are registered before the static mount and therefore take precedence over
static file lookup.
