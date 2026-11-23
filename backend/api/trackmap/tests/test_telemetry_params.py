"""Phase 1c: start_m / end_m / channels / format on the existing telemetry endpoints, and the
stored time channel feeding mini-sectors and delta. Defaults are covered by test_telemetry_defaults."""
import numpy as np
import pytest
from django.conf import settings
from rest_framework.test import APIClient

from api.models import DriverTelemetry
from api.trackmap.telemetry_params import TelemetryOptions, parse_options

from .telemetry_fixture import LAP_LEN, R, Y, seed
from .test_endpoints import built  # noqa: F401  (geometry fixture for 2025 round 5)

BASE = f"/api/analysis/races/{Y}/{R}/telemetry"


@pytest.fixture
def client():
    c = APIClient()
    c.credentials(HTTP_X_API_KEY=str(settings.INTERNAL_API_KEY))
    return c


@pytest.fixture
def stored(db):
    seed(with_time=True)


# --- slicing ---------------------------------------------------------------------

def test_start_end_m_bounds(client, stored):
    full = client.get(f"{BASE}/?driver=VER&lap=3").json()["data"]
    body = client.get(f"{BASE}/?driver=VER&lap=3&start_m=1000&end_m=2000").json()
    dist = [r["distance_m"] for r in body["data"]]
    assert dist and min(dist) >= 1000 and max(dist) <= 2000
    assert body["meta"]["row_count"] == len(dist) == sum(1000 <= r["distance_m"] <= 2000 for r in full)
    assert body["filters_applied"]["start_m"] == 1000 and body["filters_applied"]["format"] == "rows"
    # sliced rows are the same rows, same keys, same values
    assert body["data"] == [r for r in full if 1000 <= r["distance_m"] <= 2000]
    only_start = client.get(f"{BASE}/?driver=VER&lap=3&start_m=4000").json()["data"]
    assert min(r["distance_m"] for r in only_start) >= 4000 and max(r["distance_m"] for r in only_start) == pytest.approx(LAP_LEN)
    only_end = client.get(f"{BASE}/?driver=VER&lap=3&end_m=500").json()["data"]
    assert max(r["distance_m"] for r in only_end) <= 500


def test_overlay_slicing_applies_to_both_traces(client, stored):
    body = client.get(f"{BASE}/overlay/?driver_a=VER&driver_b=NOR&lap_a=3&lap_b=3&start_m=2000&end_m=2500").json()
    assert len(body["traces"]) == 2
    for t in body["traces"]:
        assert t["data"] and all(2000 <= r["distance_m"] <= 2500 for r in t["data"])
    assert body["meta"]["row_count"] == sum(len(t["data"]) for t in body["traces"])


# --- channels --------------------------------------------------------------------

def test_channel_filtering(client, stored):
    rows = client.get(f"{BASE}/?driver=VER&lap=3&channels=speed,drs").json()["data"]
    assert len(rows) == 400
    assert set(rows[0]) == {"driver_code", "lap_number", "distance_m", "speed_kph", "drs"}
    assert {r["drs"] for r in rows} == {True, False}
    full = client.get(f"{BASE}/?driver=VER&lap=3").json()["data"]
    assert [r["speed_kph"] for r in rows] == [r["speed_kph"] for r in full]  # same values as default rows


def test_time_channel_only_via_channels(client, stored):
    default = client.get(f"{BASE}/?driver=VER&lap=3").json()["data"]
    assert all(r["time_seconds"] is None for r in default)  # unchanged: stored time is not leaked
    rows = client.get(f"{BASE}/?driver=VER&lap=3&channels=time").json()["data"]
    t = [r["time_seconds"] for r in rows]
    assert t[0] == 0 or t[0] > 0
    assert all(b >= a for a, b in zip(t, t[1:])) and t[-1] > 60


def test_time_channel_null_for_rows_stored_without_it(client, db):
    seed(with_time=False)
    rows = client.get(f"{BASE}/?driver=VER&lap=3&channels=time").json()["data"]
    assert all(r["time_seconds"] is None for r in rows)


def test_channels_work_for_overlay(client, stored):
    body = client.get(f"{BASE}/overlay/?driver_a=VER&driver_b=NOR&lap_a=3&lap_b=3&channels=brake,gear").json()
    for t in body["traces"]:
        assert set(t["data"][0]) == {"lap_number", "distance_m", "brake", "gear"}


# --- columnar --------------------------------------------------------------------

@pytest.mark.parametrize("extra", ["", "&channels=speed,throttle,brake,gear,rpm,drs,time", "&start_m=1500&end_m=3000", "&channels=speed&stride=3"])
def test_columnar_equals_rows_value_for_value(client, stored, extra):
    rows = client.get(f"{BASE}/?driver=NOR{extra}&format=rows").json()
    col = client.get(f"{BASE}/?driver=NOR{extra}&format=columnar").json()
    rdata, cdata = rows["data"], col["data"]
    assert isinstance(cdata, dict) and set(cdata) == set(rdata[0])
    assert col["meta"]["row_count"] == rows["meta"]["row_count"] == len(rdata)
    for k, values in cdata.items():
        assert values == [r[k] for r in rdata]
    # format=rows explicit is the same shape as default rows
    assert isinstance(rdata, list)


def test_columnar_overlay_equals_rows(client, stored):
    q = f"{BASE}/overlay/?driver_a=VER&driver_b=NOR&lap_a=3&lap_b=3&channels=speed,drs"
    rows, col = client.get(q).json(), client.get(q + "&format=columnar").json()
    for tr, tc in zip(rows["traces"], col["traces"]):
        for k, values in tc["data"].items():
            assert values == [r[k] for r in tr["data"]]


def test_columnar_payload_is_smaller(client, stored):
    q = f"{BASE}/?driver=VER&lap=3"
    assert len(client.get(q + "&format=columnar").content) < len(client.get(q).content)


# --- bad params ------------------------------------------------------------------

@pytest.mark.parametrize("qs", [
    "start_m=abc", "end_m=x", "start_m=-5", "end_m=nan", "start_m=2000&end_m=1000", "start_m=100&end_m=100",
    "channels=speed,bogus", "channels=", "channels=,", "format=xml", "format=",
])
def test_bad_params_return_400(client, stored, qs):
    for path in (f"{BASE}/?driver=VER&lap=3&{qs}",
                 f"{BASE}/overlay/?driver_a=VER&driver_b=NOR&{qs}"):
        r = client.get(path)
        if qs == "format=":  # empty format means default
            assert r.status_code == 200
            continue
        assert r.status_code == 400 and "error" in r.json()


def test_parse_options_and_cache_suffix():
    assert parse_options({}).is_default and parse_options({}).cache_suffix() == ""
    o = parse_options({"start_m": "10", "channels": "Speed, drs", "format": "columnar"})
    assert o == TelemetryOptions(10.0, None, ("speed", "drs"), True)
    assert o.cache_suffix() != parse_options({"start_m": "10"}).cache_suffix()


# --- stored time channel -> mini-sectors and delta -----------------------------------------

def _put_laps(code, lap_no, speed, elapsed_scale=None):
    from .test_endpoints import LAP_M

    d = np.linspace(0, LAP_M, 600)
    p = {"distance": d.tolist(), "speed": [speed(x / LAP_M) for x in d]}
    if elapsed_scale is not None:
        inv = 1 / (np.array(p["speed"]) / 3.6)
        t = np.concatenate([[0], np.cumsum(np.diff(d) * 0.5 * (inv[:-1] + inv[1:]))]) * elapsed_scale
        p["elapsed_s"] = t.tolist()
    DriverTelemetry.objects.create(year=2025, round_number=5, session="R", driver_code=code, payload={str(lap_no): p})
    return p


def test_mini_sectors_use_stored_time_and_report_source(client, built):  # noqa: F811
    base = "/api/analysis/races/2025/5"
    _put_laps("VER", 5, lambda f: 200.0, elapsed_scale=1.10)  # measured time 10 % longer than integrated
    _put_laps("NOR", 5, lambda f: 200.0)  # old row: no time channel
    body = client.get(f"{base}/mini-sectors/?drivers=VER,NOR").json()
    ver, nor = body["drivers"]["VER"], body["drivers"]["NOR"]
    assert ver["lap_time_source"] == "telemetry" and nor["lap_time_source"] == "integrated"
    assert ver["lap_time"] == pytest.approx(nor["lap_time"] * 1.10, rel=1e-3)  # stored time used, not re-integrated
    assert sum(ver["sector_times"]) == pytest.approx(ver["lap_time"], abs=0.03)
    # telemetry source takes priority over the lap table too
    from unittest.mock import patch
    with patch("api.trackmap.service._official_times", return_value={5: 77.0}):
        both = client.get(f"{base}/mini-sectors/?drivers=VER,NOR").json()["drivers"]
    assert both["VER"]["lap_time_source"] == "telemetry" and both["NOR"]["lap_time_source"] == "official"
    assert both["NOR"]["lap_time"] == 77.0


def test_delta_uses_stored_time(client, built):  # noqa: F811
    base = "/api/analysis/races/2025/5"
    _put_laps("VER", 5, lambda f: 200.0, elapsed_scale=1.0)
    _put_laps("NOR", 5, lambda f: 200.0, elapsed_scale=1.2)
    body = client.get(f"{base}/telemetry/delta/?ref=VER&cmp=NOR").json()
    assert body["ref"]["lap_time_source"] == body["cmp"]["lap_time_source"] == "telemetry"
    assert body["delta"][-1] == pytest.approx(0.2 * body["ref"]["lap_time"], rel=1e-2)


def test_populate_writes_elapsed_seconds_from_fastf1_time_column():
    import pandas as pd

    from api.management.commands.populate_telemetry import _elapsed_seconds

    tel = pd.DataFrame({"Time": pd.to_timedelta([5.0, 5.25, 5.5, 6.0], unit="s")})
    assert _elapsed_seconds(tel) == [0.0, 0.25, 0.5, 1.0]
    assert _elapsed_seconds(pd.DataFrame({"Speed": [1, 2]})) == []  # no Time column: key omitted by the caller
