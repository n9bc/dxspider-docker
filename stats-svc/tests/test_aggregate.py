"""Tests for app.aggregate — chart aggregation logic.

Seed strategy
-------------
We create a MemoryRepo with spots spread across 3 hours (h0, h1, h2) that are
all within a 24-hour window so activity_series picks them all up.  We use
concrete, hand-calculated expected values so that assertions are real.

Spot inventory (14 spots total):
  h0 (2 human spots):
    spot A: band=20m, mode=CW,  source=human, spotter=K1ABC, dx=JA1XX,
            spotter_dxcc=USA, dx_dxcc=Japan, dx_continent=AS
    spot B: band=40m, mode=CW,  source=human, spotter=K1ABC, dx=VK2YY,
            spotter_dxcc=USA, dx_dxcc=Australia, dx_continent=OC

  h1 (5 spots: 3 human, 2 rbn):
    spot C: band=20m, mode=CW,  source=human, spotter=G3XYZ, dx=JA1XX,
            spotter_dxcc=England, dx_dxcc=Japan, dx_continent=AS
    spot D: band=15m, mode=SSB, source=human, spotter=G3XYZ, dx=EA8ZZ,
            spotter_dxcc=England, dx_dxcc=Spain, dx_continent=EU
    spot E: band=10m, mode=FT8, source=human, spotter=W0YVA, dx=PY3QQ,
            spotter_dxcc=USA, dx_dxcc=Brazil, dx_continent=SA
    spot F: band=20m, mode=CW,  source=rbn,   spotter=RBN1,  dx=JA1XX,
            spotter_dxcc=USA, dx_dxcc=Japan, dx_continent=AS
    spot G: band=None, mode=None, source=rbn, spotter=RBN2, dx=VK2YY,
            spotter_dxcc=None, dx_dxcc=None, dx_continent=None

  h2 (7 spots: 3 human, 4 rbn):
    spot H: band=20m, mode=CW,  source=human, spotter=K1ABC, dx=DX1AAA,
            spotter_dxcc=USA, dx_dxcc=Philippines, dx_continent=OC
    spot I: band=40m, mode=SSB, source=human, spotter=G3XYZ, dx=EA8ZZ,
            spotter_dxcc=England, dx_dxcc=Spain, dx_continent=EU
    spot J: band=20m, mode=CW,  source=human, spotter=K1ABC, dx=JA1XX,
            spotter_dxcc=USA, dx_dxcc=Japan, dx_continent=AS
    spot K: band=20m, mode=CW,  source=rbn,   spotter=RBN1,  dx=JA1XX,
            spotter_dxcc=USA, dx_dxcc=Japan, dx_continent=AS
    spot L: band=15m, mode=CW,  source=rbn,   spotter=RBN1,  dx=PY3QQ,
            spotter_dxcc=USA, dx_dxcc=Brazil, dx_continent=SA
    spot M: band=10m, mode=FT8, source=rbn,   spotter=RBN2,  dx=VK2YY,
            spotter_dxcc=None, dx_dxcc=None, dx_continent=None
    spot N: band=20m, mode=FT8, source=rbn,   spotter=RBN2,  dx=EA8ZZ,
            spotter_dxcc=None, dx_dxcc=Spain, dx_continent=EU

Totals (all 14):
  band counts: 20m=7 (A,C,F,H,J,K,N), 40m=2 (B,I), 15m=2 (D,L), 10m=2 (E,M), unknown=1 (G)
  mode counts: CW=7(A,B,C,F,H,J,K,L... wait)
    A=CW, B=CW, C=CW, D=SSB, E=FT8, F=CW, G=None→unknown, H=CW, I=SSB, J=CW, K=CW, L=CW, M=FT8, N=FT8
    CW=8(A,B,C,F,H,J,K,L), SSB=2(D,I), FT8=3(E,M,N), unknown=1(G)
  dx_continent: AS=5(A,C,F,J,K), OC=3(B,G→unk,H... wait G has None continent)
    AS=5(A,C,F,J,K), OC=2(B,H), EU=3(D,I,N), SA=2(E,L), unknown=2(G,M)
  human source 8: A,B,C,D,E,H,I,J
  rbn source 6: F,G,K,L,M,N

  per-hour counts:
    h0: 2 total (2 human, 0 rbn)
    h1: 5 total (3 human, 2 rbn)
    h2: 7 total (3 human, 4 rbn)

  top spotters (all, 24h fetch):
    K1ABC: spots A,B,H,J = 4
    G3XYZ: spots C,D,I   = 3
    W0YVA: spot E         = 1
    RBN1:  spots F,K,L   = 3
    RBN2:  spots G,M,N   = 3

  top dx_call:
    JA1XX: A,C,F,J,K = 5
    VK2YY: B,G,M     = 3
    EA8ZZ: D,I,N     = 3
    PY3QQ: E,L       = 2
    DX1AAA: H        = 1
"""

import datetime as dt
import pytest

from app.repo import MemoryRepo
from app.parsers import SpotRecord, ConnectedUser
from app.aggregate import (
    activity_series,
    band_breakdown,
    mode_breakdown,
    geo_breakdown,
    top_spotters,
    top_dx,
    rare_dx,
    callsign_detail,
    connected,
)

# ---------------------------------------------------------------------------
# Helper: build a SpotRecord with sensible defaults
# ---------------------------------------------------------------------------

def _spot(**kw) -> SpotRecord:
    base = dict(
        kind="spot",
        spotter="K1ABC",
        dx_call="JA1XX",
        freq_khz=14025.0,
        band="20m",
        mode="CW",
        source="human",
        spotter_dxcc="USA",
        spotter_continent="NA",
        dx_dxcc="Japan",
        dx_continent="AS",
        comment="",
        when_z=None,
        raw="",
    )
    base.update(kw)
    return SpotRecord(**base)


# ---------------------------------------------------------------------------
# Fixture: seeded repo
# ---------------------------------------------------------------------------

# Reference timestamps — h2 is the most recent rollup hour; spots live inside
# each bucket (30 min past the hour).  We fix a deterministic "now" that is
# within _H2 but late enough for all _T* spots to be inside [since, now).
_H2 = dt.datetime(2026, 5, 16, 15, 0, 0, tzinfo=dt.timezone.utc)   # 15:00 UTC
_H1 = _H2 - dt.timedelta(hours=1)                                    # 14:00 UTC
_H0 = _H2 - dt.timedelta(hours=2)                                    # 13:00 UTC

# Timestamps within each hour bucket (30 min past the hour)
_T0 = _H0.replace(minute=30)   # 13:30
_T1 = _H1.replace(minute=30)   # 14:30
_T2 = _H2.replace(minute=30)   # 15:30

# "now" for time-windowed functions: 15:59, so:
#   latest_hour = 15:00 = _H2
#   3-hour window covers _H0, _H1, _H2
#   fetch_spots(since=15:59-24h, until=15:59) captures all _T* spots
_NOW = _H2.replace(minute=59)


async def _make_repo() -> MemoryRepo:
    r = MemoryRepo()

    # --- h0: 2 human ---
    await r.insert_spot(_spot(spotter="K1ABC", dx_call="JA1XX", band="20m", mode="CW",
                               source="human", spotter_dxcc="USA", dx_dxcc="Japan",
                               dx_continent="AS"), _T0)                         # A
    await r.insert_spot(_spot(spotter="K1ABC", dx_call="VK2YY", band="40m", mode="CW",
                               source="human", spotter_dxcc="USA", dx_dxcc="Australia",
                               dx_continent="OC"), _T0)                         # B

    # --- h1: 3 human + 2 rbn ---
    await r.insert_spot(_spot(spotter="G3XYZ", dx_call="JA1XX", band="20m", mode="CW",
                               source="human", spotter_dxcc="England", dx_dxcc="Japan",
                               dx_continent="AS"), _T1)                         # C
    await r.insert_spot(_spot(spotter="G3XYZ", dx_call="EA8ZZ", band="15m", mode="SSB",
                               source="human", spotter_dxcc="England", dx_dxcc="Spain",
                               dx_continent="EU"), _T1)                         # D
    await r.insert_spot(_spot(spotter="W0YVA", dx_call="PY3QQ", band="10m", mode="FT8",
                               source="human", spotter_dxcc="USA", dx_dxcc="Brazil",
                               dx_continent="SA"), _T1)                         # E
    await r.insert_spot(_spot(spotter="RBN1",  dx_call="JA1XX", band="20m", mode="CW",
                               source="rbn",   spotter_dxcc="USA", dx_dxcc="Japan",
                               dx_continent="AS"), _T1)                         # F
    await r.insert_spot(_spot(spotter="RBN2",  dx_call="VK2YY", band=None, mode=None,
                               source="rbn",   spotter_dxcc=None, dx_dxcc=None,
                               dx_continent=None), _T1)                         # G

    # --- h2: 3 human + 4 rbn ---
    await r.insert_spot(_spot(spotter="K1ABC", dx_call="DX1AAA", band="20m", mode="CW",
                               source="human", spotter_dxcc="USA", dx_dxcc="Philippines",
                               dx_continent="OC"), _T2)                         # H
    await r.insert_spot(_spot(spotter="G3XYZ", dx_call="EA8ZZ", band="40m", mode="SSB",
                               source="human", spotter_dxcc="England", dx_dxcc="Spain",
                               dx_continent="EU"), _T2)                         # I
    await r.insert_spot(_spot(spotter="K1ABC", dx_call="JA1XX", band="20m", mode="CW",
                               source="human", spotter_dxcc="USA", dx_dxcc="Japan",
                               dx_continent="AS"), _T2)                         # J
    await r.insert_spot(_spot(spotter="RBN1",  dx_call="JA1XX", band="20m", mode="CW",
                               source="rbn",   spotter_dxcc="USA", dx_dxcc="Japan",
                               dx_continent="AS"), _T2)                         # K
    await r.insert_spot(_spot(spotter="RBN1",  dx_call="PY3QQ", band="15m", mode="CW",
                               source="rbn",   spotter_dxcc="USA", dx_dxcc="Brazil",
                               dx_continent="SA"), _T2)                         # L
    await r.insert_spot(_spot(spotter="RBN2",  dx_call="VK2YY", band="10m", mode="FT8",
                               source="rbn",   spotter_dxcc=None, dx_dxcc=None,
                               dx_continent=None), _T2)                         # M
    await r.insert_spot(_spot(spotter="RBN2",  dx_call="EA8ZZ", band="20m", mode="FT8",
                               source="rbn",   spotter_dxcc=None, dx_dxcc="Spain",
                               dx_continent="EU"), _T2)                         # N

    # Connected users
    snap = _H2
    await r.replace_connected_users(
        [
            ConnectedUser(callsign="W1AW",   conn_type="USER"),
            ConnectedUser(callsign="K1ABC",  conn_type="USER"),
            ConnectedUser(callsign="VE3XYZ", conn_type="NODE"),
        ],
        snap,
    )

    return r


# ---------------------------------------------------------------------------
# activity_series
# ---------------------------------------------------------------------------

class TestActivitySeries:
    """activity_series returns per-hour buckets in ascending order."""

    @pytest.mark.asyncio
    async def test_shape_and_keys(self):
        r = await _make_repo()
        # Use hours=3 and _now=_NOW so the window covers exactly h0, h1, h2.
        result = await activity_series(r, hours=3, _now=_NOW)
        assert isinstance(result, list)
        assert len(result) == 3
        for item in result:
            assert set(item.keys()) == {"hour", "count"}
            assert isinstance(item["hour"], str)
            assert isinstance(item["count"], int)

    @pytest.mark.asyncio
    async def test_ascending_order(self):
        r = await _make_repo()
        result = await activity_series(r, hours=3, _now=_NOW)
        hours = [item["hour"] for item in result]
        assert hours == sorted(hours)

    @pytest.mark.asyncio
    async def test_counts_both_sources(self):
        """source='both' sums human + rbn for each hour."""
        r = await _make_repo()
        result = await activity_series(r, hours=3, _now=_NOW)
        counts = [item["count"] for item in result]
        # h0=2, h1=5, h2=7 (in ascending order from oldest)
        assert counts == [2, 5, 7]

    @pytest.mark.asyncio
    async def test_source_filter_human(self):
        r = await _make_repo()
        result = await activity_series(r, source="human", hours=3, _now=_NOW)
        counts = [item["count"] for item in result]
        # h0=2 human, h1=3 human, h2=3 human
        assert counts == [2, 3, 3]

    @pytest.mark.asyncio
    async def test_source_filter_rbn(self):
        r = await _make_repo()
        result = await activity_series(r, source="rbn", hours=3, _now=_NOW)
        counts = [item["count"] for item in result]
        # h0=0 rbn, h1=2 rbn, h2=4 rbn
        assert counts == [0, 2, 4]

    @pytest.mark.asyncio
    async def test_zero_filled_hour_included(self):
        """Hours with no spots still appear in the series with count=0."""
        r = await _make_repo()
        # Only rbn filter for h0 has 0 spots
        result = await activity_series(r, source="rbn", hours=3, _now=_NOW)
        assert result[0]["count"] == 0   # h0 has no rbn spots

    @pytest.mark.asyncio
    async def test_iso8601_format(self):
        """hour field must be parseable ISO-8601 UTC string."""
        r = await _make_repo()
        result = await activity_series(r, hours=3, _now=_NOW)
        for item in result:
            parsed = dt.datetime.fromisoformat(item["hour"])
            assert parsed.tzinfo is not None

    @pytest.mark.asyncio
    async def test_empty_repo(self):
        r = MemoryRepo()
        result = await activity_series(r, hours=24, _now=_NOW)
        assert isinstance(result, list)
        assert len(result) == 24
        assert all(item["count"] == 0 for item in result)


# ---------------------------------------------------------------------------
# band_breakdown
# ---------------------------------------------------------------------------

class TestBandBreakdown:
    """band_breakdown returns label/value dicts descending by value."""

    @pytest.mark.asyncio
    async def test_shape(self):
        r = await _make_repo()
        result = await band_breakdown(r)
        assert isinstance(result, list)
        for item in result:
            assert set(item.keys()) == {"label", "value"}
            assert isinstance(item["label"], str)
            assert isinstance(item["value"], int)

    @pytest.mark.asyncio
    async def test_descending_order(self):
        r = await _make_repo()
        result = await band_breakdown(r)
        values = [item["value"] for item in result]
        assert values == sorted(values, reverse=True)

    @pytest.mark.asyncio
    async def test_all_counts_both(self):
        """All 14 spots counted; 20m=7, 40m=2, 15m=2, 10m=2, unknown=1."""
        r = await _make_repo()
        result = await band_breakdown(r)
        d = {item["label"]: item["value"] for item in result}
        assert d["20m"] == 7
        assert d["40m"] == 2
        assert d["15m"] == 2
        assert d["10m"] == 2
        assert d["unknown"] == 1

    @pytest.mark.asyncio
    async def test_unknown_label_for_empty_band(self):
        r = await _make_repo()
        result = await band_breakdown(r)
        labels = [item["label"] for item in result]
        assert "unknown" in labels
        assert "" not in labels

    @pytest.mark.asyncio
    async def test_source_filter_human(self):
        """Human only: A=20m, B=40m, C=20m, D=15m, E=10m, H=20m, I=40m, J=20m.
        20m=4, 40m=2, 15m=1, 10m=1, no unknowns."""
        r = await _make_repo()
        result = await band_breakdown(r, source="human")
        d = {item["label"]: item["value"] for item in result}
        assert d["20m"] == 4
        assert d["40m"] == 2
        assert d["15m"] == 1
        assert d["10m"] == 1
        assert "unknown" not in d

    @pytest.mark.asyncio
    async def test_source_filter_rbn(self):
        """RBN only: F=20m, G=None, K=20m, L=15m, M=10m, N=20m.
        20m=3, 15m=1, 10m=1, unknown=1."""
        r = await _make_repo()
        result = await band_breakdown(r, source="rbn")
        d = {item["label"]: item["value"] for item in result}
        assert d["20m"] == 3
        assert d["15m"] == 1
        assert d["10m"] == 1
        assert d["unknown"] == 1

    @pytest.mark.asyncio
    async def test_empty_repo(self):
        r = MemoryRepo()
        result = await band_breakdown(r)
        assert result == []


# ---------------------------------------------------------------------------
# mode_breakdown
# ---------------------------------------------------------------------------

class TestModeBreakdown:
    """mode_breakdown returns label/value dicts descending by value."""

    @pytest.mark.asyncio
    async def test_shape(self):
        r = await _make_repo()
        result = await mode_breakdown(r)
        assert isinstance(result, list)
        for item in result:
            assert set(item.keys()) == {"label", "value"}

    @pytest.mark.asyncio
    async def test_descending_order(self):
        r = await _make_repo()
        result = await mode_breakdown(r)
        values = [item["value"] for item in result]
        assert values == sorted(values, reverse=True)

    @pytest.mark.asyncio
    async def test_all_counts_both(self):
        """CW=8(A,B,C,F,H,J,K,L), SSB=2(D,I), FT8=3(E,M,N), unknown=1(G)."""
        r = await _make_repo()
        result = await mode_breakdown(r)
        d = {item["label"]: item["value"] for item in result}
        assert d["CW"] == 8
        assert d["SSB"] == 2
        assert d["FT8"] == 3
        assert d["unknown"] == 1

    @pytest.mark.asyncio
    async def test_unknown_label_for_empty_mode(self):
        r = await _make_repo()
        result = await mode_breakdown(r)
        labels = [item["label"] for item in result]
        assert "unknown" in labels
        assert "" not in labels

    @pytest.mark.asyncio
    async def test_source_filter_human(self):
        """Human: CW=5(A,B,C,H,J), SSB=2(D,I), FT8=1(E). No unknowns."""
        r = await _make_repo()
        result = await mode_breakdown(r, source="human")
        d = {item["label"]: item["value"] for item in result}
        assert d["CW"] == 5
        assert d["SSB"] == 2
        assert d["FT8"] == 1
        assert "unknown" not in d

    @pytest.mark.asyncio
    async def test_empty_repo(self):
        r = MemoryRepo()
        result = await mode_breakdown(r)
        assert result == []


# ---------------------------------------------------------------------------
# geo_breakdown
# ---------------------------------------------------------------------------

class TestGeoBreakdown:
    """geo_breakdown groups by a dimension; top N, desc, unknown relabeled."""

    @pytest.mark.asyncio
    async def test_shape(self):
        r = await _make_repo()
        result = await geo_breakdown(r, by="dx_continent")
        assert isinstance(result, list)
        for item in result:
            assert set(item.keys()) == {"label", "value"}

    @pytest.mark.asyncio
    async def test_descending_order(self):
        r = await _make_repo()
        result = await geo_breakdown(r, by="dx_continent")
        values = [item["value"] for item in result]
        assert values == sorted(values, reverse=True)

    @pytest.mark.asyncio
    async def test_dx_continent_counts(self):
        """AS=5(A,C,F,J,K), EU=3(D,I,N), OC=2(B,H), SA=2(E,L), unknown=2(G,M)."""
        r = await _make_repo()
        result = await geo_breakdown(r, by="dx_continent")
        d = {item["label"]: item["value"] for item in result}
        assert d["AS"] == 5
        assert d["EU"] == 3
        assert d["OC"] == 2
        assert d["SA"] == 2
        assert d["unknown"] == 2

    @pytest.mark.asyncio
    async def test_unknown_label(self):
        r = await _make_repo()
        result = await geo_breakdown(r, by="dx_continent")
        labels = [item["label"] for item in result]
        assert "unknown" in labels
        assert "" not in labels

    @pytest.mark.asyncio
    async def test_top_n_limits(self):
        r = await _make_repo()
        result = await geo_breakdown(r, by="dx_continent", top=2)
        assert len(result) == 2
        # Top 2 by count: AS=5, EU=3
        labels = [item["label"] for item in result]
        assert labels[0] == "AS"
        assert labels[1] == "EU"

    @pytest.mark.asyncio
    async def test_by_dx_dxcc(self):
        """dx_dxcc grouping: Japan=5, Spain=3, Brazil=2, Australia=1, Philippines=1, unknown=2."""
        r = await _make_repo()
        result = await geo_breakdown(r, by="dx_dxcc")
        d = {item["label"]: item["value"] for item in result}
        assert d["Japan"] == 5
        assert d["Spain"] == 3
        assert d["Brazil"] == 2
        assert d["Australia"] == 1
        assert d["Philippines"] == 1
        assert d["unknown"] == 2

    @pytest.mark.asyncio
    async def test_by_spotter_dxcc(self):
        """spotter_dxcc: USA=8(A,B,E,F,J,K,L — plus H spot spotter K1ABC=USA so 8), England=3(C,D,I), unknown=3(G,M,N).
        Let's recount:
          USA spotter: A(K1ABC),B(K1ABC),E(W0YVA),F(RBN1),H(K1ABC),J(K1ABC),K(RBN1),L(RBN1) = 8
          England spotter: C(G3XYZ),D(G3XYZ),I(G3XYZ) = 3
          unknown (None→""): G(RBN2),M(RBN2),N(RBN2) = 3
        """
        r = await _make_repo()
        result = await geo_breakdown(r, by="spotter_dxcc")
        d = {item["label"]: item["value"] for item in result}
        assert d["USA"] == 8
        assert d["England"] == 3
        assert d["unknown"] == 3

    @pytest.mark.asyncio
    async def test_source_filter_human(self):
        """Human only dx_continent: AS=3(A,C,J), EU=2(D,I), OC=2(B,H), SA=1(E). No unknowns."""
        r = await _make_repo()
        result = await geo_breakdown(r, by="dx_continent", source="human")
        d = {item["label"]: item["value"] for item in result}
        assert d["AS"] == 3
        assert d["EU"] == 2
        assert d["OC"] == 2
        assert d["SA"] == 1
        assert "unknown" not in d

    @pytest.mark.asyncio
    async def test_empty_repo(self):
        r = MemoryRepo()
        result = await geo_breakdown(r, by="dx_continent")
        assert result == []

    @pytest.mark.asyncio
    async def test_geo_breakdown_invalid_by_raises(self):
        from app.aggregate import geo_breakdown
        from app.repo import MemoryRepo
        with pytest.raises(ValueError):
            await geo_breakdown(MemoryRepo(), by="not_a_dimension")


# ---------------------------------------------------------------------------
# top_spotters
# ---------------------------------------------------------------------------

class TestTopSpotters:
    """top_spotters derives from fetch_spots over the last hours window."""

    @pytest.mark.asyncio
    async def test_shape(self):
        r = await _make_repo()
        result = await top_spotters(r, _now=_NOW)
        assert isinstance(result, list)
        for item in result:
            assert set(item.keys()) == {"callsign", "count"}
            assert isinstance(item["callsign"], str)
            assert isinstance(item["count"], int)

    @pytest.mark.asyncio
    async def test_descending_order(self):
        r = await _make_repo()
        result = await top_spotters(r, _now=_NOW)
        counts = [item["count"] for item in result]
        assert counts == sorted(counts, reverse=True)

    @pytest.mark.asyncio
    async def test_all_sources_counts(self):
        """K1ABC=4, G3XYZ=3, RBN1=3, RBN2=3, W0YVA=1. Top 10 returns all 5."""
        r = await _make_repo()
        result = await top_spotters(r, limit=10, _now=_NOW)
        d = {item["callsign"]: item["count"] for item in result}
        assert d["K1ABC"] == 4
        assert d["G3XYZ"] == 3
        assert d["RBN1"] == 3
        assert d["RBN2"] == 3
        assert d["W0YVA"] == 1

    @pytest.mark.asyncio
    async def test_limit_applied(self):
        r = await _make_repo()
        result = await top_spotters(r, limit=3, _now=_NOW)
        assert len(result) == 3

    @pytest.mark.asyncio
    async def test_source_filter_human(self):
        """Human only: K1ABC=4(A,B,H,J), G3XYZ=3(C,D,I), W0YVA=1(E)."""
        r = await _make_repo()
        result = await top_spotters(r, source="human", limit=10, _now=_NOW)
        d = {item["callsign"]: item["count"] for item in result}
        assert d["K1ABC"] == 4
        assert d["G3XYZ"] == 3
        assert d["W0YVA"] == 1
        assert "RBN1" not in d
        assert "RBN2" not in d

    @pytest.mark.asyncio
    async def test_source_filter_rbn(self):
        """RBN only: RBN1=3(F,K,L), RBN2=3(G,M,N)."""
        r = await _make_repo()
        result = await top_spotters(r, source="rbn", limit=10, _now=_NOW)
        d = {item["callsign"]: item["count"] for item in result}
        assert d["RBN1"] == 3
        assert d["RBN2"] == 3
        assert "K1ABC" not in d

    @pytest.mark.asyncio
    async def test_empty_repo(self):
        r = MemoryRepo()
        result = await top_spotters(r, _now=_NOW)
        assert result == []


# ---------------------------------------------------------------------------
# top_dx
# ---------------------------------------------------------------------------

class TestTopDx:
    """top_dx derives most-spotted dx_call from fetch_spots."""

    @pytest.mark.asyncio
    async def test_shape(self):
        r = await _make_repo()
        result = await top_dx(r, _now=_NOW)
        assert isinstance(result, list)
        for item in result:
            assert set(item.keys()) == {"callsign", "count"}

    @pytest.mark.asyncio
    async def test_descending_order(self):
        r = await _make_repo()
        result = await top_dx(r, _now=_NOW)
        counts = [item["count"] for item in result]
        assert counts == sorted(counts, reverse=True)

    @pytest.mark.asyncio
    async def test_all_sources_counts(self):
        """JA1XX=5, VK2YY=3, EA8ZZ=3, PY3QQ=2, DX1AAA=1."""
        r = await _make_repo()
        result = await top_dx(r, limit=10, _now=_NOW)
        d = {item["callsign"]: item["count"] for item in result}
        assert d["JA1XX"] == 5
        assert d["VK2YY"] == 3
        assert d["EA8ZZ"] == 3
        assert d["PY3QQ"] == 2
        assert d["DX1AAA"] == 1

    @pytest.mark.asyncio
    async def test_limit_applied(self):
        r = await _make_repo()
        result = await top_dx(r, limit=3, _now=_NOW)
        assert len(result) == 3

    @pytest.mark.asyncio
    async def test_source_filter_human(self):
        """Human only: JA1XX=3(A,C,J), EA8ZZ=2(D,I), VK2YY=1(B), DX1AAA=1(H), PY3QQ=1(E)."""
        r = await _make_repo()
        result = await top_dx(r, source="human", limit=10, _now=_NOW)
        d = {item["callsign"]: item["count"] for item in result}
        assert d["JA1XX"] == 3
        assert d["EA8ZZ"] == 2
        assert d["VK2YY"] == 1
        assert d["DX1AAA"] == 1
        assert d["PY3QQ"] == 1

    @pytest.mark.asyncio
    async def test_source_filter_rbn(self):
        """RBN only: JA1XX=2(F,K), VK2YY=2(G,M), EA8ZZ=1(N), PY3QQ=1(L)."""
        r = await _make_repo()
        result = await top_dx(r, source="rbn", limit=10, _now=_NOW)
        d = {item["callsign"]: item["count"] for item in result}
        assert d["JA1XX"] == 2
        assert d["VK2YY"] == 2
        assert d["EA8ZZ"] == 1
        assert d["PY3QQ"] == 1
        assert "DX1AAA" not in d

    @pytest.mark.asyncio
    async def test_empty_repo(self):
        r = MemoryRepo()
        result = await top_dx(r, _now=_NOW)
        assert result == []


# ---------------------------------------------------------------------------
# connected
# ---------------------------------------------------------------------------

class TestConnected:
    """connected returns count + users sorted by callsign."""

    @pytest.mark.asyncio
    async def test_shape(self):
        r = await _make_repo()
        result = await connected(r)
        assert isinstance(result, dict)
        assert set(result.keys()) == {"count", "users"}
        assert isinstance(result["count"], int)
        assert isinstance(result["users"], list)

    @pytest.mark.asyncio
    async def test_count(self):
        r = await _make_repo()
        result = await connected(r)
        assert result["count"] == 3

    @pytest.mark.asyncio
    async def test_users_shape(self):
        r = await _make_repo()
        result = await connected(r)
        for user in result["users"]:
            assert set(user.keys()) == {"callsign", "conn_type"}

    @pytest.mark.asyncio
    async def test_users_sorted_by_callsign(self):
        r = await _make_repo()
        result = await connected(r)
        callsigns = [u["callsign"] for u in result["users"]]
        # K1ABC, VE3XYZ, W1AW — alphabetical
        assert callsigns == sorted(callsigns)
        assert callsigns == ["K1ABC", "VE3XYZ", "W1AW"]

    @pytest.mark.asyncio
    async def test_user_conn_types(self):
        r = await _make_repo()
        result = await connected(r)
        by_cs = {u["callsign"]: u["conn_type"] for u in result["users"]}
        assert by_cs["W1AW"] == "USER"
        assert by_cs["K1ABC"] == "USER"
        assert by_cs["VE3XYZ"] == "NODE"

    @pytest.mark.asyncio
    async def test_empty_repo(self):
        r = MemoryRepo()
        result = await connected(r)
        assert result == {"count": 0, "users": []}


# ---------------------------------------------------------------------------
# rare_dx
# ---------------------------------------------------------------------------
#
# Spot inventory for reference (dx_call counts, all sources, 24h window):
#   JA1XX: 5 (A,C,F,J,K)
#   VK2YY: 3 (B,G,M)
#   EA8ZZ: 3 (D,I,N)
#   PY3QQ: 2 (E,L)
#   DX1AAA: 1 (H)
# Ascending by count then callsign:
#   DX1AAA=1, PY3QQ=2, EA8ZZ=3, VK2YY=3, JA1XX=5

class TestRareDx:
    """rare_dx returns least-spotted DX calls ascending by count then callsign."""

    @pytest.mark.asyncio
    async def test_shape(self):
        r = await _make_repo()
        result = await rare_dx(r, _now=_NOW)
        assert isinstance(result, list)
        for item in result:
            assert set(item.keys()) == {"callsign", "count"}
            assert isinstance(item["callsign"], str)
            assert isinstance(item["count"], int)

    @pytest.mark.asyncio
    async def test_ascending_order(self):
        """Results must be ascending by count (rarest first)."""
        r = await _make_repo()
        result = await rare_dx(r, limit=10, _now=_NOW)
        counts = [item["count"] for item in result]
        assert counts == sorted(counts)

    @pytest.mark.asyncio
    async def test_all_sources_counts(self):
        """DX1AAA=1 must be first (rarest); JA1XX=5 last in the ascending list."""
        r = await _make_repo()
        result = await rare_dx(r, limit=10, _now=_NOW)
        d = {item["callsign"]: item["count"] for item in result}
        assert d["DX1AAA"] == 1
        assert d["PY3QQ"] == 2
        assert d["EA8ZZ"] == 3
        assert d["VK2YY"] == 3
        assert d["JA1XX"] == 5
        # Rarest first
        assert result[0]["callsign"] == "DX1AAA"

    @pytest.mark.asyncio
    async def test_limit_applied(self):
        r = await _make_repo()
        result = await rare_dx(r, limit=2, _now=_NOW)
        assert len(result) == 2
        # Should be the 2 rarest: DX1AAA=1, PY3QQ=2
        callsigns = {item["callsign"] for item in result}
        assert "DX1AAA" in callsigns
        assert "PY3QQ" in callsigns

    @pytest.mark.asyncio
    async def test_source_filter_human(self):
        """Human only dx_call counts: JA1XX=3(A,C,J), EA8ZZ=2(D,I), VK2YY=1(B),
        DX1AAA=1(H), PY3QQ=1(E). Ascending: DX1AAA=1, PY3QQ=1, VK2YY=1 (ties by callsign),
        EA8ZZ=2, JA1XX=3."""
        r = await _make_repo()
        result = await rare_dx(r, source="human", limit=10, _now=_NOW)
        d = {item["callsign"]: item["count"] for item in result}
        assert d["JA1XX"] == 3
        assert d["EA8ZZ"] == 2
        assert d["VK2YY"] == 1
        assert d["DX1AAA"] == 1
        assert d["PY3QQ"] == 1
        # All counts ascending
        counts = [item["count"] for item in result]
        assert counts == sorted(counts)

    @pytest.mark.asyncio
    async def test_source_filter_rbn(self):
        """RBN only: JA1XX=2(F,K), VK2YY=2(G,M), EA8ZZ=1(N), PY3QQ=1(L).
        Ascending: EA8ZZ=1, PY3QQ=1, JA1XX=2, VK2YY=2."""
        r = await _make_repo()
        result = await rare_dx(r, source="rbn", limit=10, _now=_NOW)
        d = {item["callsign"]: item["count"] for item in result}
        assert d["JA1XX"] == 2
        assert d["VK2YY"] == 2
        assert d["EA8ZZ"] == 1
        assert d["PY3QQ"] == 1
        counts = [item["count"] for item in result]
        assert counts == sorted(counts)

    @pytest.mark.asyncio
    async def test_empty_repo(self):
        r = MemoryRepo()
        result = await rare_dx(r, _now=_NOW)
        assert result == []


# ---------------------------------------------------------------------------
# callsign_detail
# ---------------------------------------------------------------------------
#
# Using _make_repo() seeded spots:
#   K1ABC as spotter: A(_T0), B(_T0), H(_T2), J(_T2) → 4 spots as spotter
#   K1ABC as dx: none (K1ABC never appears as dx_call in the seed data)
#   JA1XX as dx: A,C,F,J,K → 5 spots as dx; as spotter: 0
#   RBN1 as spotter: F(_T1), K(_T2), L(_T2) → 3 as spotter; as dx: 0
#
# _NOW = _H2.replace(minute=59) = 15:59 UTC
# default hours=168 for callsign_detail (1 week), _T0/_T1/_T2 are all within 3h

class TestCallsignDetail:
    """callsign_detail returns per-callsign spotter/dx counts and recent spots."""

    @pytest.mark.asyncio
    async def test_shape(self):
        r = await _make_repo()
        result = await callsign_detail(r, "K1ABC", _now=_NOW)
        assert isinstance(result, dict)
        assert set(result.keys()) == {"callsign", "as_spotter", "as_dx", "recent"}
        assert isinstance(result["as_spotter"], int)
        assert isinstance(result["as_dx"], int)
        assert isinstance(result["recent"], list)

    @pytest.mark.asyncio
    async def test_callsign_uppercased(self):
        r = await _make_repo()
        result = await callsign_detail(r, "k1abc", _now=_NOW)
        assert result["callsign"] == "K1ABC"

    @pytest.mark.asyncio
    async def test_k1abc_as_spotter_count(self):
        """K1ABC appears as spotter in spots A,B,H,J → as_spotter=4."""
        r = await _make_repo()
        result = await callsign_detail(r, "K1ABC", _now=_NOW)
        assert result["as_spotter"] == 4

    @pytest.mark.asyncio
    async def test_k1abc_as_dx_count(self):
        """K1ABC never appears as dx_call in seed data → as_dx=0."""
        r = await _make_repo()
        result = await callsign_detail(r, "K1ABC", _now=_NOW)
        assert result["as_dx"] == 0

    @pytest.mark.asyncio
    async def test_ja1xx_as_dx_count(self):
        """JA1XX appears as dx_call in A,C,F,J,K → as_dx=5."""
        r = await _make_repo()
        result = await callsign_detail(r, "JA1XX", _now=_NOW)
        assert result["as_dx"] == 5

    @pytest.mark.asyncio
    async def test_ja1xx_as_spotter_count(self):
        """JA1XX never spots in seed data → as_spotter=0."""
        r = await _make_repo()
        result = await callsign_detail(r, "JA1XX", _now=_NOW)
        assert result["as_spotter"] == 0

    @pytest.mark.asyncio
    async def test_recent_newest_first(self):
        """Recent spots must be sorted newest first (descending ts)."""
        r = await _make_repo()
        result = await callsign_detail(r, "K1ABC", _now=_NOW)
        recent = result["recent"]
        assert len(recent) > 1
        ts_list = [item["ts"] for item in recent]
        # All ts strings; check descending order
        assert ts_list == sorted(ts_list, reverse=True)

    @pytest.mark.asyncio
    async def test_recent_max_25(self):
        """recent list is capped at 25 entries."""
        r = MemoryRepo()
        # Insert 30 spots for the same callsign
        base_ts = dt.datetime(2026, 5, 16, 10, 0, 0, tzinfo=dt.timezone.utc)
        for i in range(30):
            ts = base_ts + dt.timedelta(minutes=i)
            await r.insert_spot(_spot(spotter="ZZ9ZZZ", dx_call="JA1XX"), ts)
        result = await callsign_detail(r, "ZZ9ZZZ", _now=base_ts + dt.timedelta(hours=2))
        assert len(result["recent"]) == 25

    @pytest.mark.asyncio
    async def test_recent_fields(self):
        """Each recent entry has the required fields."""
        r = await _make_repo()
        result = await callsign_detail(r, "K1ABC", _now=_NOW)
        for entry in result["recent"]:
            assert set(entry.keys()) == {"ts", "spotter", "dx_call", "freq_khz", "band", "mode", "source"}

    @pytest.mark.asyncio
    async def test_window_filter(self):
        """Spots outside the hours window are excluded."""
        r = await _make_repo()
        # Use hours=1: only _T2 spots (at 15:30) fall in [14:59, 15:59)
        # _NOW = 15:59, since = 14:59, _T2 = 15:30 → inside; _T1=14:30 → outside
        result = await callsign_detail(r, "K1ABC", hours=1, _now=_NOW)
        # K1ABC spots in last hour: H and J (both at _T2=15:30)
        assert result["as_spotter"] == 2

    @pytest.mark.asyncio
    async def test_unknown_callsign_returns_zeros_empty(self):
        """A callsign with no spots returns zeros and empty recent list."""
        r = await _make_repo()
        result = await callsign_detail(r, "XX0UNKNOWN", _now=_NOW)
        assert result["callsign"] == "XX0UNKNOWN"
        assert result["as_spotter"] == 0
        assert result["as_dx"] == 0
        assert result["recent"] == []
