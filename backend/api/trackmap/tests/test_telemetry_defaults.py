"""Golden snapshots: with none of the Phase 1c params the telemetry endpoints must return
the exact bytes they returned before Phase 1c. (telemetry/summary is left out and unchanged: its
DB path is already broken on master, `get_telemetry_summary` is never imported in session/views.py.) Snapshots in tests/golden/ were captured from
the unmodified views (set UPDATE_GOLDEN=1 only to deliberately re-capture)."""
import os
from pathlib import Path

import pytest
from django.conf import settings
from rest_framework.test import APIClient

from .telemetry_fixture import R, Y, seed

GOLDEN = Path(__file__).parent / "golden"
BASE = f"/api/analysis/races/{Y}/{R}/telemetry"

REQUESTS = {
    "lap": f"{BASE}/?driver=VER&lap=3",
    "driver_all_laps": f"{BASE}/?driver=NOR",
    "limit_points": f"{BASE}/?driver=VER&lap=2&limit_points=50",
    "stride": f"{BASE}/?driver=VER&lap=3&stride=4",
    "sector_window": f"{BASE}/?driver=VER&lap=3&sector_start=2&sector_end=2",
    "whole_session": f"{BASE}/?lap=3&limit_points=100",
    "overlay": f"{BASE}/overlay/?driver_a=VER&driver_b=NOR&lap_a=3&lap_b=3",
    "overlay_limited": f"{BASE}/overlay/?driver_a=VER&driver_b=NOR&limit_points=60",
}


@pytest.fixture
def client():
    c = APIClient()
    c.credentials(HTTP_X_API_KEY=str(settings.INTERNAL_API_KEY))
    return c


@pytest.mark.django_db
@pytest.mark.parametrize("name", sorted(REQUESTS))
def test_default_response_bytes_unchanged(client, name):
    seed()
    r = client.get(REQUESTS[name])
    assert r.status_code == 200
    path = GOLDEN / f"{name}.json"
    if os.environ.get("UPDATE_GOLDEN") == "1":
        path.write_bytes(r.content)
    assert path.exists(), "golden snapshot missing"
    assert r.content == path.read_bytes()


@pytest.mark.django_db
@pytest.mark.parametrize("name", sorted(REQUESTS))
def test_stored_time_channel_does_not_change_defaults(client, name):
    """Rows that carry the new elapsed_s array must produce the same default bytes."""
    seed(with_time=True)
    r = client.get(REQUESTS[name])
    assert r.content == (GOLDEN / f"{name}.json").read_bytes()
