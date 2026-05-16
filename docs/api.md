# Stats Service API Reference

`stats-svc` exposes a REST API under `/api/` and a WebSocket at `/ws`. All
endpoints are served by FastAPI on port 8000 (proxied through Caddy at `/`).

---

## Common Concepts

### `source` Query Parameter

Most endpoints accept a `source` query parameter that filters spots by origin:

| Value | Meaning |
|---|---|
| `both` | Human + RBN/skimmer spots (default) |
| `human` | Spots from human operators only |
| `rbn` | Spots from RBN/skimmer nodes only |

Passing any other value returns HTTP 422.

### `hours` Query Parameter

Where present, `hours` sets the look-back window (in whole hours from now, UTC).
Valid range: 1–168 (1 week) unless otherwise noted.

### Response Format

All endpoints return `application/json`. Error responses use FastAPI's default
422 Unprocessable Entity structure for validation failures.

---

## Endpoints

### `GET /api/health`

Liveness check. Returns immediately without touching the database.

**Response:**
```json
{"status": "ok"}
```

**curl example:**
```bash
curl http://localhost:8000/api/health
```

---

### `GET /api/activity`

Returns per-hour spot counts for the last N hours.  Exactly `hours` buckets are
always returned; hours with no spots have `count: 0`.  Derived from the hourly
rollup table.

**Query parameters:**

| Parameter | Type | Default | Validation |
|---|---|---|---|
| `source` | `human\|rbn\|both` | `both` | 422 on invalid value |
| `hours` | integer | `24` | 1–168 |

**Response shape:** `list[{"hour": string, "count": integer}]`

- `hour` — ISO 8601 UTC datetime string truncated to the hour boundary, e.g.
  `"2026-05-16T14:00:00+00:00"`.
- `count` — number of spots in that hour.
- List is in ascending chronological order.

**Example response:**
```json
[
  {"hour": "2026-05-16T13:00:00+00:00", "count": 42},
  {"hour": "2026-05-16T14:00:00+00:00", "count": 57},
  {"hour": "2026-05-16T15:00:00+00:00", "count": 0}
]
```

**curl example:**
```bash
curl "http://localhost:8000/api/activity?source=human&hours=24"
```

---

### `GET /api/bands`

Returns spot counts grouped by amateur band, descending by count. Derived from
the hourly rollup table. Empty-string band values are relabelled `"unknown"`.

**Query parameters:**

| Parameter | Type | Default | Validation |
|---|---|---|---|
| `source` | `human\|rbn\|both` | `both` | 422 on invalid value |

**Response shape:** `list[{"label": string, "value": integer}]`

- `label` — band name (e.g. `"20m"`, `"40m"`, `"unknown"`).
- `value` — total spot count.

**Example response:**
```json
[
  {"label": "20m", "value": 1503},
  {"label": "40m", "value": 892},
  {"label": "15m", "value": 341},
  {"label": "unknown", "value": 12}
]
```

**curl example:**
```bash
curl "http://localhost:8000/api/bands?source=both"
```

---

### `GET /api/modes`

Returns spot counts grouped by mode, descending by count. Derived from the
hourly rollup table. Empty-string mode values are relabelled `"unknown"`.

**Query parameters:**

| Parameter | Type | Default | Validation |
|---|---|---|---|
| `source` | `human\|rbn\|both` | `both` | 422 on invalid value |

**Response shape:** `list[{"label": string, "value": integer}]`

- `label` — mode string (e.g. `"CW"`, `"SSB"`, `"FT8"`, `"unknown"`).
- `value` — total spot count.

**Example response:**
```json
[
  {"label": "CW",  "value": 2104},
  {"label": "FT8", "value": 1876},
  {"label": "SSB", "value": 634},
  {"label": "unknown", "value": 28}
]
```

**curl example:**
```bash
curl "http://localhost:8000/api/modes?source=rbn"
```

---

### `GET /api/geo`

Returns spot counts grouped by a geographic dimension, descending by count, up
to `top` entries. Derived from the hourly rollup table. Empty values are
relabelled `"unknown"`.

**Query parameters:**

| Parameter | Type | Default | Validation |
|---|---|---|---|
| `source` | `human\|rbn\|both` | `both` | 422 on invalid value |
| `by` | string | `dx_continent` | Must be one of `dx_continent`, `dx_dxcc`, `spotter_dxcc`; otherwise 422 |
| `top` | integer | `15` | 1–100 |

**`by` values:**

| Value | Groups by |
|---|---|
| `dx_continent` | Continent of the DX station (e.g. `"EU"`, `"NA"`) |
| `dx_dxcc` | DXCC entity of the DX station (e.g. `"Japan"`) |
| `spotter_dxcc` | DXCC entity of the spotter |

**Response shape:** `list[{"label": string, "value": integer}]`

**Example response:**
```json
[
  {"label": "EU", "value": 3201},
  {"label": "NA", "value": 1892},
  {"label": "AS", "value": 1044},
  {"label": "unknown", "value": 57}
]
```

**curl example:**
```bash
curl "http://localhost:8000/api/geo?by=dx_continent&top=10"
curl "http://localhost:8000/api/geo?by=dx_dxcc&top=20&source=human"
```

**422 example:**
```bash
curl "http://localhost:8000/api/geo?by=invalid"
# → 422: 'by' must be one of ['dx_continent', 'dx_dxcc', 'spotter_dxcc']
```

---

### `GET /api/top/spotters`

Returns the most active spotters by spot count over the last N hours. Derived
from raw spot rows (not rollup), so individual callsigns are available.

**Query parameters:**

| Parameter | Type | Default | Validation |
|---|---|---|---|
| `source` | `human\|rbn\|both` | `both` | 422 on invalid value |
| `limit` | integer | `10` | 1–100 |
| `hours` | integer | `24` | 1–168 |

**Response shape:** `list[{"callsign": string, "count": integer}]`

- Sorted descending by count.

**Example response:**
```json
[
  {"callsign": "DK9IP",  "count": 342},
  {"callsign": "OH6BG",  "count": 287},
  {"callsign": "K1ABC",  "count": 154}
]
```

**curl example:**
```bash
curl "http://localhost:8000/api/top/spotters?limit=5&hours=12&source=human"
```

---

### `GET /api/top/dx`

Returns the most-spotted DX stations by spot count over the last N hours.
Derived from raw spot rows.

**Query parameters:**

| Parameter | Type | Default | Validation |
|---|---|---|---|
| `source` | `human\|rbn\|both` | `both` | 422 on invalid value |
| `limit` | integer | `10` | 1–100 |
| `hours` | integer | `24` | 1–168 |

**Response shape:** `list[{"callsign": string, "count": integer}]`

- Sorted descending by count.

**Example response:**
```json
[
  {"callsign": "JA1XYZ",  "count": 87},
  {"callsign": "VK9XX",   "count": 63},
  {"callsign": "5B4AGN",  "count": 51}
]
```

**curl example:**
```bash
curl "http://localhost:8000/api/top/dx?limit=10&hours=24"
```

---

### `GET /api/top/rare-dx`

Returns the least-spotted DX callsigns over the last N hours (rarest first).
Derived from raw spot rows; mirrors `top/dx` but in ascending order, then by
callsign for ties.

**Query parameters:**

| Parameter | Type | Default | Validation |
|---|---|---|---|
| `source` | `human\|rbn\|both` | `both` | 422 on invalid value |
| `hours` | integer | `24` | 1–168 |
| `limit` | integer | `10` | 1–100 |

**Response shape:** `list[{"callsign": string, "count": integer}]`

- Sorted ascending by count, then alphabetically by callsign.

**Example response:**
```json
[
  {"callsign": "3B9FR",  "count": 1},
  {"callsign": "VU4PB",  "count": 1},
  {"callsign": "FT5XO",  "count": 2}
]
```

**curl example:**
```bash
curl "http://localhost:8000/api/top/rare-dx?hours=48&limit=10"
```

---

### `GET /api/callsign/{call}`

Returns activity detail for a single callsign over the last N hours. The
callsign path parameter is case-insensitive (normalised to upper case
internally). Fetches all spots in the window with no source filter, then
filters in Python for spots where `spotter == call` or `dx_call == call`.

**Path parameters:**

| Parameter | Description |
|---|---|
| `call` | Callsign to look up (case-insensitive) |

**Query parameters:**

| Parameter | Type | Default | Validation |
|---|---|---|---|
| `hours` | integer | `168` (7 days) | 1–720 |

**Response shape:**

```json
{
  "callsign": "JA1XYZ",
  "as_spotter": 42,
  "as_dx": 17,
  "recent": [
    {
      "ts": "2026-05-16T14:23:00+00:00",
      "spotter": "K1ABC",
      "dx_call": "JA1XYZ",
      "freq_khz": 14025.0,
      "band": "20m",
      "mode": "CW",
      "source": "human"
    }
  ]
}
```

- `callsign` — upper-cased input callsign.
- `as_spotter` — count of spots where this callsign was the spotter.
- `as_dx` — count of spots where this callsign was the DX station.
- `recent` — up to 25 most-recent matching spots, newest first. Each entry
  includes: `ts` (ISO 8601 string), `spotter`, `dx_call`, `freq_khz`, `band`,
  `mode`, `source`.

**curl example:**
```bash
curl "http://localhost:8000/api/callsign/JA1XYZ"
curl "http://localhost:8000/api/callsign/ja1xyz?hours=48"
```

---

### `GET /api/users`

Returns the current connected-users snapshot. Updated periodically by the
ingestor's `show/users` poll (default every 20 seconds).

**No query parameters.**

**Response shape:**

```json
{
  "count": 3,
  "users": [
    {"callsign": "G3XYZ",  "conn_type": "LOCAL"},
    {"callsign": "K1ABC",  "conn_type": "TELNET"},
    {"callsign": "W1AW",   "conn_type": "TELNET"}
  ]
}
```

- `count` — number of connected users.
- `users` — list of users sorted alphabetically by callsign; each entry has
  `callsign` and `conn_type` (as reported by DXSpider's `show/users`).

**curl example:**
```bash
curl http://localhost:8000/api/users
```

---

## WebSocket — `/ws`

Opens a persistent WebSocket connection and receives live events broadcast by
the ingestor.

**URL:** `ws://<host>/ws` (or `wss://` behind TLS)

### Event Envelope

Every message is a JSON object with a `type` field and a `data` field:

```json
{"type": "<event-type>", "data": { ... }}
```

### Event Types

#### `spot`

A new DX spot has been received and inserted.

```json
{
  "type": "spot",
  "data": {
    "kind": "spot",
    "spotter": "K1ABC",
    "dx_call": "JA1XYZ",
    "freq_khz": 14025.0,
    "band": "20m",
    "mode": "CW",
    "source": "human",
    "spotter_dxcc": "United States",
    "spotter_continent": "NA",
    "dx_dxcc": "Japan",
    "dx_continent": "AS",
    "comment": "CW 599",
    "when_z": "1423Z",
    "raw": "DX de K1ABC:     14025.0  JA1XYZ       CW 599        1423Z"
  }
}
```

#### `wwv`

A WWV propagation bulletin.

```json
{
  "type": "wwv",
  "data": {
    "kind": "wwv",
    "sfi": 140,
    "a_index": 7,
    "k_index": 2,
    "r": null,
    "origin": "AR0NL",
    "text": "SFI=140, A=7, K=2, No Storms",
    "raw": "WWV de AR0NL <18>:   SFI=140, A=7, K=2, No Storms"
  }
}
```

#### `wcy`

A WCY geomagnetic data bulletin. Same shape as `wwv` but `type: "wcy"`.

```json
{
  "type": "wcy",
  "data": {
    "kind": "wcy",
    "sfi": 140,
    "a_index": 10,
    "k_index": 2,
    "r": 120,
    "origin": "DK0WCY",
    "text": "K=2 expK=0 A=10 R=120 SFI=140",
    "raw": "WCY de DK0WCY-1 <12> : K=2 expK=0 A=10 R=120 SFI=140"
  }
}
```

#### `announce`

A DXSpider announcement (`To ALL de ...`).

```json
{
  "type": "announce",
  "data": {
    "kind": "announce",
    "sfi": null,
    "a_index": null,
    "k_index": null,
    "r": null,
    "origin": "G1ABC",
    "text": "Hello world",
    "raw": "To ALL de G1ABC: Hello world"
  }
}
```

#### `users`

A connected-users snapshot (pushed after each `show/users` poll, approximately
every 20 seconds).

```json
{
  "type": "users",
  "data": {
    "count": 3,
    "users": [
      {"callsign": "G3XYZ",  "conn_type": "LOCAL"},
      {"callsign": "K1ABC",  "conn_type": "TELNET"},
      {"callsign": "W1AW",   "conn_type": "TELNET"}
    ]
  }
}
```

### Connection Behaviour

- On connect, any events that were broadcast before the first client connected
  (pre-seeded in the hub's `pending` queue) are delivered first.
- Per-connection queue has a max size of 256. If a slow client falls behind,
  the oldest queued event is dropped to make room for the newest.
- The server does not send pings. Reconnection is the client's responsibility.

### Reconnect Strategy (JavaScript example)

The dashboard uses exponential back-off with a cap of 30 seconds:

```javascript
let wsBackoff = 1000; // ms
const WS_MAX_BACKOFF_MS = 30_000;

function connectWs() {
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
  const ws = new WebSocket(`${proto}//${location.host}/ws`);

  ws.onopen = () => { wsBackoff = 1000; };  // reset on success

  ws.onmessage = (ev) => {
    const msg = JSON.parse(ev.data);
    if (msg.type === 'spot') { /* handle spot */ }
    if (msg.type === 'users') { /* update user count */ }
  };

  ws.onclose = () => {
    setTimeout(() => {
      wsBackoff = Math.min(wsBackoff * 2, WS_MAX_BACKOFF_MS);
      connectWs();
    }, wsBackoff);
  };

  ws.onerror = () => ws.close();
}

connectWs();
```

---

## Error Responses

| HTTP Status | Cause |
|---|---|
| `422 Unprocessable Entity` | Invalid `source` value; invalid `by` value for `/api/geo`; `hours` or `limit` out of range |

FastAPI returns a JSON body describing the validation failure:

```json
{
  "detail": [
    {
      "type": "enum",
      "loc": ["query", "source"],
      "msg": "Input should be 'human', 'rbn' or 'both'",
      "input": "bad"
    }
  ]
}
```

The `/api/geo` `by` parameter is validated manually and returns a plain string
detail:

```json
{"detail": "'by' must be one of ['dx_continent', 'dx_dxcc', 'spotter_dxcc']"}
```
