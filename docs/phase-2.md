# Phase 2 Roadmap

Phase 2 items are **documented and config-gated but intentionally not active in
v1**. The v1 goal was a fully working *standalone* node with a rich stats
dashboard; peering and automated upstream feeds are deliberately deferred so a
node can be stood up and verified in isolation first.

## 1. Partner / inter-cluster peering

DX cluster nodes normally peer with each other over the DXSpider PC protocol
(same telnet port, 7300) so spots propagate across the network.

**What enabling involves:**

- Add `connect` scripts / partner definitions to the DXSpider config (in the
  `dxspider-config` volume or via additional templated blocks). The
  `DXVars.pm` template carries commented, env-gated placeholders for this.
- Exchange node callsigns and connection details with partner sysops
  (peering is a mutual arrangement on the real DX cluster network).
- Confirm your `NODE_CALL` is registered/recognised by partners.

**Stats impact:** none structural — peered spots flow through the same telnet
stream the ingestor already parses. Spot volume increases substantially.

## 2. Outbound RBN aggregator feed

The Reverse Beacon Network (RBN) provides automated skimmer spots. A node can
connect outbound to an RBN aggregator to ingest them.

**What enabling involves:**

- Add the RBN aggregator connection to the DXSpider config (env-gated block).

**Stats impact:** **none** — the parser and data model already classify every
spot as `source = human | rbn` (RBN detected from skimmer `-#` markers and the
RBN comment grammar), and every dashboard view and API endpoint already
supports the `human | rbn | both` filter. RBN data will simply start
appearing once the feed is enabled.

## 3. Native-format spot-file backfill

v1 first-boot backfill reads CSV/TSV `*.spots` files only. DXSpider's native
spot files are Perl `Data::Dumper` / binary dumps.

**What enabling involves:**

- A parser for the native DXSpider spot-file format in
  `stats-svc/app/backfill.py`, mapping records into the existing
  `SpotRecord` path (band/DXCC enrichment is already shared).
- Tests against captured native-format fixtures.

Until then, backfill is a safe no-op on native data and charts populate from
the live ingestor.

## 4. `show/users` stream multiplexing

v1 polls `show/users` over the **same** telnet stream as spots using a
~1-second collection window, which can briefly interleave with spot lines.

**What enabling involves:**

- Either a dedicated second telnet session for control queries, or proper
  in-band response framing/multiplexing so `show/users` output is
  deterministically separated from the spot feed.

## 5. Optional dashboard authentication

v1 deliberately serves **read-only public** statistics with no auth (YAGNI for
a public node). If a deployment needs access control:

**What enabling involves:**

- Front the dashboard route in the Caddyfile with Basic Auth or forward-auth,
  or add an auth layer in FastAPI. The sysop console (`/cluster`) is already
  Basic-Auth protected and is independent of this.

---

None of the above changes the v1 architecture; each is an additive,
independently-enableable step. See [architecture.md](architecture.md) for how
the pieces fit and [configuration.md](configuration.md) for the relevant
variables.
