"""Phase 1d: empty slice, params applied to a streamed DB-miss result, telemetry/summary DB path."""
import asyncio
import json
from unittest.mock import patch

import pytest
from django.conf import settings
from django.http import StreamingHttpResponse
from rest_framework.test import APIClient

from api.trackmap.telemetry_params import apply_to_stream, parse_options

from .telemetry_fixture import R, Y, seed

BASE = f"/api/analysis/races/{Y}/{R}/telemetry"


@pytest.fixture
def client():
    c = APIClient()
    c.credentials(HTTP_X_API_KEY=str(settings.INTERNAL_API_KEY))
    return c


# --- 1. empty slice ----------------------------------------------------------------

def test_empty_slice_is_200_with_empty_data_not_a_task(client, db):
    seed()
    with patch("api.services.nonblocking.TaskManager.enqueue_if_needed") as enq, \
         patch("api.services.analysis.TaskManager", create=True) as enq2:
        rows = client.get(f"{BASE}/?driver=VER&lap=3&start_m=9000&end_m=9500")
        col = client.get(f"{BASE}/?driver=VER&lap=3&start_m=9000&end_m=9500&format=columnar&channels=speed,drs")
        ov = client.get(f"{BASE}/overlay/?driver_a=VER&driver_b=NOR&lap_a=3&lap_b=3&start_m=9000&end_m=9500")
        ovc = client.get(f"{BASE}/overlay/?driver_a=VER&driver_b=NOR&lap_a=3&lap_b=3&start_m=9000&end_m=9500&format=columnar&channels=speed")
    assert rows.status_code == 200 and rows.json()["data"] == [] and rows.json()["meta"]["row_count"] == 0
    assert col.status_code == 200
    assert col.json()["data"] == {k: [] for k in ("driver_code", "lap_number", "distance_m", "speed_kph", "drs")}
    assert [t["data"] for t in ov.json()["traces"]] == [[], []]
    assert ovc.status_code == 200 and all(t["data"]["speed_kph"] == [] for t in ovc.json()["traces"])
    enq.assert_not_called()
    enq2.enqueue_if_needed.assert_not_called()


def test_real_miss_still_enqueues(client, db):
    from rest_framework.response import Response

    with patch("api.services.nonblocking.TaskManager.get_existing_task", return_value=None), \
         patch("api.services.nonblocking.TaskManager.enqueue_if_needed") as enq, \
         patch("api.services.nonblocking.streaming.stream_task_result_json", return_value=Response({"s": 1})):
        client.get(f"{BASE}/?driver=VER&lap=3&start_m=1&end_m=2")
    keys = [c.args[0] if c.args else c.kwargs["task_key"] for c in enq.call_args_list]
    assert any(k.startswith("populate_telemetry:") for k in keys)


# --- 2. params applied to the streamed result ------------------------------------------

def _stream(payload):
    async def gen():
        yield json.dumps(payload)
    return StreamingHttpResponse(gen(), content_type="application/json")


def _read(resp):
    async def go():
        return b"".join([p async for p in resp.streaming_content])
    return json.loads(asyncio.run(go()))


ROWS = [
    {"driver_code": "VER", "lap_number": 3, "sector": 1, "time_seconds": 1.5, "distance_m": d,
     "speed_kph": 200.0 + d, "throttle_pct": 50.0, "brake": False, "rpm": 9000, "gear": 5}
    for d in (0.0, 500.0, 1000.0, 1500.0)
]


def test_streamed_snapshot_gets_slice_channels_and_columnar():
    payload = {"meta": {"row_count": 4}, "filters_applied": {"driver": "VER"}, "data": [dict(r) for r in ROWS]}
    o = parse_options({"start_m": "400", "end_m": "1200", "channels": "speed,time", "format": "columnar"})
    out = _read(apply_to_stream(_stream(payload), o))
    assert out["data"] == {"driver_code": ["VER", "VER"], "lap_number": [3, 3], "distance_m": [500.0, 1000.0],
                           "speed_kph": [700.0, 1200.0], "time_seconds": [1.5, 1.5]}
    assert out["meta"]["row_count"] == 2 and out["filters_applied"]["format"] == "columnar"


def test_streamed_overlay_and_passthrough():
    payload = {"meta": {"row_count": 8}, "filters_applied": {}, "traces": [{"driver": "VER", "lap": 3, "data": [dict(r) for r in ROWS]}] * 2}
    out = _read(apply_to_stream(_stream(payload), parse_options({"start_m": "900"})))
    assert [len(t["data"]) for t in out["traces"]] == [2, 2] and out["meta"]["row_count"] == 4
    # default options and non-result chunks come back untouched
    assert _read(apply_to_stream(_stream({"status": "timeout"}), parse_options({"start_m": "1"}))) == {"status": "timeout"}
    resp = _stream(payload)
    assert apply_to_stream(resp, parse_options({})) is resp


# --- 3. telemetry/summary DB path -------------------------------------------------------

def test_summary_serves_stored_telemetry(client, db):
    seed()
    r = client.get(f"{BASE}/summary/?driver=VER&lap=3")
    assert r.status_code == 200 and r["Content-Type"].startswith("application/json")
    body = r.json()
    assert body["meta"]["row_count"] == 1 and body["meta"]["limit_max"] >= 1
    s = body["summary"][0]
    assert s["driver_code"] == "VER" and s["lap_number"] == 3 and s["samples"] == 400
    assert s["max_speed_kph"] > 250 and s["braking_zones"] >= 1
    whole = client.get(f"{BASE}/summary/").json()
    assert len(whole["summary"]) == 4  # 2 drivers x 2 laps


def test_summary_worker_serializer_accepts_the_payload(db):
    from api.services.analysis import get_telemetry_summary
    from api.session.serializers import TelemetrySummaryResponseSerializer

    seed()
    data = TelemetrySummaryResponseSerializer(get_telemetry_summary(Y, R, "R", driver="VER")).data
    assert data["meta"]["limit_max"] >= 1 and len(data["summary"]) == 2
