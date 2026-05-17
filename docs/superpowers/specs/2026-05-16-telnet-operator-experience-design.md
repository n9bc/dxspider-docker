# Telnet Operator Experience — Design

**Date:** 2026-05-16
**Status:** Approved (brainstorming)
**Scope:** A single implementation plan.

## Problem

A ham connecting to this node via telnet on port 7300 currently gets the
bare stock DXSpider default experience: no node identity, no orientation,
no command guidance, and no connection to the live stats dashboard this
stack provides. The four selected pain points:

1. **First-connect impression** — stock boilerplate, no identity/orientation.
2. **Sensible defaults** — no documented, opt-in node-default guidance.
3. **Command discoverability** — users don't know what to type.
4. **Dashboard tie-in** — telnet and web feel like separate worlds.

## Goals

- Give telnet operators a clear, branded, useful first screen.
- Surface the live stats dashboard URL inside the telnet session.
- Provide a conservative, fully-documented, opt-in node-defaults menu
  that changes **zero** behavior on a fresh render.
- Match the existing template-render configuration pattern exactly
  (DXVars.pm / Listeners.pm): tokens substituted at first boot,
  volume-persisted, operator-editable, `OVERWRITE_CONFIG`-aware.

## Non-Goals

- No changes to cluster behavior out of the box.
- No new services or volumes.
- No DXSpider source patching.
- Container/entrypoint integration remains operator-verified on first
  `docker compose up` (same as the rest of the stack).

## Chosen Approach

**Approach A** (templated onboarding package) as core, **Approach C**
(one persistent custom command) as a stretch goal contingent on clean
verification of the DXSpider `local_cmd` convention against the pinned
source.

## Architecture & Components

Follows the existing template-render pattern. No new services/volumes.

**New files — `dxspider/templates/`:**

- `motd.tmpl` — message-of-the-day shown on connect. Token-substituted
  node identity + orientation + dashboard URL + command cheat-sheet.
- `startup.tmpl` — DXSpider startup command script. Conservative
  defaults, every behavioral line commented out with a one-line
  rationale. A documented opt-in menu, not active configuration.

**Changed files:**

- `dxspider/entrypoint.sh` — two additional render blocks (sed token
  substitution, first-run / `OVERWRITE_CONFIG` guard) writing to the
  verified persisted paths; resolve a new `DASHBOARD_URL` env.
- `docker-compose.yml` — pass `DOMAIN` / `DASHBOARD_URL` into the
  `dxspider` service environment.
- `.env.example` — document the new `DASHBOARD_URL` knob.
- `docs/dxspider.md` — document MOTD, startup defaults, customization
  and override behavior.

**Stretch (Approach C):** one custom DXSpider local command surfacing
the dashboard URL, **only if** the `local_cmd` convention verifies
cleanly against the pinned DXSpider SHA. Otherwise dropped without
affecting core scope.

**Key constraint:** rendered files must land on `/spider/local` or
`/spider/local_data` (the only persisted volumes). The exact
DXSpider-expected paths for the MOTD and the startup script are verified
against the pinned DXSpider SHA during implementation. If a canonical
path is not on a persisted volume, the render target adapts (symlink or
a supported override mechanism) rather than silently losing operator
edits on container rebuild. This verification is an explicit, blocking
implementation step.

## Render Data Flow

In `entrypoint.sh`, after the existing DXVars/Listeners render blocks:

1. Resolve `DASHBOARD_URL`. If unset, derive from `DOMAIN`:
   `https://${DOMAIN}/`, except `DOMAIN=localhost` →
   `http://localhost/`. An explicit `DASHBOARD_URL` always wins.
2. For each of `motd.tmpl`, `startup.tmpl`: if the target is absent
   **or** `OVERWRITE_CONFIG=yes`, render via `sed` token substitution
   to the verified persisted path; otherwise log the
   "preserving operator config" message — identical guard semantics to
   the existing blocks.
3. Tokens: `__NODE_CALL__`, `__SYSOP_CALL__`, `__SYSOP_NAME__`,
   `__QTH__`, `__LOCATOR__`, `__EMAIL__`, `__DASHBOARD_URL__`. Same
   single-quote / `|`-delimiter safety rules already documented in
   `DXVars.pm.tmpl`.

## Error Handling

- Render uses the same `sed` approach already trusted in the script;
  `set -euo pipefail` aborts on render failure before `cluster.pl`
  starts — consistent with current behavior.
- Missing template file in image → hard fail at boot with a clear
  `[entrypoint]` message (treated like the existing required templates).
- A bad `DASHBOARD_URL` is non-fatal cosmetic text in the MOTD; no
  validation gate (do not block cluster start over a banner).
- Startup-script defaults are all inert (commented) on a fresh render,
  so a first boot cannot change cluster behavior unexpectedly.

## MOTD Content

Plain text, ~24 lines so it fits a standard terminal without scrolling
the prompt away. Tokens shown unsubstituted:

```
=================================================================
  __NODE_CALL__  —  DX Cluster Node
  Sysop: __SYSOP_NAME__ (__SYSOP_CALL__)   QTH: __QTH__   Grid: __LOCATOR__
=================================================================

  Welcome. You are connected to a DXSpider node.

  Live stats dashboard:  __DASHBOARD_URL__
    (band/mode activity, leaderboards, rare DX, per-call drill-down,
     updated in real time from this node's spot stream)

  Getting started:
    DX <freq> <call> <comment>   post a spot
    SH/DX                        last spots         SH/DX 20   last 20
    SH/DX <call>                 spots for a call   SH/DX/30m  by band
    SET/NAME <your name>         set your name
    SET/QTH <your qth>           set your location
    SH/USERS                     who's connected    BYE        disconnect

  Full command list:  HELP        Node info:  SH/CLUSTER
  Sysop contact:  __EMAIL__
=================================================================
```

Static aside from the seven identity/URL tokens.

## Startup Defaults Content

`startup.tmpl` renders to the DXSpider startup script path. Every
behavioral directive ships commented out with a one-line rationale; the
file is a documented, ready-to-opt-in menu.

```
# __NODE_CALL__ startup script — runs when cluster.pl starts.
# Rendered from startup.tmpl on first boot. Edit freely; preserved
# across restarts. Uncomment a line to enable that default.

# set/dx mode 1            # richer SH/DX formatting for users
# set/dxgrid               # append grid square to DX announcements
# unset/echo               # don't echo user commands back to them

# --- Output volume guards (uncomment if your node feels noisy) ---
# set/obscount 5           # spot obscount threshold
# (each option carries a short why-comment; nothing enabled by default)
```

The exact directive list is finalized against the pinned DXSpider SHA
during implementation — only directives valid in that version ship,
each verified. Invariant: **a fresh render changes zero cluster
behavior**.

## Testing

A small focused pytest module, consistent with existing test philosophy
(repo already runs pytest; no shell test harness, and none is warranted):

- Render each template by applying the same `sed` token map the
  entrypoint uses; assert every `__TOKEN__` is substituted and none
  leak through.
- Assert the rendered `startup` script contains **zero uncommented
  behavioral directives** (the "fresh render changes nothing" safety
  invariant — the regression test that matters most).
- Assert the MOTD contains the substituted node call and dashboard URL.
- Exercise the `DASHBOARD_URL`-from-`DOMAIN` derivation (extract to a
  tiny shell function the test can call, or mirror it in the test, with
  the entrypoint as the single source of truth).

Entrypoint/container integration remains operator-verified on first
`docker compose up`, same as the rest of the stack today.

## Risks

- **DXSpider path/convention drift** — MOTD/startup/`local_cmd` paths
  vary across DXSpider versions. Mitigation: explicit blocking
  verification step against the pinned SHA before finalizing render
  targets and directive lists.
- **Stretch command coupling** — Approach C depends most heavily on
  DXSpider internals. Mitigation: it is a stretch goal, droppable
  without affecting core scope.

## Verified Paths

Source verification performed against the pinned DXSpider source baked
into the image (Task 1, blocking factual decision).

**Pinned source:** EA3CV fork `mojo` branch, SHA
`63d47180dc195e026bae23446eb9b798a0e923d6`
(`https://github.com/EA3CV/dx-spider.git`), as cloned in
`dxspider/Dockerfile`.

**Docker VOLUME paths (persisted):** `/spider/local` and
`/spider/local_data` only — `dxspider/Dockerfile:143`
(`VOLUME ["/spider/local", "/spider/local_data"]`).
`$main::root` is `/spider` (`perl/cluster.pl:60`).

### MOTD (connect message of the day)

**Canonical path: `/spider/local_data/motd` — ALREADY PERSISTED.**

Derivation (read from source, not inferred):

- `perl/SysVar.pm:34` — `$motd = "motd"` (bare filename, no path).
- `perl/cluster.pl:635` — `localdata_mv($motd)` migrates a legacy
  `/spider/data/motd` into `/spider/local_data/motd` if present
  (`perl/DXUtil.pm:574-583`).
- `perl/cluster.pl:636` — `$motd = localdata($motd)` reassigns
  `$main::motd` to an **absolute** path. `localdata()`
  (`perl/DXUtil.pm:554-572`) sets `$lfn = "$main::local_data/$ifn"`
  (= `/spider/local_data/motd`) and `$dfn = "$main::data/$ifn"`; it
  returns `$lfn` unless a *newer* `$dfn` exists. The pinned image
  ships **no** `/spider/data/motd` (verified: `/spider/data` contains
  only `bands.pl`, `cty.dat`, `prefix_data.pl`, `wpxloc.raw`), so the
  function deterministically returns `/spider/local_data/motd`.
- `perl/DXCommandmode.pm:1350-1369` — `send_motd()` is called per
  connection (`:173`). It probes language/registration variants
  (`${main::motd}_nor_<lang>`, `${main::motd}_<lang>`, `_ax25`) and
  falls back to the base `$main::motd`; line `:1360`
  `$motd = $main::motd unless $motd && -e $motd;` then `:1368`
  `$self->send_file($motd) if -e $motd;` opens that absolute path.

Because `$main::motd` is rooted at `$main::local_data`
(`perl/SysVar.pm:19` / `cluster.pl:76`, `= "$root/local_data"`), every
candidate the connect path opens lives under the persisted
`/spider/local_data` volume.

**Render-target decision:** Render the MOTD **directly** to
`/spider/local_data/motd`. It is on a persisted volume — **no symlink
required**. Operator edits survive container rebuilds.

### Startup script (run by cluster.pl at boot)

**Canonical path: `/spider/scripts/startup` — NOT persisted.**

Derivation:

- `perl/cluster.pl:742-743` — `# read startup script` /
  `my $script = new Script "startup";` then `:744`
  `$script->run($main::me) if $script;`.
- `perl/Script.pm:20` — `my $base = "$main::root/scripts";`.
- `perl/Script.pm:29-47` — `new()`: `$mybase = shift || $base;`
  `my $fn = "$mybase/$script";` → opens
  `/spider/scripts/startup` (no second arg passed from `cluster.pl`,
  so `$base` is used). With `$main::root = /spider`
  (`cluster.pl:60`), the absolute path is **`/spider/scripts/startup`**.
- `/spider/scripts` is **not** a VOLUME (only `/spider/local` and
  `/spider/local_data` are). Verified: the dir ships only
  `.gitignore` (contents: `*`, `!.gitignore`, `*.issue`) and is
  otherwise empty, so a file written there is lost on image rebuild /
  container recreate.
- No usable override variable exists: `$base` is hardcoded to
  `$main::root/scripts` in `Script.pm:20`; only `DXSPIDER_ROOT`
  (`cluster.pl:61`) could change it, but that relocates the entire
  DXSpider tree — not a viable scoped override.

**Render-target decision:** Render the startup script to a persisted
path **`/spider/local_data/startup`**, and at container startup create
a symlink so DXSpider's hardcoded canonical path resolves to the
persisted file:

```sh
ln -sfn /spider/local_data/startup /spider/scripts/startup
```

(`/spider/scripts` itself is recreated from the image each rebuild, so
the entrypoint must (re)create this symlink every start, before
`cluster.pl` runs.)

### local_cmd convention (informational, for stretch Task 10)

Custom/local commands live in **`/spider/local_cmd`**
(`perl/SysVar.pm:28` and `perl/cluster.pl:73,81`,
`$localcmd = "$root/local_cmd"`; auto-created at `cluster.pl:73`
`mkdir "$root/local_cmd", 02774 unless -d ...`). A custom command is a
`.pl` file mirroring the built-in `cmd/` tree (e.g.
`/spider/local_cmd/show/<name>.pl`); `local_cmd` is searched **before**
`cmd` (`perl/DXCommandmode.pm:545`,
`search($main::localcmd, $cmd, "pl")`). Note `/spider/local_cmd` is
**not** a VOLUME, so a persisted stretch command will need the same
render-to-`local_data` + symlink treatment as the startup script.
