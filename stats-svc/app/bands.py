"""Band and mode classification for DX cluster spots."""
import re

# IARU band edges: (low_khz, high_khz, name)
_BANDS = [
    (1800.0,   2000.0,   "160m"),
    (3500.0,   4000.0,   "80m"),
    (5351.5,   5366.5,   "60m"),
    (7000.0,   7300.0,   "40m"),
    (10100.0,  10150.0,  "30m"),
    (14000.0,  14350.0,  "20m"),
    (18068.0,  18168.0,  "17m"),
    (21000.0,  21450.0,  "15m"),
    (24890.0,  24990.0,  "12m"),
    (28000.0,  29700.0,  "10m"),
    (50000.0,  54000.0,  "6m"),
    (70000.0,  70500.0,  "4m"),
    (144000.0, 148000.0, "2m"),
    (430000.0, 440000.0, "70cm"),
]

# Per-band sub-segment split: (low_khz, split_khz) — below split -> CW, above -> SSB
# Split points follow IARU Region 1 band plan (phone segments start above CW/data segments)
_BAND_SEGMENTS = {
    "160m": (1800.0,  1838.0),
    "80m":  (3500.0,  3600.0),
    "40m":  (7000.0,  7040.0),
    "30m":  (10100.0, 10150.0),   # 30m is CW/data only; treat all as CW
    "20m":  (14000.0, 14150.0),
    "17m":  (18068.0, 18110.0),
    "15m":  (21000.0, 21150.0),
    "12m":  (24890.0, 24930.0),
    "10m":  (28000.0, 28300.0),
}

# Mode keywords — ordered longest-first so longer tokens shadow shorter ones
_MODE_KEYWORDS = [
    ("PSK31", "PSK31"),
    ("RTTY",  "RTTY"),
    ("FT8",   "FT8"),
    ("FT4",   "FT4"),
    ("JT65",  "JT65"),
    ("JT9",   "JT9"),
    ("PSK",   "PSK"),
    ("USB",   "SSB"),
    ("LSB",   "SSB"),
    ("SSB",   "SSB"),
    ("CW",    "CW"),
    ("AM",    "AM"),
    ("FM",    "FM"),
]

# Pre-compile patterns keyed by keyword (case-insensitive word boundary match)
_MODE_PATTERNS = [
    (re.compile(r'\b' + kw + r'\b', re.IGNORECASE), mode)
    for kw, mode in _MODE_KEYWORDS
]


def band_for_khz(khz: float) -> "str | None":
    """Return the amateur band name for the given frequency in kHz, or None."""
    for low, high, name in _BANDS:
        if low <= khz < high:
            return name
    return None


def mode_for_khz_comment(khz: float, comment: str) -> "str | None":
    """Return a mode string inferred from the spot comment and/or frequency.

    Priority:
    1. Keyword match in comment (longest keyword wins).
    2. Band-plan sub-segment inference (CW lower portion, SSB upper).
    3. None if out-of-band and comment has no recognizable keyword.
    """
    # 1. Keyword scan (patterns already sorted longest-first)
    for pattern, mode in _MODE_PATTERNS:
        if pattern.search(comment):
            return mode

    # 2. Sub-segment inference
    band = band_for_khz(khz)
    if band and band in _BAND_SEGMENTS:
        low, split = _BAND_SEGMENTS[band]
        return "CW" if khz < split else "SSB"

    return None
