from pathlib import Path

from app.parsers import parse_line, parse_users_block, SpotRecord, InfoRecord, ConnectedUser


def test_parse_human_spot():
    rec = parse_line("DX de K1ABC:     14025.0  JA1XYZ       CW 599 up 2          1234Z")
    assert isinstance(rec, SpotRecord)
    assert rec.kind == "spot"
    assert rec.spotter == "K1ABC"
    assert rec.dx_call == "JA1XYZ"
    assert rec.freq_khz == 14025.0
    assert rec.source == "human"
    assert rec.band == "20m"
    assert rec.mode == "CW"
    assert rec.dx_dxcc == "Japan"
    assert rec.dx_continent == "AS"
    assert "CW 599 up 2" in rec.comment


def test_parse_rbn_spot_detected_by_skimmer_marker():
    rec = parse_line("DX de OH6BG-#:   14025.0  JA1XYZ       CW 12 dB 24 WPM CQ   1234Z")
    assert rec.spotter == "OH6BG"
    assert rec.source == "rbn"
    assert rec.dx_call == "JA1XYZ"


def test_parse_wwv():
    rec = parse_line("WWV de AR0NL <18>:   SFI=140, A=7, K=2, No Storms -> No Storms")
    assert isinstance(rec, InfoRecord)
    assert rec.kind == "wwv"
    assert rec.sfi == 140
    assert rec.a_index == 7
    assert rec.k_index == 2


def test_parse_wcy():
    rec = parse_line("WCY de DK0WCY-1 <12> : K=2 expK=0 A=10 R=120 SFI=140 SA=qui GMF=qui Au=no")
    assert rec.kind == "wcy"
    assert rec.sfi == 140
    assert rec.k_index == 2
    assert rec.a_index == 10


def test_parse_announce():
    rec = parse_line("To ALL de G1ABC: Hello world <1234Z>")
    assert isinstance(rec, InfoRecord)
    assert rec.kind == "announce"
    assert rec.origin == "G1ABC"
    assert "Hello world" in rec.text


def test_unparseable_returns_none():
    assert parse_line("random console noise") is None
    assert parse_line("") is None


def test_parse_users_block():
    text = (Path(__file__).parent / "fixtures" / "users_block.txt").read_text(encoding="utf-8")
    users = parse_users_block(text)
    calls = {u.callsign for u in users}
    assert "K1ABC" in calls
    assert "G7XYZ" in calls
    assert all(isinstance(u, ConnectedUser) for u in users)
    k = next(u for u in users if u.callsign == "K1ABC")
    assert k.conn_type  # non-empty string


def test_parse_rbn_spot_detected_by_skimmer_grammar():
    rec = parse_line("DX de W9PA:   14025.0  JA1XYZ       CW 15 dB 25 WPM CQ   1234Z")
    assert rec.source == "rbn"
    assert rec.spotter == "W9PA"


def test_parse_line_none_and_nonstring_returns_none():
    assert parse_line(None) is None
    assert parse_line(12345) is None
