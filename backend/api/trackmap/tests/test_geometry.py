"""Phase 1a: geometry builder + build_track_geometry task, on synthetic telemetry (no network)."""
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest
from django.core.cache import caches

from api.trackmap import geometry as g
from api.trackmap.models import TrackGeometry
from api.trackmap.tasks import build_track_geometry, geometry_cache_key


def make_tel(n=900, a=9000.0, b=5000.0, jitter=0.0, with_drs=True):
    """Closed elliptical lap in 1/10 m units; Distance integrated from the path (metres)."""
    th = np.linspace(0, 2 * np.pi, n, endpoint=True)
    x, y = a * np.cos(th), b * np.sin(th)
    seg = np.hypot(np.diff(x), np.diff(y)) / 10.0
    dist = np.concatenate([[0.0], np.cumsum(seg)])
    rng = np.random.default_rng(1)
    x = x + rng.normal(0, jitter, n)
    drs = np.zeros(n, dtype=int)
    if with_drs:
        # two zones: 10-20 % and 60-62 % (the latter shorter than MIN_DRS_ZONE_M? no: ~ lap/50)
        drs[(dist > 0.10 * dist[-1]) & (dist < 0.20 * dist[-1])] = 12
        drs[(dist > 0.60 * dist[-1]) & (dist < 0.62 * dist[-1])] = 8  # eligible only, not open
        drs[(dist > 0.80 * dist[-1]) & (dist < 0.85 * dist[-1])] = 14
    return pd.DataFrame({"X": x, "Y": y, "Z": np.linspace(0, 30, n), "Distance": dist, "DRS": drs})


def make_corners(length):
    return pd.DataFrame({
        "X": [9000.0, 0.0, -9000.0, 0.0], "Y": [0.0, 5000.0, 0.0, -5000.0],
        "Number": [1, 2, 3, 4], "Letter": ["", "", "A", ""],
        "Angle": [0.0, 90.0, 180.0, 270.0],
        "Distance": [length * f for f in (0.05, 0.3, 0.55, 0.8)],
    })


def test_downsample_count_and_loop_closes():
    tel = make_tel()
    pts = g.downsample(tel)
    assert len(pts["x"]) == len(pts["y"]) == len(pts["z"]) == len(pts["distance"]) == g.N_POINTS
    step = (pts["distance"][-1] - pts["distance"][0]) / (g.N_POINTS - 1)
    gap_m = np.hypot(pts["x"][-1] - pts["x"][0], pts["y"][-1] - pts["y"][0]) / 10.0
    assert gap_m < 2 * step  # last point lands on the first: a closed loop
    # uniform grid
    assert np.allclose(np.diff(pts["distance"]), step, atol=0.02)


def test_mini_sector_boundaries_cover_lap():
    tel = make_tel()
    f = g.build_geometry(tel, make_corners(tel["Distance"].iloc[-1]))
    length = f["points"]["distance"][-1]
    eq = f["mini_sectors"]["distance"]["boundaries"]
    assert len(eq) == g.N_MINI_SECTORS + 1 and eq[0] == 0 and eq[-1] == pytest.approx(length, abs=0.01)
    assert np.allclose(np.diff(eq), length / g.N_MINI_SECTORS, atol=0.02)
    cb = f["mini_sectors"]["corners"]["boundaries"]
    assert cb[0] == 0 and cb[-1] == pytest.approx(length, abs=0.01) and cb == sorted(cb)
    assert len(cb) == len(f["corners"]) + 1
    # each corner sits inside its own sector
    for i, c in enumerate(f["corners"]):
        assert cb[i] <= c["distance"] <= cb[i + 1]
    assert f["mini_sectors"]["corners"]["labels"] == ["T1", "T2", "T3A", "T4"]


def test_drs_zones_from_channel():
    tel = make_tel()
    zones = g.drs_zones(tel)
    L = tel["Distance"].iloc[-1]
    assert len(zones) == 2  # DRS == 8 (eligible, not open) is ignored
    assert zones[0]["start_m"] == pytest.approx(0.10 * L, rel=0.02)
    assert zones[0]["end_m"] == pytest.approx(0.20 * L, rel=0.02)
    assert zones[1]["end_m"] == pytest.approx(0.85 * L, rel=0.02)
    assert g.drs_zones(make_tel(with_drs=False)) == []
    assert g.drs_zones(tel.drop(columns="DRS")) == []


def test_layout_hash_stable_and_discriminating():
    h1 = g.build_geometry(make_tel(), None)["layout_hash"]
    assert h1 == g.build_geometry(make_tel(), None)["layout_hash"]
    # sub-metre racing-line noise does not change it
    assert h1 == g.build_geometry(make_tel(jitter=0.5), None)["layout_hash"]
    # a different layout does
    assert h1 != g.build_geometry(make_tel(a=9000.0, b=3000.0), None)["layout_hash"]


class FakeLap(dict):
    def __init__(self, tel):
        super().__init__(Driver="VER")
        self._tel = tel

    def get_telemetry(self, **kw):
        return self._tel


def fake_session(tel, circuit_key=63):
    return SimpleNamespace(
        laps=SimpleNamespace(pick_fastest=lambda: FakeLap(tel)),
        get_circuit_info=lambda: SimpleNamespace(corners=make_corners(tel["Distance"].iloc[-1])),
        session_info={"Meeting": {"Circuit": {"Key": circuit_key}}},
    )


@pytest.mark.django_db
def test_task_is_idempotent_and_caches_permanently():
    caches["telemetry_cache"].clear()
    sess = fake_session(make_tel())
    with patch("api.trackmap.tasks.SessionManager.get_session", return_value=sess) as gs:
        r1 = build_track_geometry.delay(2025, 5).get()
        r2 = build_track_geometry.delay(2025, 5).get()
        assert gs.call_count == 1  # second call short-circuits before loading FastF1
        # same layout reached from another weekend reuses the row
        r3 = build_track_geometry.delay(2026, 5).get()
    assert (r1["status"], r2["status"], r3["status"]) == ("created", "exists", "exists")
    assert TrackGeometry.objects.count() == 1
    row = TrackGeometry.objects.get()
    assert (row.circuit_key, row.year, row.layout_hash) == (63, 2025, r1["layout_hash"])
    assert len(row.points["x"]) == g.N_POINTS and row.drs_zones and row.corners
    assert caches["telemetry_cache"].get(geometry_cache_key(63, row.layout_hash))


@pytest.mark.django_db
def test_task_rebuilds_row_if_db_lost_pointer_stale():
    caches["telemetry_cache"].clear()
    with patch("api.trackmap.tasks.SessionManager.get_session", return_value=fake_session(make_tel())):
        build_track_geometry.delay(2025, 5).get()
        TrackGeometry.objects.all().delete()
        assert build_track_geometry.delay(2025, 5).get()["status"] == "created"
