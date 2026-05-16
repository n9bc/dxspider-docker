"""Telnet stream line parsers for DXSpider cluster output.

Public API
----------
parse_line(line: str) -> SpotRecord | InfoRecord | None
    Dispatch a single raw telnet line to a typed record.  Returns None for
    unparseable / unrecognised lines.

parse_users_block(text: str) -> list[ConnectedUser]
    Parse the multi-line output of the DXSpider ``show/users`` command into a
    list of ConnectedUser records.
"""

import re
from dataclasses import dataclass, field

from app.bands import band_for_khz, mode_for_khz_comment
from app.dxcc import resolve

__all__ = [
    "SpotRecord",
    "InfoRecord",
    "ConnectedUser",
    "parse_line",
    "parse_users_block",
]

# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class SpotRecord:
    kind: str = "spot"
    spotter: str = ""
    dx_call: str = ""
    freq_khz: float = 0.0
    band: "str | None" = None
    mode: "str | None" = None
    source: str = "human"          # "human" | "rbn"
    spotter_dxcc: "str | None" = None
    spotter_continent: "str | None" = None
    dx_dxcc: "str | None" = None
    dx_continent: "str | None" = None
    comment: str = ""
    when_z: "str | None" = None
    raw: str = ""


@dataclass
class InfoRecord:
    kind: str = ""                  # "wwv" | "wcy" | "announce"
    sfi: "int | None" = None
    a_index: "int | None" = None
    k_index: "int | None" = None
    r: "int | None" = None
    origin: "str | None" = None
    text: "str | None" = None
    raw: str = ""


@dataclass
class ConnectedUser:
    callsign: str = ""
    conn_type: str = ""


# ---------------------------------------------------------------------------
# Regex patterns
# ---------------------------------------------------------------------------

# DX spot: "DX de SPOTTER:   FREQ   DXCALL   comment   HHMMz"
# Spotter may have -# (RBN) or -N (SSID); freq has decimal point.
_RE_DX = re.compile(
    r"^DX\s+de\s+"
    r"(?P<spotter>[A-Z0-9/]+-[#\d]+|[A-Z0-9/]+)"   # spotter (with or without suffix)
    r"\s*:\s*"
    r"(?P<freq>\d+(?:\.\d+)?)"                       # frequency in kHz
    r"\s+"
    r"(?P<dxcall>[A-Z0-9/]+)"                        # DX callsign
    r"\s+"
    r"(?P<rest>.+?)"                                  # comment + optional time
    r"\s*$",
    re.IGNORECASE,
)

# Trailing time stamp: 4 digits followed by Z (optionally preceded by whitespace)
_RE_TIME_Z = re.compile(r"\b(\d{4}Z)\s*$", re.IGNORECASE)

# RBN/skimmer detection patterns in comment
_RE_RBN_DB  = re.compile(r"\b\d+\s*dB\b",  re.IGNORECASE)
_RE_RBN_WPM = re.compile(r"\b\d+\s*WPM\b", re.IGNORECASE)

# WWV: "WWV de ORIGIN <num>:  SFI=N, A=N, K=N, ..."
_RE_WWV = re.compile(
    r"^WWV\s+de\s+"
    r"(?P<origin>[A-Z0-9/-]+)"
    r"\s*<\d+>\s*:\s*"
    r"(?P<body>.+)$",
    re.IGNORECASE,
)

# WCY: "WCY de ORIGIN <num> : K=N expK=N A=N R=N SFI=N ..."
_RE_WCY = re.compile(
    r"^WCY\s+de\s+"
    r"(?P<origin>[A-Z0-9/-]+)"
    r"(?:\s*<\d+>)?\s*:\s*"
    r"(?P<body>.+)$",
    re.IGNORECASE,
)

# Announce: "To ALL de ORIGIN: text" or "To LOCAL de ORIGIN: text"
_RE_ANN = re.compile(
    r"^To\s+(?:ALL|LOCAL|DX|DXCC|[A-Z]+)\s+de\s+"
    r"(?P<origin>[A-Z0-9/-]+)\s*:\s*"
    r"(?P<text>.+)$",
    re.IGNORECASE,
)

# Key=value extractor for WWV / WCY bodies
_RE_KV = re.compile(r"([A-Za-z_]+)\s*=\s*(-?\d+)")

# Valid-looking callsign characters for users-block scanner
# A callsign line must have a plausible first token: 2–7 uppercase letters/digits
_RE_CALLSIGN = re.compile(r"^[A-Z][A-Z0-9]{1,6}(?:-\d+)?$", re.IGNORECASE)

# Lines to skip in users block: separators, empty, comment, header keywords
_RE_SKIP = re.compile(
    r"^(?:#|=|-|show/users|callsign|\s*$)",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _strip_rbn_suffix(raw_spotter: str) -> str:
    """Return the base callsign, removing -# RBN marker or numeric SSID like -1."""
    return re.sub(r"-[#\d]+$", "", raw_spotter.upper())


def _is_rbn(raw_spotter: str, comment: str) -> bool:
    """True if the spot originates from an RBN/skimmer node."""
    if raw_spotter.upper().endswith("-#"):
        return True
    if _RE_RBN_DB.search(comment) and _RE_RBN_WPM.search(comment):
        return True
    return False


def _extract_kv(body: str) -> dict[str, int]:
    """Return a dict of all NAME=integer pairs found in *body*."""
    result: dict[str, int] = {}
    for m in _RE_KV.finditer(body):
        result[m.group(1).upper()] = int(m.group(2))
    return result


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def parse_line(line: str) -> "SpotRecord | InfoRecord | None":
    """Parse a single raw telnet line from DXSpider into a typed record.

    Returns None for blank lines or lines that do not match any known format.
    Never raises — catches all parsing exceptions and returns None.
    """
    line = line.strip()
    if not line:
        return None

    try:
        # ---- DX spot -------------------------------------------------------
        m = _RE_DX.match(line)
        if m:
            raw_spotter = m.group("spotter")
            freq_khz    = float(m.group("freq"))
            dx_call     = m.group("dxcall").upper()
            rest        = m.group("rest").strip()

            # Split trailing time token from comment
            tm = _RE_TIME_Z.search(rest)
            when_z  = tm.group(1).upper() if tm else None
            comment = rest[: tm.start()].strip() if tm else rest

            spotter  = _strip_rbn_suffix(raw_spotter)
            source   = "rbn" if _is_rbn(raw_spotter, comment) else "human"

            # DXCC enrichment
            sp_dxcc  = resolve(spotter)
            dx_dxcc  = resolve(dx_call)

            return SpotRecord(
                kind              = "spot",
                spotter           = spotter,
                dx_call           = dx_call,
                freq_khz          = freq_khz,
                band              = band_for_khz(freq_khz),
                mode              = mode_for_khz_comment(freq_khz, comment),
                source            = source,
                spotter_dxcc      = sp_dxcc.entity,
                spotter_continent = sp_dxcc.continent,
                dx_dxcc           = dx_dxcc.entity,
                dx_continent      = dx_dxcc.continent,
                comment           = comment,
                when_z            = when_z,
                raw               = line,
            )

        # ---- WWV -----------------------------------------------------------
        m = _RE_WWV.match(line)
        if m:
            kv = _extract_kv(m.group("body"))
            return InfoRecord(
                kind    = "wwv",
                sfi     = kv.get("SFI"),
                a_index = kv.get("A"),
                k_index = kv.get("K"),
                r       = kv.get("R"),
                origin  = m.group("origin").upper(),
                text    = m.group("body").strip(),
                raw     = line,
            )

        # ---- WCY -----------------------------------------------------------
        m = _RE_WCY.match(line)
        if m:
            kv = _extract_kv(m.group("body"))
            return InfoRecord(
                kind    = "wcy",
                sfi     = kv.get("SFI"),
                a_index = kv.get("A"),
                k_index = kv.get("K"),
                r       = kv.get("R"),
                origin  = m.group("origin").upper(),
                text    = m.group("body").strip(),
                raw     = line,
            )

        # ---- Announce ------------------------------------------------------
        m = _RE_ANN.match(line)
        if m:
            return InfoRecord(
                kind   = "announce",
                origin = m.group("origin").upper(),
                text   = m.group("text").strip(),
                raw    = line,
            )

    except Exception:
        pass

    return None


def parse_users_block(text: str) -> list[ConnectedUser]:
    """Parse the multi-line output of DXSpider ``show/users`` into ConnectedUser records.

    Tolerant scanner:
    - Skips comment lines (starting with #), separator lines (=, -), the
      ``show/users`` command echo, and header lines (``Callsign``, ``Type``...).
    - Expects data lines to have at least two whitespace-separated tokens where
      the first looks like a callsign (letters and digits, optional -N suffix)
      and the second is the connection type string.
    """
    users: list[ConnectedUser] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or _RE_SKIP.match(line):
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        callsign = parts[0].upper()
        conn_type = parts[1].upper()
        if not _RE_CALLSIGN.match(callsign):
            continue
        users.append(ConnectedUser(callsign=callsign, conn_type=conn_type))
    return users
