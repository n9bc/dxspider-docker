"""DXCC prefix resolution for DX cluster callsigns.

Public API
----------
resolve(call: str) -> Dxcc
    Given a raw callsign (with optional /portable or DX-prefix/ decoration),
    return the matching DXCC entity, continent and CQ zone.  Unknown input
    returns Dxcc(None, None, None).

The prefix table is loaded once at module import from
    data/dxcc_prefixes.csv
relative to this file's parent directory.
"""

import csv
from dataclasses import dataclass
from pathlib import Path

__all__ = ["Dxcc", "resolve"]

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Dxcc:
    entity: "str | None"
    continent: "str | None"
    cq_zone: "int | None"


_UNKNOWN = Dxcc(None, None, None)

# ---------------------------------------------------------------------------
# Prefix table — loaded once at import
# ---------------------------------------------------------------------------

def _load_table(csv_path: Path) -> list[tuple[str, Dxcc]]:
    """Return list of (prefix, Dxcc) sorted longest-first for greedy match."""
    rows: list[tuple[str, Dxcc]] = []
    with csv_path.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            prefix = row["prefix"].strip().upper()
            if not prefix:
                continue
            try:
                zone: "int | None" = int(row["cq_zone"].strip())
            except (ValueError, KeyError):
                zone = None
            rows.append((
                prefix,
                Dxcc(
                    entity=row["entity"].strip() or None,
                    continent=row["continent"].strip() or None,
                    cq_zone=zone,
                ),
            ))
    # Sort longest prefix first so the first hit is always the best match.
    rows.sort(key=lambda t: len(t[0]), reverse=True)
    return rows


_CSV_PATH = Path(__file__).resolve().parent.parent / "data" / "dxcc_prefixes.csv"
_TABLE: list[tuple[str, Dxcc]] = _load_table(_CSV_PATH)

# ---------------------------------------------------------------------------
# Resolution logic
# ---------------------------------------------------------------------------

# Suffixes that mean "portable" / "mobile on land" — not a new DXCC entity.
_PORTABLE_SUFFIXES = frozenset({"P", "M", "QRP", "A", "0", "1", "2", "3", "4",
                                 "5", "6", "7", "8", "9"})

# Suffixes that indicate maritime / aeronautical mobile → no DXCC entity.
_MOBILE_SUFFIXES = frozenset({"MM", "AM"})


def _longest_prefix_match(candidate: str) -> Dxcc:
    """Return the best-matching Dxcc for *candidate* (already upper-cased)."""
    for prefix, dxcc in _TABLE:
        if candidate.startswith(prefix):
            return dxcc
    return _UNKNOWN


def resolve(call: str) -> Dxcc:
    """Resolve *call* to its DXCC entity.

    Slash handling
    --------------
    * ``/MM`` or ``/AM`` suffix → maritime/aeronautical mobile → unknown.
    * ``PREFIX/CALL`` where the left part is shorter (≤ 3 chars or contains
      only letters and at most one digit, and the right part is the longer
      callsign) → use the left part as the operating location.
    * ``CALL/SUFFIX`` where the right part is a known portable suffix or a
      single digit → ignore suffix, use left part.

    Longest-prefix matching is applied after the above normalisation.
    """
    call = call.strip().upper()
    if not call:
        return _UNKNOWN

    # Split on the first slash only.
    if "/" in call:
        left, right = call.split("/", 1)

        # Maritime / aeronautical mobile → no entity.
        if right in _MOBILE_SUFFIXES:
            return _UNKNOWN

        # Decide which side is the operating location:
        #   • If right is a known portable suffix → left is the callsign.
        #   • If left is shorter (or ≤ 3 chars) → left is the DX prefix.
        #   • Otherwise fall back to left being the callsign.
        if right in _PORTABLE_SUFFIXES:
            # e.g. G3XYZ/P, W1AW/4 — operate from home DXCC
            candidate = left
        elif len(left) <= len(right) and len(left) <= 3:
            # e.g. F/G3XYZ — operating from France
            candidate = left
        else:
            # e.g. some other compound — treat left as the callsign
            candidate = left
    else:
        candidate = call

    return _longest_prefix_match(candidate)
