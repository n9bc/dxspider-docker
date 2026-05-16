from app.dxcc import resolve


def test_resolve_simple():
    r = resolve("W1AW")
    assert r.entity == "United States" and r.continent == "NA"


def test_resolve_uses_longest_prefix():
    assert resolve("VP8LP").entity == "Falkland Islands"
    assert resolve("VK9XX").continent == "OC"


def test_resolve_strips_common_portable_suffix():
    assert resolve("G3XYZ/P").entity == "England"
    assert resolve("W1AW/4").entity == "United States"


def test_resolve_handles_portable_prefix():
    assert resolve("F/G3XYZ").continent == "EU"
    assert resolve("F/G3XYZ").entity == "France"


def test_maritime_aeronautical_mobile_is_unknown():
    assert resolve("DL1ABC/MM").entity is None
    assert resolve("DL1ABC/MM").continent is None
    assert resolve("W1XYZ/AM").entity is None


def test_unknown_returns_none_entity():
    assert resolve("").entity is None
    assert resolve("12345").entity is None
