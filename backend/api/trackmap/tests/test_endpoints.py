"""Phase 1b: track-map, mini-sectors and delta endpoints on synthetic fixtures (no network)."""
from unittest.mock import patch

import numpy as np
import pytest
from django.conf import settings
from django.core.cache import caches
from rest_framework.test import APIClient

from api.models import DriverTelemetry
from api.session.views import AnalysisTelemetryAPIView
from api.trackmap import service
from api.trackmap.tasks import build_track_geometry, populate_track_geometry
from api.trackmap.views import MiniSectorsAPIView, TelemetryDeltaAPIView, TrackMapAPIView

from .test_geometry import fake_session, make_tel

Y, R = 2025, 5
BASE = f"/api/analysis/races/{Y}/{R}"
LAP_M = float(make_tel()["Distance"].iloc[-1])  # synthetic lap length, metres


@pytest.fixture
def client():
    c = APIClient()
    c.credentials(HTTP_X_API_KEY=str(settings.INTERNAL_API_KEY))
    return c


@pytest.fixture
def built(db):
    caches["telemetry_cache"].clear()
    with patch("api.trackmap.tasks.SessionManager.get_session", return_value=fake_session(make_tel())):
        build_track_geometry.delay(Y, R).get()


def lap_payload(speed_fn, n=600):
    d = np.linspace(0, LAP_M, n)
    return {"distance": d.tolist(), "speed": [speed_fn(x / LAP_M) for x in d]}


def put_driver(code, speed_fn, lap=5, session="R"):
    DriverTelemetry.objects.create(
        year=Y, round_number=R, session=session, driver_code=code,
        payload={str(lap): lap_payload(speed_fn), "1": {"distance": [0, 10], "speed": [50, 60]}},  # lap 1 unusable
    )


def lap_seconds(speed_fn):
    return float(np.trapezoid([1 / (speed_fn(f) / 3.6) for f in np.linspace(0, 1, 5000)], np.linspace(0, LAP_M, 5000)))


VER = lambda f: 200.0  # noqa: E731
NOR = lambda f: 250.0 if f < 0.5 else 160.0  # noqa: E731  faster first half, slower second


@pytest.fixture
def drivers(built):
    put_driver("VER", VER)
    put_driver("NOR", NOR)


# --- track-map -------------------------------------------------------------------

def test_track_map_happy_path_both_schemes(client, built):
    r = client.get(f"{BASE}/track-map/")
    assert r.status_code == 200
    body = r.json()
    assert len(body["points"]["x"]) == 1500 and set(body["points"]) == {"x", "y", "z", "distance"}
    assert body["meta"]["scheme"] == "distance" and len(body["mini_sectors"]["boundaries"]) == 26
    assert len(body["corners"]) == 4 and len(body["drs_zones"]) == 2
    c = client.get(f"{BASE}/track-map/?scheme=corners").json()
    assert c["meta"]["scheme"] == "corners" and len(c["mini_sectors"]["boundaries"]) == 5
    assert c["mini_sectors"]["labels"] == ["T1", "T2", "T3A", "T4"]


def test_track_map_reads_db_when_cache_payload_evicted(client, built):
    cache = caches["telemetry_cache"]
    ptr = cache.get(service.built_key(Y, R))
    cache.delete(service.geometry_cache_key(*ptr))
    assert client.get(f"{BASE}/track-map/").status_code == 200
    assert cache.get(service.geometry_cache_key(*ptr))  # re-warmed from the DB


def test_track_map_not_built_is_fast_202_and_never_touches_fastf1(client, db):
    caches["telemetry_cache"].clear()
    with patch("api.trackmap.views.TaskManager.enqueue_if_needed") as enq,          patch("api.trackmap.tasks.SessionManager.get_session", side_effect=AssertionError("FastF1 called in request")) as gs,          patch("fastf1.get_session", side_effect=AssertionError("FastF1 called in request"), create=True):
        r = client.get(f"{BASE}/track-map/?scheme=corners")
    assert r.status_code == 202 and r.json()["status"] == "pending"
    args, kwargs = enq.call_args
    assert args[0] == f"track_map:{Y}:{R}:corners" and args[1] is populate_track_geometry
    assert args[2:] == (Y, R) and kwargs == {"scheme": "corners"}
    gs.assert_not_called()


def test_populate_job_publishes_track_map_response(db):
    caches["telemetry_cache"].clear()
    with patch("api.trackmap.tasks.SessionManager.get_session", return_value=fake_session(make_tel())), \
         patch("api.services.worker_utils.handle_result") as hr:
        populate_track_geometry.apply(args=(f"track_map:{Y}:{R}:corners", Y, R), kwargs={"scheme": "corners"}).get()
    data = hr.call_args.kwargs["serialized_data"]
    assert data["meta"]["scheme"] == "corners" and len(data["points"]["x"]) == 1500


# --- mini-sectors ----------------------------------------------------------------

def test_mini_sectors_sum_to_lap_time(client, drivers):
    body = client.get(f"{BASE}/mini-sectors/?drivers=VER,NOR").json()
    assert body["meta"]["sector_count"] == 25
    for code, fn in (("VER", VER), ("NOR", NOR)):
        d = body["drivers"][code]
        assert d["lap_number"] == 5 and len(d["sector_times"]) == 25
        assert sum(d["sector_times"]) == pytest.approx(d["lap_time"], abs=0.03)
        assert d["lap_time"] == pytest.approx(lap_seconds(fn), rel=0.01)


def test_mini_sectors_use_official_lap_time_when_available(client, drivers):
    with patch("api.trackmap.service._official_times", return_value={5: 90.0}):
        body = client.get(f"{BASE}/mini-sectors/?drivers=VER").json()
    d = body["drivers"]["VER"]
    assert d["lap_time"] == 90.0 and d["lap_time_source"] == "official"
    assert sum(d["sector_times"]) == pytest.approx(90.0, abs=0.03)


def test_mini_sectors_fastest_driver_and_gaps(client, drivers):
    body = client.get(f"{BASE}/mini-sectors/?drivers=VER,NOR&lap=5&scheme=corners").json()
    assert body["meta"]["sector_count"] == 4 and body["labels"] == ["T1", "T2", "T3A", "T4"]
    fastest = [s["driver"] for s in body["fastest_per_sector"]]
    assert fastest[0] == "NOR" and fastest[-1] == "VER"  # NOR quicker in the first half only
    for i, s in enumerate(body["fastest_per_sector"]):
        assert body["gaps"][s["driver"]][i] == 0
        other = "VER" if s["driver"] == "NOR" else "NOR"
        assert body["gaps"][other][i] > 0


def test_mini_sectors_pending_when_geometry_missing(client, db):
    caches["telemetry_cache"].clear()
    with patch("api.trackmap.views.TaskManager.enqueue_if_needed") as enq:
        r = client.get(f"{BASE}/mini-sectors/?drivers=VER")
    assert r.status_code == 202 and r.json()["status"] == "pending"
    enq.assert_called_once()


def test_mini_sectors_404_without_telemetry(client, built):
    r = client.get(f"{BASE}/mini-sectors/?drivers=VER")
    assert r.status_code == 404 and "VER" in r.json()["error"]


# --- delta -----------------------------------------------------------------------

def test_delta_on_common_grid(client, drivers):
    body = client.get(f"{BASE}/telemetry/delta/?ref=VER&cmp=NOR").json()
    assert len(body["distance"]) == len(body["delta"]) == 1500
    assert body["delta"][0] == pytest.approx(0, abs=1e-6)
    assert body["delta"][-1] == pytest.approx(body["cmp"]["lap_time"] - body["ref"]["lap_time"], abs=0.01)
    assert min(body["delta"]) < -0.5  # NOR pulls ahead in the first half...
    assert body["delta"][-1] > 0  # ...and ends the lap behind
    assert body["meta"]["delta_sign"].startswith("positive")


def test_delta_pending_when_geometry_missing(client, db):
    caches["telemetry_cache"].clear()
    with patch("api.trackmap.views.TaskManager.enqueue_if_needed"):
        assert client.get(f"{BASE}/telemetry/delta/?ref=VER&cmp=NOR").status_code == 202


# --- bad params -----------------------------------------------------------------

@pytest.mark.parametrize("path", [
    "/track-map/?scheme=bogus",
    "/mini-sectors/",
    "/mini-sectors/?drivers=VERSTAPPEN",
    "/mini-sectors/?drivers=VER,,NOR",
    "/mini-sectors/?drivers=VER&lap=abc",
    "/mini-sectors/?drivers=VER&lap=0",
    "/mini-sectors/?drivers=VER&scheme=x",
    "/mini-sectors/?drivers=VER&session=ZZ",
    "/telemetry/delta/?ref=VER",
    "/telemetry/delta/?cmp=NOR",
    "/telemetry/delta/?ref=VER&cmp=N0R",
    "/telemetry/delta/?ref=VER&cmp=NOR&lap=-3",
])
def test_bad_params_return_400(client, drivers, path):
    r = client.get(BASE + path)
    assert r.status_code == 400 and "error" in r.json()


# --- auth / throttle parity with an existing analysis view -------------------------

@pytest.mark.parametrize("view", [TrackMapAPIView, MiniSectorsAPIView, TelemetryDeltaAPIView])
def test_view_classes_match_existing_analysis_view(view):
    ref = AnalysisTelemetryAPIView
    assert view.authentication_classes == ref.authentication_classes
    assert view.permission_classes == ref.permission_classes
    assert view.throttle_classes == ref.throttle_classes
    assert [c.__name__ for c in view.throttle_classes] == ["APIKeyThrottle"]


@pytest.mark.parametrize("path", ["/track-map/", "/mini-sectors/?drivers=VER", "/telemetry/delta/?ref=VER&cmp=NOR", "/laps/"])
def test_requests_without_api_key_are_rejected_like_existing_views(db, path):
    r = APIClient().get(BASE + path)
    assert r.status_code in (401, 403)
    # same status as the existing laps view
    assert r.status_code == APIClient().get(BASE + "/laps/").status_code
