"""Phase 2f: circuit matching, aliases for the 2022-2026 calendars, automatic linking, list endpoint, loud logging."""
import logging
from unittest.mock import patch

import pytest
from django.conf import settings
from django.core.cache import caches
from rest_framework.test import APIClient

from api.chaos import circuits as CI
from api.chaos import history as H
from api.chaos.models import CircuitProfile
from api.chaos.tasks import build_features
from api.chaos.tests.test_features_baseline import seed_db, synth_races
from api.models import SeasonSchedule
from api.trackmap.models import TrackGeometry

INDEX = CI.CircuitIndex({c["slug"]: c for c in CI.load_seed()})


# ---- every seeded alias matches its own circuit (one case per alias) ------------------------------------------------------

ALIASES = [(a, c["slug"]) for c in CI.load_seed() for a in c["locations"]]


@pytest.mark.parametrize("alias,slug", ALIASES)
def test_every_alias_matches_its_circuit_as_location_and_as_event_name(alias, slug):
    assert INDEX.match(location=alias)[0]["slug"] == slug
    assert INDEX.match(name=alias)[0]["slug"] == slug


def test_seed_aliases_do_not_collide_between_circuits():
    seen = {}
    for c in CI.load_seed():
        for a in [*c["locations"], c["name"]]:
            n = CI.norm(a)
            assert seen.setdefault(n, c["slug"]) == c["slug"], f"alias {a!r} used by {seen[n]} and {c['slug']}"


# ---- the (location, event name) pairs FastF1 stores, 2022-2026 ---------------------------------------------------------------

CALENDAR = [
    ("Sakhir", "Bahrain Grand Prix", "bahrain"), ("Jeddah", "Saudi Arabian Grand Prix", "jeddah"),
    ("Melbourne", "Australian Grand Prix", "melbourne"), ("Imola", "Emilia Romagna Grand Prix", "imola"),
    ("Miami", "Miami Grand Prix", "miami"), ("Miami Gardens", "Miami Grand Prix", "miami"),
    ("Barcelona", "Spanish Grand Prix", "barcelona"), ("Monaco", "Monaco Grand Prix", "monaco"),
    ("Baku", "Azerbaijan Grand Prix", "baku"), ("Montréal", "Canadian Grand Prix", "montreal"), ("Montreal", "Canadian Grand Prix", "montreal"),
    ("Silverstone", "British Grand Prix", "silverstone"), ("Spielberg", "Austrian Grand Prix", "red-bull-ring"),
    ("Le Castellet", "French Grand Prix", "paul-ricard"), ("Budapest", "Hungarian Grand Prix", "hungaroring"),
    ("Spa-Francorchamps", "Belgian Grand Prix", "spa"), ("Zandvoort", "Dutch Grand Prix", "zandvoort"),
    ("Monza", "Italian Grand Prix", "monza"), ("Marina Bay", "Singapore Grand Prix", "singapore"),
    ("Suzuka", "Japanese Grand Prix", "suzuka"), ("Lusail", "Qatar Grand Prix", "lusail"),
    ("Austin", "United States Grand Prix", "cota"), ("Mexico City", "Mexico City Grand Prix", "mexico-city"),
    ("Mexico City", "Mexican Grand Prix", "mexico-city"), ("São Paulo", "São Paulo Grand Prix", "interlagos"),
    ("Sao Paulo", "Brazilian Grand Prix", "interlagos"), ("Las Vegas", "Las Vegas Grand Prix", "las-vegas"),
    ("Yas Island", "Abu Dhabi Grand Prix", "yas-marina"), ("Yas Marina", "Abu Dhabi Grand Prix", "yas-marina"),
    ("Shanghai", "Chinese Grand Prix", "shanghai"),
    # 2026: Madrid joins and Barcelona gets its own event name; the location decides, not "Spanish Grand Prix"
    ("Madrid", "Spanish Grand Prix", "madrid"), ("Barcelona", "Barcelona-Catalunya Grand Prix", "barcelona"),
    ("Montmeló", "Spanish Grand Prix", "barcelona"),
]


@pytest.mark.parametrize("location,name,slug", CALENDAR)
def test_calendar_pairs_match(location, name, slug):
    p, how = INDEX.match(location, name)
    assert p["slug"] == slug and how


def test_event_name_alone_and_contained_aliases_match():
    assert INDEX.match(None, "Hungarian Grand Prix")[0]["slug"] == "hungaroring"
    assert INDEX.match("Autodromo Hermanos Rodriguez, Mexico City", "")[0]["slug"] == "mexico-city"
    assert INDEX.match("", "FORMULA 1 MIAMI GRAND PRIX 2026")[0]["slug"] == "miami"
    assert INDEX.match("MONTRÉAL ", None)[0]["slug"] == "montreal"  # case, accents, whitespace


def test_unknown_and_ambiguous_texts_do_not_match():
    assert INDEX.match("Nowhere", "Moon Grand Prix") == (None, None)
    assert INDEX.match(None, None) == (None, None)
    assert INDEX.match("", "") == (None, None)
    two = CI.CircuitIndex({"a": {"slug": "a", "name": "A", "locations": ["Twin City"]}, "b": {"slug": "b", "name": "B", "locations": ["Twin City"]}})
    assert two.match("Twin City") == (None, None)  # a shared alias never guesses


# ---- race_meta and the loud log -------------------------------------------------------------------------------------------------

@pytest.mark.django_db
def test_race_meta_matches_schedule_row_and_flags_unmatched_loudly(caplog):
    SeasonSchedule.objects.create(year=2026, payload={"races": [
        {"round": 5, "name": "Miami Grand Prix", "location": "Miami Gardens"},
        {"round": 6, "name": "Moon Grand Prix", "location": "Tranquility Base"}]})
    idx = H.circuit_lookup()
    ok = H.race_meta(2026, 5, idx)
    assert ok["circuit"] == "miami" and ok["ctype"] == "street" and ok["circuit_matched"] is True
    H._WARNED.clear()
    with caplog.at_level(logging.WARNING, logger="api.chaos.history"):
        bad = H.race_meta(2026, 6, idx)
        missing = H.race_meta(2026, 9, idx)
        H.race_meta(2026, 6, idx)  # same race again: warned once per process, not per request
    assert bad["circuit_matched"] is False and bad["circuit"] == "Tranquility Base" and bad["ctype"] is None
    assert missing["circuit"] == "unknown" and missing["circuit_matched"] is False
    msgs = [r.getMessage() for r in caplog.records if "UNMATCHED CIRCUIT" in r.getMessage()]
    assert len(msgs) == 2 and "Tranquility Base" in msgs[0] and "no schedule row" in msgs[1]


@pytest.mark.django_db
def test_build_features_reports_unmatched_circuits(tmp_path, monkeypatch, caplog):
    monkeypatch.setenv("CHAOS_FEATURES_DIR", str(tmp_path))
    races = synth_races()
    seed_db(races)
    SeasonSchedule.objects.filter(year=2023).update(payload={"races": [{"round": r, "location": "Mystery Park"} for r in range(1, 5)]})
    H._WARNED.clear()
    with caplog.at_level(logging.WARNING, logger="api.chaos"):
        res = build_features()
    assert [u["location"] for u in res["unmatched_circuits"]] == ["Mystery Park"] * 4
    assert any("have NO matching circuit" in r.getMessage() for r in caplog.records)


# ---- linking --------------------------------------------------------------------------------------------------------------------------

def schedule_2026():
    SeasonSchedule.objects.create(year=2026, payload={"races": [{"round": 5, "name": "Miami Grand Prix", "location": "Miami Gardens"}]})


@pytest.mark.django_db
def test_geometry_post_save_links_circuit_key_length_and_corners(django_capture_on_commit_callbacks):
    schedule_2026()
    with django_capture_on_commit_callbacks(execute=True):
        TrackGeometry.objects.create(circuit_key=151, year=2026, layout_hash="h", source="2026 R5 Q pole lap",
                                     points={"distance": [0.0, 2500.0, 5412.0]}, corners=[{}] * 19)
    p = CircuitProfile.objects.get(slug="miami")  # created from the seed: no prior populate step needed
    assert (p.circuit_key, p.length_m, p.corners, p.circuit_type) == (151, 5412.0, 19, "street")


@pytest.mark.django_db
def test_linking_runs_on_a_real_track_map_build(django_capture_on_commit_callbacks):
    from api.trackmap.tasks import build_track_geometry
    from api.trackmap.tests.test_geometry import fake_session, make_tel

    caches["telemetry_cache"].clear()
    schedule_2026()
    with patch("api.trackmap.tasks.SessionManager.get_session", return_value=fake_session(make_tel(), circuit_key=151)), \
            django_capture_on_commit_callbacks(execute=True):
        build_track_geometry.delay(2026, 5).get()
    p = CircuitProfile.objects.get(slug="miami")
    assert p.circuit_key == 151 and p.length_m and p.corners  # trackmap's real `source` format is understood


@pytest.mark.django_db
def test_unmatched_geometry_and_conflicts_are_logged_not_fatal(django_capture_on_commit_callbacks, caplog):
    SeasonSchedule.objects.create(year=2026, payload={"races": [{"round": 5, "name": "Moon Grand Prix", "location": "Tranquility Base"},
                                                                {"round": 6, "name": "Miami Grand Prix", "location": "Miami"}]})
    with caplog.at_level(logging.WARNING, logger="api.chaos"), django_capture_on_commit_callbacks(execute=True):
        TrackGeometry.objects.create(circuit_key=1, year=2026, layout_hash="a", source="2026 R5 Q x", points={"distance": [0, 1]}, corners=[])
        TrackGeometry.objects.create(circuit_key=151, year=2026, layout_hash="b", source="2026 R6 Q x", points={"distance": [0, 1]}, corners=[])
        TrackGeometry.objects.create(circuit_key=999, year=2026, layout_hash="c", source="2026 R6 Q y", points={"distance": [0, 1]}, corners=[])
        TrackGeometry.objects.create(circuit_key=5, year=2026, layout_hash="d", source="garbage", points={"distance": [0, 1]}, corners=[])
    text = " ".join(r.getMessage() for r in caplog.records)
    assert "UNMATCHED CIRCUIT for track geometry 1" in text and "already linked to key 151" in text
    assert CircuitProfile.objects.get(slug="miami").circuit_key == 151  # the first link stands


@pytest.mark.django_db
def test_build_features_backfills_links_and_profiles(tmp_path, monkeypatch):
    monkeypatch.setenv("CHAOS_FEATURES_DIR", str(tmp_path))
    seed_db(synth_races())
    SeasonSchedule.objects.create(year=2026, payload={"races": [{"round": 5, "name": "Miami Grand Prix", "location": "Miami Gardens"}]})
    TrackGeometry.objects.create(circuit_key=151, year=2026, layout_hash="h", source="2026 R5 Q x",
                                 points={"distance": [0.0, 5000.0]}, corners=[{}] * 17)  # created with no signal run
    res = build_features()
    assert res["circuit_links_made"] >= 1
    p = CircuitProfile.objects.get(slug="miami")
    assert (p.circuit_key, p.length_m, p.corners) == (151, 5000.0, 17)
    assert CircuitProfile.objects.count() >= 32  # seed populated by the pipeline itself
    assert build_features()["circuit_links_made"] == 0  # idempotent


# ---- list endpoint --------------------------------------------------------------------------------------------------------------------------

@pytest.fixture
def client():
    caches["default"].clear()
    c = APIClient()
    c.credentials(HTTP_X_API_KEY=str(settings.INTERNAL_API_KEY))
    return c


@pytest.mark.django_db
def test_circuit_list_endpoint_lists_slugs_names_and_aliases(client):
    d = client.get("/api/chaos/circuits/").json()
    assert d["count"] == len(d["circuits"]) >= 32 and d["history_url"].endswith("<slug>/history/")
    by = {c["slug"]: c for c in d["circuits"]}
    assert by["montreal"]["name"] == "Circuit Gilles Villeneuve" and "Canadian Grand Prix" in by["montreal"]["aliases"]
    assert by["madrid"]["type"] == "hybrid" and by["monaco"]["stored"] is False  # known from the seed before any DB row exists
    assert [c["slug"] for c in d["circuits"]] == sorted(by)
    # a listed slug is directly usable, even before its profile row exists
    r = client.get("/api/chaos/circuits/montreal/history/")
    assert r.status_code == 200 and r.json()["races"] == [] and r.json()["circuit"]["type"] == "hybrid"
    miss = client.get("/api/chaos/circuits/atlantis/history/")
    assert miss.status_code == 404 and "/api/chaos/circuits/" in miss.json()["error"]


@pytest.mark.django_db
def test_circuit_list_marks_stored_and_requires_the_key(client):
    CI.populate_circuit_profiles()
    d = client.get("/api/chaos/circuits/").json()
    assert all(c["stored"] for c in d["circuits"])
    assert APIClient().get("/api/chaos/circuits/").status_code in (401, 403)
