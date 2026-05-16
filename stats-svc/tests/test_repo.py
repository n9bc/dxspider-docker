import datetime as dt
from app.repo import MemoryRepo
from app.parsers import SpotRecord, ConnectedUser

def _spot(**kw):
    base = dict(kind="spot", spotter="K1ABC", dx_call="JA1XYZ", freq_khz=14025.0,
               band="20m", mode="CW", source="human", spotter_dxcc="United States",
               spotter_continent="NA", dx_dxcc="Japan", dx_continent="AS",
               comment="", when_z="1234Z", raw="raw")
    base.update(kw); return SpotRecord(**base)

async def test_insert_and_count_spot():
    r = MemoryRepo()
    ts = dt.datetime(2026,5,16,12,30, tzinfo=dt.timezone.utc)
    await r.insert_spot(_spot(), ts)
    assert await r.spot_count() == 1

async def test_rollup_incremented_on_insert():
    r = MemoryRepo()
    ts = dt.datetime(2026,5,16,12,5, tzinfo=dt.timezone.utc)
    await r.insert_spot(_spot(band="20m", mode="CW", source="human"), ts)
    await r.insert_spot(_spot(band="20m", mode="CW", source="human"),
                        dt.datetime(2026,5,16,12,55, tzinfo=dt.timezone.utc))
    rows = await r.rollup_rows()
    hour = dt.datetime(2026,5,16,12,0, tzinfo=dt.timezone.utc)
    match = [x for x in rows if x["hour_ts"]==hour and x["band"]=="20m"
             and x["mode"]=="CW" and x["source"]=="human"]
    assert len(match) == 1 and match[0]["count"] == 2

async def test_replace_connected_users_is_replace_all():
    r = MemoryRepo()
    snap = dt.datetime(2026,5,16,12,0, tzinfo=dt.timezone.utc)
    await r.replace_connected_users([ConnectedUser("K1ABC","USER"),
                                     ConnectedUser("G7XYZ","NODE")], snap)
    await r.replace_connected_users([ConnectedUser("W1AW","USER")],
                                    dt.datetime(2026,5,16,12,1, tzinfo=dt.timezone.utc))
    users = await r.connected_users()
    assert {u["callsign"] for u in users} == {"W1AW"}

async def test_backfill_dedup_skips_duplicate():
    r = MemoryRepo()
    ts = dt.datetime(2026,5,16,12,0, tzinfo=dt.timezone.utc)
    s = _spot()
    assert await r.insert_spot_dedup(s, ts) is True
    assert await r.insert_spot_dedup(s, ts) is False
    assert await r.spot_count() == 1

async def test_rollup_coalesces_none_keys():
    r = MemoryRepo()
    ts = dt.datetime(2026,5,16,12,0, tzinfo=dt.timezone.utc)
    await r.insert_spot(_spot(band=None, mode=None, dx_dxcc=None,
                              dx_continent=None, spotter_dxcc=None), ts)
    await r.insert_spot(_spot(band=None, mode=None, dx_dxcc=None,
                              dx_continent=None, spotter_dxcc=None),
                        dt.datetime(2026,5,16,12,30, tzinfo=dt.timezone.utc))
    rows = await r.rollup_rows()
    merged = [x for x in rows if x["hour_ts"]==ts and x["band"]==""
              and x["dx_dxcc"]==""]
    assert len(merged) == 1 and merged[0]["count"] == 2
