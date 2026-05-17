"""Guards dxspider onboarding templates: full token substitution and the
'fresh render changes zero cluster behavior' invariant."""
import os
import pathlib
import re
import shlex
import subprocess

REPO = pathlib.Path(__file__).resolve().parents[2]
TEMPLATES = REPO / "dxspider" / "templates"
HELPER = REPO / "dxspider" / "dashboard-url.sh"
RENDER_HELPER = REPO / "dxspider" / "render-template.sh"

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


def _derive(overrides):
    """Run the real shell helper deterministically across platforms.

    The helper is fed via stdin (no path passed to bash). Test variables
    are injected as shell-quoted export/unset statements prepended to the
    piped script rather than via the process environment: the host bash
    may be WSL bash, which does not inherit the Windows environment block,
    so subprocess env= is unreliable. Injecting into the script makes the
    result independent of env propagation on every platform."""
    preamble = []
    for key in ("DOMAIN", "DASHBOARD_URL"):
        if key in overrides:
            preamble.append(f"export {key}={shlex.quote(overrides[key])}")
        else:
            preamble.append(f"unset {key}")
    script = (
        "\n".join(preamble)
        + "\n"
        + HELPER.read_text()
        + "\nderive_dashboard_url\n"
    )
    result = subprocess.run(
        ["bash", "-s"],
        input=script.encode("utf-8"),
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr.decode("utf-8", "replace")
    return result.stdout.decode("utf-8")


def test_dashboard_url_defaults_to_localhost():
    assert _derive({"DOMAIN": "localhost"}) == "http://localhost/"


def test_dashboard_url_unset_domain_defaults_localhost():
    assert _derive({}) == "http://localhost/"


def test_dashboard_url_derives_https_from_domain():
    assert _derive({"DOMAIN": "dx.example.com"}) == "https://dx.example.com/"


def test_dashboard_url_explicit_wins():
    assert (
        _derive({"DOMAIN": "dx.example.com", "DASHBOARD_URL": "http://x/"})
        == "http://x/"
    )


def _render(template_bytes: bytes, *pairs: str) -> bytes:
    """Run the REAL render-template.sh against an in-memory template.

    Mirrors _derive's robustness: the helper source is read as text and
    prepended to a generated bash script fed entirely via stdin as bytes.
    No Windows path is ever handed to bash and nothing relies on env=
    propagation (host bash may be WSL bash). The template bytes are written
    to a temp file by a tiny perl one-liner that reads them from a base64
    literal embedded in the script — this preserves the EXACT template
    bytes (including the precise trailing-newline count, control bytes and
    backslashes) with no heredoc/quoting artifacts. render_template writes
    to a temp file, and we cat that file back so stdout is the exact
    rendered bytes."""
    import base64

    b64 = base64.b64encode(template_bytes).decode("ascii")
    args = " ".join(shlex.quote(p) for p in pairs)
    script = (
        RENDER_HELPER.read_text()
        + "\n"
        + "set -eu\n"
        + 'rt_tmpl="$(mktemp)"\n'
        + 'rt_out="$(mktemp)"\n'
        + f"printf %s {shlex.quote(b64)} | perl -MMIME::Base64 -0777 -ne "
        + shlex.quote("print decode_base64($_)")
        + ' > "$rt_tmpl"\n'
        + f'render_template "$rt_tmpl" "$rt_out" {args}\n'
        + 'cat "$rt_out"\n'
        + 'rm -f "$rt_tmpl" "$rt_out"\n'
    )
    script_bytes = script.encode("utf-8")
    result = subprocess.run(
        ["bash", "-s"],
        input=script_bytes,
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr.decode("utf-8", "replace")
    return result.stdout


def test_render_byte_identity_normal_values():
    out = _render(
        b"X=__NODE_CALL__ Y=__DASHBOARD_URL__\n",
        "__NODE_CALL__", "N0CALL-2",
        "__DASHBOARD_URL__", "http://localhost/",
    )
    assert out == b"X=N0CALL-2 Y=http://localhost/\n"


def test_render_ampersand_literal():
    out = _render(
        b"url=__DASHBOARD_URL__\n",
        "__DASHBOARD_URL__", "https://h/?a=1&b=2",
    )
    assert b"https://h/?a=1&b=2" in out
    assert b"__DASHBOARD_URL__" not in out


def test_render_pipe_literal_exit_zero():
    # A value containing '|' aborted the old `sed s|...|...|` pipeline.
    out = _render(
        b"qth=__QTH__\n",
        "__QTH__", "a|b",
    )
    assert out == b"qth=a|b\n"


def test_render_backslash_literal():
    # Literal backslash-n must survive as backslash-n, not become a newline.
    out = _render(
        b"v=__NODE_CALL__\n",
        "__NODE_CALL__", "a\\nb",
    )
    assert out == b"v=a\\nb\n"


def test_render_dollar_at_literal():
    out = _render(
        b"v=__NODE_CALL__\n",
        "__NODE_CALL__", "de$x@y",
    )
    assert out == b"v=de$x@y\n"


def test_render_multi_token_sequential_order():
    out = _render(
        b"A=__ONE__ B=__TWO__\n",
        "__ONE__", "first",
        "__TWO__", "second",
    )
    assert out == b"A=first B=second\n"


def test_render_startup_zero_active_directive_invariant():
    """The new engine must not regress the safety invariant: rendering the
    real startup.tmpl with a metachar-laden NODE_CALL still yields only
    comment lines (no active directive injected via & or |)."""
    tmpl = (TEMPLATES / "startup.tmpl").read_bytes()
    out = _render(
        tmpl,
        "__NODE_CALL__", "N0&CALL|X-2",
    )
    text = out.decode("utf-8")
    for line in text.splitlines():
        stripped = line.strip()
        if stripped:
            assert stripped.startswith("#"), f"active directive: {line!r}"
