# Telnet Operator Experience Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give telnet operators a branded first-connect MOTD, a documented opt-in node-defaults menu, and a live dashboard link, using the existing template-render pattern.

**Architecture:** Two new token-substituted templates (`motd.tmpl`, `startup.tmpl`) rendered by `entrypoint.sh` on first boot to persisted volume paths, `OVERWRITE_CONFIG`-aware, exactly mirroring DXVars/Listeners. A single-source-of-truth shell helper derives `DASHBOARD_URL` from `DOMAIN`. A focused pytest guards token substitution and the "fresh render changes zero behavior" invariant.

**Tech Stack:** Bash (entrypoint), `sed` token substitution, Docker Compose, pytest (existing stats-svc harness), DXSpider (pinned SHA `63d47180dc195e026bae23446eb9b798a0e923d6`, EA3CV mojo fork).

**Spec:** `docs/superpowers/specs/2026-05-16-telnet-operator-experience-design.md`

---

### Task 1: Verify DXSpider MOTD + startup paths against the pinned source

This is a blocking factual decision: where DXSpider reads the connect MOTD and the startup command script in the pinned `mojo` SHA, and whether those paths are on a persisted volume (`/spider/local` or `/spider/local_data`).

**Files:**
- Modify (record findings): `docs/superpowers/specs/2026-05-16-telnet-operator-experience-design.md` (append a "Verified Paths" subsection)

- [ ] **Step 1: Build the dxspider image (or reuse if already built)**

Run:
```bash
docker compose build dxspider
```
Expected: build succeeds; clones DXSpider at SHA `63d47180dc195e026bae23446eb9b798a0e923d6`.

- [ ] **Step 2: Inspect the cloned source for MOTD + startup conventions**

Run:
```bash
docker compose run --rm --entrypoint sh dxspider -c \
  'grep -rn "motd\|local_data/motd\|/scripts/startup\|local_cmd" /spider/perl/DXUser.pm /spider/perl/DXCommandmode.pm /spider/cmd 2>/dev/null | head -40; echo "---"; ls -d /spider/scripts /spider/local_cmd /spider/local_data 2>/dev/null'
```
Expected: output showing the file/path DXSpider opens for the connect MOTD and the startup script. Identify: (a) MOTD file path, (b) startup script path, (c) whether each is under `/spider/local` or `/spider/local_data`.

- [ ] **Step 3: Decide render targets and record the decision**

Append to the spec a "Verified Paths" subsection stating the exact MOTD path, startup-script path, the pinned SHA they were verified against, and the chosen render target for each.

Decision rule:
- If the canonical path is already under `/spider/local` or `/spider/local_data` → render directly there.
- If not → render to a persisted path and create a startup-time symlink from the canonical path to it (add the `ln -sfn` to entrypoint in Task 6), OR use a DXSpider-supported override variable if one exists. Document which.
- If the source inspection is genuinely ambiguous (two plausible paths, no clear winner) — this is the point to escalate via multi-agent debate rather than guessing; do not proceed to Task 2 until the target is unambiguous.

- [ ] **Step 4: Commit**

```bash
git add docs/superpowers/specs/2026-05-16-telnet-operator-experience-design.md
git commit -m "docs: record verified DXSpider MOTD/startup paths"
```

---

### Task 2: Create the MOTD template

**Files:**
- Create: `dxspider/templates/motd.tmpl`

- [ ] **Step 1: Write the template**

Create `dxspider/templates/motd.tmpl` with exactly:

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

- [ ] **Step 2: Commit**

```bash
git add dxspider/templates/motd.tmpl
git commit -m "feat: add telnet MOTD template"
```

---

### Task 3: Create the startup-defaults template

**Files:**
- Create: `dxspider/templates/startup.tmpl`

- [ ] **Step 1: Write the template**

Create `dxspider/templates/startup.tmpl` with exactly (every behavioral directive commented; nothing active):

```
# __NODE_CALL__ startup script — runs when cluster.pl starts.
# Rendered from startup.tmpl on first boot. Edit freely; preserved
# across restarts (volume-mounted). Uncomment a line to enable it.
#
# NOTHING below is active by default. Each line is a documented,
# opt-in node default. Verify the directive is valid on your DXSpider
# version before relying on it.

# set/dx mode 1            # richer SH/DX output formatting for users
# set/dxgrid               # append grid square to DX announcements
# unset/echo               # do not echo user commands back to them

# --- Output volume guards (uncomment if your node feels noisy) ---
# set/obscount 5           # spot obscount threshold before suppression
```

> Note for executor: in Task 1 you confirmed which `set/*` directives
> are valid on the pinned SHA. Remove any line whose directive does not
> exist in that version; do NOT add new active lines. The invariant
> tested in Task 4 is that zero lines are uncommented.

- [ ] **Step 2: Commit**

```bash
git add dxspider/templates/startup.tmpl
git commit -m "feat: add opt-in node-defaults startup template"
```

---

### Task 4: Create the DASHBOARD_URL derivation helper (single source of truth)

**Files:**
- Create: `dxspider/dashboard-url.sh`

- [ ] **Step 1: Write the helper**

Create `dxspider/dashboard-url.sh` with exactly:

```bash
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
```

- [ ] **Step 2: Commit**

```bash
git add dxspider/dashboard-url.sh
git commit -m "feat: add dashboard-url derivation helper"
```

---

### Task 5: Write the failing template-rendering test

**Files:**
- Create: `stats-svc/tests/test_dxspider_templates.py`

(Placed in the existing stats-svc pytest harness deliberately — no new
test framework is introduced; the test only uses stdlib + repo files.)

- [ ] **Step 1: Write the failing test**

Create `stats-svc/tests/test_dxspider_templates.py` with exactly:

```python
"""Guards dxspider onboarding templates: full token substitution and the
'fresh render changes zero cluster behavior' invariant."""
import pathlib
import re
import subprocess

REPO = pathlib.Path(__file__).resolve().parents[2]
TEMPLATES = REPO / "dxspider" / "templates"
HELPER = REPO / "dxspider" / "dashboard-url.sh"

TOKEN_MAP = {
    "__NODE_CALL__": "N9BC-2",
    "__SYSOP_CALL__": "N9BC",
    "__SYSOP_NAME__": "Test Sysop",
    "__QTH__": "Testville",
    "__LOCATOR__": "EN61bx",
    "__EMAIL__": "sysop@example.com",
    "__DASHBOARD_URL__": "https://dx.example.com/",
}


def render(name: str) -> str:
    text = (TEMPLATES / name).read_text()
    for token, value in TOKEN_MAP.items():
        text = text.replace(token, value)
    return text


def test_motd_has_no_unsubstituted_tokens():
    out = render("motd.tmpl")
    assert not re.search(r"__[A-Z_]+__", out), out


def test_startup_has_no_unsubstituted_tokens():
    out = render("startup.tmpl")
    assert not re.search(r"__[A-Z_]+__", out), out


def test_motd_contains_identity_and_dashboard():
    out = render("motd.tmpl")
    assert "N9BC-2" in out
    assert "https://dx.example.com/" in out


def test_startup_has_zero_active_directives():
    """The safety invariant: every non-blank line is a comment."""
    out = render("startup.tmpl")
    for line in out.splitlines():
        stripped = line.strip()
        if stripped:
            assert stripped.startswith("#"), f"active directive: {line!r}"


def _derive(env):
    script = (
        f". {HELPER.as_posix()}; derive_dashboard_url"
    )
    return subprocess.run(
        ["bash", "-c", script], capture_output=True, text=True, env=env
    ).stdout


def test_dashboard_url_defaults_to_localhost():
    assert _derive({"DOMAIN": "localhost"}) == "http://localhost/"


def test_dashboard_url_derives_https_from_domain():
    assert _derive({"DOMAIN": "dx.example.com"}) == "https://dx.example.com/"


def test_dashboard_url_explicit_wins():
    assert (
        _derive({"DOMAIN": "dx.example.com", "DASHBOARD_URL": "http://x/"})
        == "http://x/"
    )
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd stats-svc && python -m pytest tests/test_dxspider_templates.py -v`
Expected: collection succeeds; `test_motd_*` / `test_startup_*` FAIL with `FileNotFoundError` only if Task 2/3 skipped — otherwise token/derivation tests drive the work. (If Tasks 2–4 already done, these should mostly pass; the meaningful failures appear once entrypoint wiring in Task 6 is exercised by Task 8's smoke test.)

- [ ] **Step 3: Commit**

```bash
git add stats-svc/tests/test_dxspider_templates.py
git commit -m "test: dxspider template substitution + zero-active-directive invariant"
```

---

### Task 6: Wire the render blocks + DASHBOARD_URL into entrypoint.sh

**Files:**
- Modify: `dxspider/entrypoint.sh` (add after the Listeners.pm block, before "Ensure runtime directories"; section numbers shift accordingly)
- Modify: `dxspider/Dockerfile` (COPY the two new templates + the helper)

- [ ] **Step 1: Copy new files into the image**

In `dxspider/Dockerfile`, after the existing template COPY lines
(`COPY templates/Listeners.pm.tmpl ...`), add:

```dockerfile
COPY templates/motd.tmpl    /spider/templates/motd.tmpl
COPY templates/startup.tmpl /spider/templates/startup.tmpl
COPY dashboard-url.sh       /spider/dashboard-url.sh
```

- [ ] **Step 2: Add env defaults + URL derivation to entrypoint.sh**

In `dxspider/entrypoint.sh` section 1 (env resolution), after the
`OVERWRITE_CONFIG=...` line, add:

```bash
DOMAIN="${DOMAIN:-localhost}"
# DASHBOARD_URL: explicit wins; else derived from DOMAIN by the helper.
# shellcheck source=/dev/null
. /spider/dashboard-url.sh
DASHBOARD_URL="$(derive_dashboard_url)"
echo "[entrypoint] DASHBOARD_URL=${DASHBOARD_URL}"
```

- [ ] **Step 3: Add the two render blocks**

In `dxspider/entrypoint.sh`, immediately after the Listeners.pm render
block (current section 3) and before "4. Ensure runtime directories",
insert (use the verified paths from Task 1 — `MOTD_TARGET` /
`STARTUP_TARGET` set to the persisted paths recorded there):

```bash
# ---------------------------------------------------------------------------
# 3b. Render MOTD (first run / OVERWRITE_CONFIG=yes only)
# ---------------------------------------------------------------------------
MOTD_TARGET="<VERIFIED_MOTD_PATH_FROM_TASK_1>"
MOTD_TMPL="/spider/templates/motd.tmpl"
if [[ ! -f "${MOTD_TARGET}" || "${OVERWRITE_CONFIG}" == "yes" ]]; then
    echo "[entrypoint] Writing ${MOTD_TARGET} from template..."
    sed \
        -e "s|__NODE_CALL__|${NODE_CALL}|g" \
        -e "s|__SYSOP_CALL__|${SYSOP_CALL}|g" \
        -e "s|__SYSOP_NAME__|${SYSOP_NAME}|g" \
        -e "s|__LOCATOR__|${LOCATOR}|g" \
        -e "s|__QTH__|${NODE_QTH}|g" \
        -e "s|__EMAIL__|${SYSOP_EMAIL}|g" \
        -e "s|__DASHBOARD_URL__|${DASHBOARD_URL}|g" \
        "${MOTD_TMPL}" > "${MOTD_TARGET}"
    echo "[entrypoint] MOTD written."
else
    echo "[entrypoint] ${MOTD_TARGET} exists and OVERWRITE_CONFIG!=yes — preserving operator config."
fi

# ---------------------------------------------------------------------------
# 3c. Render startup script (first run / OVERWRITE_CONFIG=yes only)
# ---------------------------------------------------------------------------
STARTUP_TARGET="<VERIFIED_STARTUP_PATH_FROM_TASK_1>"
STARTUP_TMPL="/spider/templates/startup.tmpl"
if [[ ! -f "${STARTUP_TARGET}" || "${OVERWRITE_CONFIG}" == "yes" ]]; then
    echo "[entrypoint] Writing ${STARTUP_TARGET} from template..."
    sed -e "s|__NODE_CALL__|${NODE_CALL}|g" \
        "${STARTUP_TMPL}" > "${STARTUP_TARGET}"
    echo "[entrypoint] startup script written."
else
    echo "[entrypoint] ${STARTUP_TARGET} exists and OVERWRITE_CONFIG!=yes — preserving operator config."
fi
```

If Task 1 decided a symlink is required (canonical path not on a
persisted volume), also add directly below, after the mkdir block in
section 4:

```bash
ln -sfn "<PERSISTED_PATH>" "<CANONICAL_PATH>"
```

- [ ] **Step 4: Add the new directories to the mkdir block if needed**

If the verified MOTD/startup parent dirs are not already created in
section 4's `mkdir -p`, add them to that list, then keep the existing
`chown -R sysop:spider /spider/local /spider/local_data`.

- [ ] **Step 5: Commit**

```bash
git add dxspider/entrypoint.sh dxspider/Dockerfile
git commit -m "feat: render MOTD + startup templates in entrypoint"
```

---

### Task 7: Pass DOMAIN/DASHBOARD_URL into the dxspider service

**Files:**
- Modify: `docker-compose.yml` (dxspider `environment:` block, lines ~51–62)

- [ ] **Step 1: Add the env vars**

In `docker-compose.yml`, in the `dxspider:` service `environment:` map,
after the `OVERWRITE_CONFIG:` line, add:

```yaml
      DOMAIN:           ${DOMAIN:-localhost}
      DASHBOARD_URL:    ${DASHBOARD_URL:-}
```

- [ ] **Step 2: Commit**

```bash
git add docker-compose.yml
git commit -m "feat: pass DOMAIN/DASHBOARD_URL to dxspider service"
```

---

### Task 8: Run the test suite and a container smoke test

**Files:** none (verification)

- [ ] **Step 1: Run the new test module**

Run: `cd stats-svc && python -m pytest tests/test_dxspider_templates.py -v`
Expected: all 7 tests PASS.

- [ ] **Step 2: Run the full suite for regressions**

Run: `cd stats-svc && python -m pytest -q`
Expected: previously-passing tests still pass (171 + 7 new).

- [ ] **Step 3: Container smoke test (Docker approved by user)**

Run:
```bash
docker compose up -d --build dxspider
sleep 20
docker compose exec dxspider sh -c 'cat "<VERIFIED_MOTD_PATH_FROM_TASK_1>"'
docker compose exec dxspider sh -c 'cat "<VERIFIED_STARTUP_PATH_FROM_TASK_1>"'
printf 'N9BC\n' | nc -w 3 localhost 7300 | head -30
```
Expected: rendered MOTD shows substituted call/QTH/dashboard URL and no
`__TOKEN__`; startup file has only commented lines; telnet connect shows
the MOTD banner.

- [ ] **Step 4: Tear down**

```bash
docker compose down
```

- [ ] **Step 5: Commit (only if Step 3 required template/entrypoint tweaks)**

```bash
git add -A && git commit -m "fix: smoke-test corrections for telnet onboarding"
```

---

### Task 9: Documentation + .env.example

**Files:**
- Modify: `.env.example`
- Modify: `docs/dxspider.md`

- [ ] **Step 1: Add DASHBOARD_URL to .env.example**

In `.env.example`, after the `OVERWRITE_CONFIG` section, add:

```
# ---------------------------------------------------------------------------
# Telnet onboarding — dashboard link shown in the connect MOTD.
# Leave DASHBOARD_URL blank to auto-derive from DOMAIN:
#   DOMAIN=localhost      -> http://localhost/
#   DOMAIN=dx.example.com -> https://dx.example.com/
# Set explicitly only to override (e.g. a non-root path or separate host).
# ---------------------------------------------------------------------------
DASHBOARD_URL=
```

- [ ] **Step 2: Document MOTD + startup defaults in docs/dxspider.md**

Add a "Telnet operator onboarding" section to `docs/dxspider.md`
covering: the rendered MOTD (path from Task 1, what tokens come from
which env vars), that the startup script ships fully commented and is an
opt-in menu, the `OVERWRITE_CONFIG` interaction, and how to customize by
editing the volume-mounted files.

- [ ] **Step 3: Commit**

```bash
git add .env.example docs/dxspider.md
git commit -m "docs: document telnet onboarding MOTD + startup defaults"
```

---

### Task 10 (STRETCH): Persistent dashboard command

Only attempt if Task 1's source inspection showed a clear, low-risk
`local_cmd` custom-command convention on the pinned SHA.

**Files:**
- Create: `dxspider/templates/cmd_dashboard.tmpl`
- Modify: `dxspider/entrypoint.sh` (render block), `dxspider/Dockerfile` (COPY)

- [ ] **Step 1: Confirm the custom-command convention**

Run:
```bash
docker compose run --rm --entrypoint sh dxspider -c \
  'ls /spider/local_cmd 2>/dev/null; grep -rn "local_cmd" /spider/perl/*.pm | head'
```
Expected: a clear directory + file-naming convention for a user command.
If unclear → stop; drop the stretch goal, note it in the spec.

- [ ] **Step 2: Create the command template**

Create `dxspider/templates/cmd_dashboard.tmpl` implementing a
`dashboard` (or `sh/dashboard`) command that prints:
`Live stats dashboard: __DASHBOARD_URL__` — using the exact command
signature the convention from Step 1 requires.

- [ ] **Step 3: Render it in entrypoint + COPY in Dockerfile**

Mirror the Task 6 render block (substitute `__DASHBOARD_URL__` and
`__NODE_CALL__`) targeting the verified `local_cmd` path; add the
`COPY templates/cmd_dashboard.tmpl ...` line to the Dockerfile.

- [ ] **Step 4: Smoke test the command**

```bash
docker compose up -d --build dxspider && sleep 20
printf 'N9BC\ndashboard\nbye\n' | nc -w 5 localhost 7300 | tail -10
docker compose down
```
Expected: the dashboard URL prints in the telnet session.

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat: persistent dashboard command (stretch)"
```

---

## Self-Review

**Spec coverage:**
- First-connect impression → Task 2 (MOTD), Task 8 (smoke).
- Sensible defaults → Task 3 (commented startup), Task 5 zero-active-directive test.
- Command discoverability → Task 2 cheat-sheet, Task 10 (stretch command).
- Dashboard tie-in → Task 4 (helper), Task 6/7 (wiring), Task 9 (.env doc).
- Match existing render pattern → Task 6 (same sed/guard idiom).
- Persisted-path constraint → Task 1 (verification + symlink fallback).
- Testing strategy → Task 5/8.
- Risks (path drift, stretch coupling) → Task 1, Task 10 gating.

All spec sections map to tasks. No gaps.

**Placeholder scan:** The only intentional placeholders are
`<VERIFIED_*_PATH_FROM_TASK_1>` — these are *outputs of Task 1*, a
required investigation task with a defined procedure and escalation
rule, not unspecified work. Acceptable by design.

**Type/name consistency:** `derive_dashboard_url` defined in Task 4,
sourced identically in Task 6 and the test in Task 5. `DASHBOARD_URL`,
`MOTD_TARGET`, `STARTUP_TARGET` used consistently. Token set identical
across Tasks 2, 5, 6.
