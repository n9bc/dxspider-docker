from app.bands import band_for_khz, mode_for_khz_comment

def test_band_for_khz_hf():
    assert band_for_khz(14025.0) == "20m"
    assert band_for_khz(7005.0) == "40m"
    assert band_for_khz(3573.0) == "80m"
    assert band_for_khz(28400.0) == "10m"
    assert band_for_khz(50130.0) == "6m"

def test_band_for_khz_out_of_band_returns_none():
    assert band_for_khz(12345.0) is None

def test_mode_from_comment_keywords():
    assert mode_for_khz_comment(14074.0, "FT8 -12 dB") == "FT8"
    assert mode_for_khz_comment(14025.0, "CW") == "CW"
    assert mode_for_khz_comment(14200.0, "59 SSB") == "SSB"

def test_mode_falls_back_to_band_plan_segment():
    assert mode_for_khz_comment(14025.0, "") == "CW"
    assert mode_for_khz_comment(14250.0, "") == "SSB"

def test_band_for_khz_boundaries():
    assert band_for_khz(14000.0) == "20m"
    assert band_for_khz(14350.0) is None
    assert band_for_khz(29700.0) is None

def test_psk31_not_shadowed_by_psk():
    assert mode_for_khz_comment(14070.0, "PSK31 dx") == "PSK31"

def test_usb_lsb_normalise_to_ssb():
    assert mode_for_khz_comment(14200.0, "USB") == "SSB"
    assert mode_for_khz_comment(7100.0, "LSB") == "SSB"

def test_mode_returns_none_when_unclassifiable():
    assert mode_for_khz_comment(12345.0, "") is None
