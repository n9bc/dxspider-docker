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
