"""Phase 1e: per-session build fallback and the failure status."""
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from django.conf import settings
from django.core.cache import caches
from rest_framework.test import APIClient

from api.trackmap import service
from api.trackmap.models import TrackGeometry
from api.trackmap.tasks import TrackBuildError, build_track_geometry

from .test_geometry import fake_session, make_tel

Y, R = 2025, 5
BASE = f"/api/analysis/races/{Y}/{R}"


class DataNotLoadedError(Exception):
    pass


def empty_session():
    """Loads fine but holds no laps: what FastF1 gives when livetiming returns 401."""
    def boom():
        raise DataNotLoadedError("The data you are trying to access has not been loaded yet")
    return SimpleNamespace(laps=SimpleNamespace(pick_fastest=boom))


def no_fastest_session():
    return SimpleNamespace(laps=SimpleNamespace(pick_fastest=lambda: None))


@pytest.fixture
def client():
    c = APIClient()
    c.credentials(HTTP_X_API_KEY=str(settings.INTERNAL_API_KEY))
    return c


def sessions(**by_type):
    def get(year, rnd, st, required_types=None):
        v = by_type.get(st)
        if isinstance(v, Exception):
            raise v
        if v is None:
            raise ValueError(f"no session {st}")
        return v
    return get


@pytest.mark.django_db
def test_falls_back_to_race_when_qualifying_loads_without_laps():
    caches["telemetry_cache"].clear()
    get = sessions(Q=empty_session(), R=fake_session(make_tel()))
    with patch("api.trackmap.tasks.SessionManager.get_session", side_effect=get) as gs:
        r = build_track_geometry.delay(Y, R).get()
    assert r["status"] == "created" and r["session"] == "R"
    assert [c.args[2] for c in gs.call_args_list] == ["Q", "SQ", "R"]  # SQ does not exist: skipped, R used
    assert "R R" not in TrackGeometry.objects.get().source and " R " in TrackGeometry.objects.get().source


@pytest.mark.django_db
def test_no_fastest_lap_and_sprint_qualifying_fallback():
    caches["telemetry_cache"].clear()
    get = sessions(Q=no_fastest_session(), SQ=fake_session(make_tel()))
    with patch("api.trackmap.tasks.SessionManager.get_session", side_effect=get):
        assert build_track_geometry.delay(Y, R).get()["session"] == "SQ"


@pytest.mark.django_db
def test_all_sessions_unusable_records_failure_and_raises():
    caches["telemetry_cache"].clear()
    get = sessions(Q=empty_session(), R=no_fastest_session())
    with patch("api.trackmap.tasks.SessionManager.get_session", side_effect=get):
        with pytest.raises(TrackBuildError) as e:
            build_track_geometry.delay(Y, R).get()
    assert "Q: DataNotLoadedError" in str(e.value) and "R: ValueError" in str(e.value)
    f = service.get_failure(Y, R)
    assert f and "DataNotLoadedError" in f["reason"] and 0 < f["retry_after"] <= service.FAILURE_TTL


@pytest.mark.django_db
def test_success_clears_recorded_failure():
    caches["telemetry_cache"].clear()
    service.record_failure(Y, R, "earlier failure")
    with patch("api.trackmap.tasks.SessionManager.get_session", side_effect=sessions(Q=fake_session(make_tel()))):
        build_track_geometry.delay(Y, R).get()
    assert service.get_failure(Y, R) is None


@pytest.mark.django_db
@pytest.mark.parametrize("path", ["/track-map/", "/mini-sectors/?drivers=VER", "/telemetry/delta/?ref=VER&cmp=NOR"])
def test_recent_failure_gives_503_with_reason_and_retry_after_without_enqueue(client, path):
    caches["telemetry_cache"].clear()
    service.record_failure(Y, R, "Q: DataNotLoadedError: no laps")
    with patch("api.trackmap.views.TaskManager.enqueue_if_needed") as enq, \
         patch("api.trackmap.tasks.SessionManager.get_session", side_effect=AssertionError("FastF1 called")):
        r = client.get(BASE + path)
    assert r.status_code == 503
    body = r.json()
    assert body["status"] == "failed" and "DataNotLoadedError" in body["reason"]
    assert int(r["Retry-After"]) == body["retry_after"] and 0 < body["retry_after"] <= service.FAILURE_TTL
    enq.assert_not_called()


@pytest.mark.django_db
def test_after_failure_expires_request_enqueues_again(client):
    caches["telemetry_cache"].clear()
    with patch("api.trackmap.views.TaskManager.enqueue_if_needed") as enq:
        assert client.get(BASE + "/track-map/").status_code == 202
    enq.assert_called_once()
