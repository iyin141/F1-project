"""Phase 2a: label logic on synthetic stored rows (no network, no FastF1)."""
import pytest

from api.chaos import labels as L
from api.chaos.circuits import geometry_fields, load_seed, populate_circuit_profiles
from api.chaos.models import CircuitProfile, RaceEventLabel
from api.chaos.tasks import build_labels, label_aggregates
from api.models import IncidentData, PitStopData, PositionData, RaceResultData, TrackStatusData

SMAP = L.load_status_map()


def ts(*pairs):
    return [{"lap_number": lap, "status": st} for st, lap in pairs]


def rc(*pairs):
    return [{"lap_number": lap, "message_text": text, "flag": None} for text, lap in pairs]


# ---- DNF status mapping --------------------------------------------------------------------------------

@pytest.mark.parametrize("status,group", [
    ("Engine", "engine"), ("gearbox", "gearbox"), ("Hydraulics", "hydraulics"), ("Electrical", "electrical"),
    ("Brakes", "brakes"), ("Accident", "accident"), ("Collision", "collision"), ("Suspension", "chassis"), ("Mechanical", "chassis"), ("Technical", "chassis"),
    ("Fire", "chassis"), ("Withdrew", "other"),
    ("Retired", "other"), ("Finished", None), ("+1 Lap", None), ("+12 Laps", None), ("Lapped", None),
    ("Disqualified", None), ("Did not start", None),
])
def test_status_groups(status, group):
    assert L.classify_status(status, SMAP)[0] == group


def test_unknown_status_goes_to_other_and_is_flagged():
    assert L.classify_status("Gremlins", SMAP) == ("other", True)
    assert L.classify_status("", SMAP) == ("other", True)
    assert L.classify_status("Retired", SMAP) == ("other", False)
    assert L.classify_status("Withdrew", SMAP) == ("other", False)


def test_yaml_has_every_plan_group_and_version():
    assert {"engine", "gearbox", "hydraulics", "electrical", "brakes", "accident", "collision", "chassis"} <= set(SMAP["groups"])
    assert SMAP["fallback"] == "other" and SMAP["version"]


def test_dnf_labels_carry_version_lap_and_identity():
    res = [{"driver_number": 1, "team": "A", "status": "Finished", "laps": 50},
           {"driver_number": 2, "team": "B", "status": "Engine", "laps": 10},
           {"driver_number": 3, "team": "C", "status": "Gremlins", "laps": 0}]
    out = L.dnf_labels(2024, 3, res, {2: "BBB"}, 50, SMAP)
    assert [(o["type"], o["driver"], o["lap"]) for o in out] == [("dnf_engine", "BBB", 11), ("dnf_other", "#3", 1)]
    assert {o["mapping_version"] for o in out} == {str(SMAP["version"])}
    assert out[1]["detail"]["unmapped"] is True


# ---- SC / VSC / red ----------------------------------------------------------------------------------

def test_sc_vsc_red_from_track_status():
    ev, notes = L.neutral_events(ts(("1", 1), ("4", 10), ("1", 13), ("6", 20), ("7", 21), ("1", 22), ("5", 30), ("1", 33)), [])
    assert [(e["type"], e["lap"], e["end_lap"]) for e in ev] == [("sc", 10, 13), ("vsc", 20, 21), ("red_flag", 30, 33)]


def test_double_safety_car_is_two_events():
    ev, _ = L.neutral_events(ts(("4", 5), ("1", 8), ("2", 9), ("4", 12), ("1", 15)), [])
    assert [e["type"] for e in ev] == ["sc", "sc"]
    assert [e["lap"] for e in ev] == [5, 12]


def test_red_flag_then_restart_behind_sc_is_one_red_one_sc():
    ev, _ = L.neutral_events(ts(("5", 20), ("4", 22), ("1", 25)), [])
    assert [(e["type"], e["lap"], e["end_lap"]) for e in ev] == [("red_flag", 20, 22), ("sc", 22, 25)]


def test_repeated_status_not_double_counted_and_names_accepted():
    ev, _ = L.neutral_events(ts(("4", 5), ("4", 6), ("AllClear", 8)), [])
    assert len(ev) == 1
    ev, _ = L.neutral_events(ts(("SCDeployed", 5), ("AllClear", 8)), [])
    assert ev[0]["type"] == "sc"


def test_laps_fall_back_to_race_control_when_track_status_has_none():
    msgs = rc(("SAFETY CAR DEPLOYED", 7), ("SAFETY CAR IN THIS LAP", 10), ("VIRTUAL SAFETY CAR DEPLOYED", 30),
              ("VIRTUAL SAFETY CAR ENDING", 31), ("RED FLAG", 40))
    ev, notes = L.neutral_events(ts(("4", None), ("1", None), ("6", None), ("7", None), ("5", None)), msgs)
    got = {e["type"]: (e["lap"], e["end_lap"], e["source"]) for e in ev}
    assert got == {"sc": (7, 10, "track_status+race_control"), "vsc": (30, 31, "track_status+race_control"),
                   "red_flag": (40, 40, "track_status+race_control")}
    assert notes == []


def test_vsc_message_is_not_counted_as_sc():
    assert L._rc_marks(rc(("VIRTUAL SAFETY CAR DEPLOYED", 3)))["sc"] == []


def test_crosscheck_mismatch_reported_and_track_status_kept():
    ev, notes = L.neutral_events(ts(("4", 5), ("1", 8)), rc(("SAFETY CAR DEPLOYED", 5), ("SAFETY CAR DEPLOYED", 20)))
    assert len(ev) == 1 and ev[0]["source"] == "track_status" and "sc: track_status=1 race_control=2" in notes[0]


def test_race_control_only_when_no_track_status():
    ev, _ = L.neutral_events([], rc(("SAFETY CAR DEPLOYED", 9)))
    assert [(e["type"], e["lap"], e["source"]) for e in ev] == [("sc", 9, "race_control")]


# ---- pit stops ---------------------------------------------------------------------------------------

def stop(code, lap, dur=22.0, n=1):
    return {"driver_code": code, "lap_in": lap, "stop_duration_seconds": dur, "stop_number": n}


def test_season_threshold_needs_enough_stops():
    assert L.season_threshold([22.0] * 10) is None
    t = L.season_threshold([float(x) for x in range(1, 101)])
    assert 90 <= t <= 91.5


def test_slow_stop_above_threshold_only():
    out = L.pit_labels(2024, 1, [stop("AAA", 10, 30.0), stop("BBB", 11, 21.0)], [], 25.0, {"AAA": "T"})
    assert [(o["type"], o["driver"], o["team"]) for o in out] == [("slow_stop", "AAA", "T")]
    assert L.pit_labels(2024, 1, [stop("AAA", 10, 30.0)], [], None, {}) == []


def test_unlucky_stop_within_two_laps_under_green():
    neutral, _ = L.neutral_events(ts(("4", 12), ("1", 15)), [])
    stops = [stop("A", 10), stop("B", 11), stop("C", 12), stop("D", 9), stop("E", 14)]
    out = L.pit_labels(2024, 1, stops, neutral, None, {})
    assert sorted(o["driver"] for o in out if o["type"] == "unlucky_stop") == ["A", "B", "C"]  # D too early, E during SC
    assert next(o for o in out if o["driver"] == "A")["detail"] == {"followed_by": "sc", "laps_before": 2, "stop_number": 1}


def test_pit_during_sc_is_neither_unlucky_nor_after_it():
    neutral, _ = L.neutral_events(ts(("4", 5), ("1", 9), ("4", 10), ("1", 12)), [])
    out = L.pit_labels(2024, 1, [stop("A", 7), stop("B", 8)], neutral, None, {})
    # lap 8 is under the first SC (5..9), so green-stop test fails even though the second SC starts at 10
    assert [o["driver"] for o in out] == []


def test_stop_on_red_flag_lap_is_not_slow():
    neutral, _ = L.neutral_events(ts(("5", 20), ("1", 24)), [])
    assert L.pit_labels(2024, 1, [stop("A", 21, 90.0)], neutral, 25.0, {}) == []


def test_unlucky_stop_after_vsc_counts_but_red_does_not():
    n, _ = L.neutral_events(ts(("6", 12), ("7", 13), ("1", 14)), [])
    assert len(L.pit_labels(2024, 1, [stop("A", 11)], n, None, {})) == 1
    n, _ = L.neutral_events(ts(("5", 12), ("1", 14)), [])
    assert L.pit_labels(2024, 1, [stop("A", 11)], n, None, {}) == []


# ---- aggregation -------------------------------------------------------------------------------------

def test_aggregate_race_driver_window():
    ev = [{"type": "sc", "lap": 7, "driver": ""}, {"type": "dnf_engine", "lap": 3, "driver": "AAA"},
          {"type": "dnf_collision", "lap": 3, "driver": "BBB"}, {"type": "dnf_other", "lap": 4, "driver": "CCC"},
          {"type": "unlucky_stop", "lap": 5, "driver": "AAA"}, {"type": "slow_stop", "lap": None, "driver": "AAA"}]
    agg = L.aggregate_labels(ev, 12, ["DDD"], SMAP)
    assert agg["race"] == {"sc_vsc_red": 1, "dnf_mechanical": 1, "dnf_incident": 1, "slow_stop": 1, "unlucky_stop": 1}
    assert agg["drivers"]["AAA"]["dnf_mechanical"] == 1 and agg["drivers"]["DDD"]["slow_stop"] == 0
    assert [w["window"] for w in agg["windows"]] == [1, 2, 3]
    assert agg["windows"][0]["dnf_mechanical"] == 1 and agg["windows"][0]["unlucky_stop"] == 1
    assert agg["windows"][1]["sc_vsc_red"] == 1 and agg["windows"][2]["lap_end"] == 12
    assert sum(w["slow_stop"] for w in agg["windows"]) == 0  # lap unresolved: in race/driver, not in a window


# ---- build_labels task (DB) -------------------------------------------------------------------------

def seed_race(year=2024, rnd=5, with_season_stops=True):
    RaceResultData.objects.create(year=year, round_number=rnd, session="R", payload={"results": [
        {"driver_number": 1, "team": "RB", "status": "Finished", "laps": 20},
        {"driver_number": 4, "team": "MCL", "status": "+1 Lap", "laps": 19},
        {"driver_number": 11, "team": "RB", "status": "Engine", "laps": 8},
        {"driver_number": 16, "team": "FER", "status": "Collision", "laps": 2},
        {"driver_number": 77, "team": "MER", "status": "Gremlins", "laps": 12}]})
    TrackStatusData.objects.create(year=year, round_number=rnd, session="R", payload={"data": ts(
        ("1", None), ("4", None), ("1", None))})
    IncidentData.objects.create(year=year, round_number=rnd, session="R", payload={"data": rc(
        ("SAFETY CAR DEPLOYED", 10), ("SAFETY CAR IN THIS LAP", 12))})
    stops = [{"driver_code": c, "driver_number": n, "lap_in": lap, "stop_duration_seconds": d, "stop_number": 1}
             for c, n, lap, d in [("VER", 1, 9, 21.0), ("NOR", 4, 8, 40.0), ("HAM", 44, 15, 22.0)]]
    PitStopData.objects.create(year=year, round_number=rnd, session="R", payload={"data": stops})
    PositionData.objects.create(year=year, round_number=rnd, session="R", payload={"data": [
        {"driver_code": "PER", "driver_number": 11, "lap_number": 5}, {"driver_code": "LEC", "driver_number": 16, "lap_number": 5}]})
    if with_season_stops:  # other rounds so the season p90 exists
        PitStopData.objects.create(year=year, round_number=rnd + 1, session="R", payload={"data": [
            {"driver_code": "X", "lap_in": 10, "stop_duration_seconds": 20.0 + i * 0.1} for i in range(40)]})


@pytest.mark.django_db
def test_build_labels_end_to_end_and_idempotent():
    seed_race()
    r1 = build_labels(2024, 5)
    assert r1["status"] == "ok" and r1["unmapped_statuses"] == ["Gremlins"] and r1["crosscheck_mismatches"] == []
    snap = lambda: sorted(RaceEventLabel.objects.values_list("type", "lap", "driver", "team", "source", "mapping_version"))  # noqa: E731
    first = snap()
    r2 = build_labels(2024, 5)
    assert snap() == first and r1["labels"] == r2["labels"] == len(first)

    by = {(t, d): (lap, src, mv) for t, lap, d, _, src, mv in first}
    assert by[("sc", "")] == (10, "track_status+race_control", "")
    assert by[("dnf_engine", "PER")] == (9, "results", "2")
    assert by[("dnf_collision", "LEC")][0] == 3
    assert by[("dnf_other", "#77")][0] == 13  # unknown status kept as `other`, driver code unresolved
    assert ("slow_stop", "NOR") in by and ("slow_stop", "VER") not in by  # 40 s > season p90, 21 s is not
    assert by[("unlucky_stop", "VER")][0] == 9 and by[("unlucky_stop", "NOR")][0] == 8  # 1 and 2 laps before SC at 10
    assert ("unlucky_stop", "HAM") not in by  # lap 15, after the SC


@pytest.mark.django_db
def test_build_labels_does_not_touch_other_races_and_handles_no_results():
    RaceEventLabel.objects.create(year=2024, round_number=9, type="sc", source="x")
    assert build_labels(2024, 5)["status"] == "no_results"
    seed_race()
    build_labels(2024, 5)
    assert RaceEventLabel.objects.filter(round_number=9).count() == 1


@pytest.mark.django_db
def test_label_aggregates_from_stored_labels():
    seed_race()
    build_labels(2024, 5)
    agg = label_aggregates(2024, 5)
    assert agg["race"]["sc_vsc_red"] == 1 and agg["race"]["dnf_mechanical"] == 1 and agg["race"]["dnf_incident"] == 1
    assert [w["window"] for w in agg["windows"]] == [1, 2, 3, 4]  # 20 laps / 5


# ---- CircuitProfile ----------------------------------------------------------------------------------

def test_seed_has_no_invented_numbers():
    seed = load_seed()
    assert len(seed) >= 25 and len({c["slug"] for c in seed}) == len(seed)
    assert all(c["circuit_type"] in ("street", "permanent", "hybrid") for c in seed)
    assert not any({"wall_proximity", "overtaking_index", "elevation_range_m", "length_m"} & set(c) for c in seed)


@pytest.mark.django_db
def test_circuit_profile_populates_from_geometry():
    from api.trackmap.models import TrackGeometry

    TrackGeometry.objects.create(circuit_key=22, year=2024, layout_hash="a", points={"distance": [0.0, 1500.0, 3337.0]},
                                 corners=[{"number": i} for i in range(1, 20)])
    assert geometry_fields(22) == {"length_m": 3337.0, "corners": 19}
    assert geometry_fields(999) == {}
    seed = [{"slug": "monaco", "name": "Monaco", "locations": ["Monte Carlo"], "circuit_type": "street", "circuit_key": 22},
            {"slug": "x", "name": "X", "locations": [], "circuit_type": None}]
    assert populate_circuit_profiles(seed) == 2 and populate_circuit_profiles(seed) == 2
    m = CircuitProfile.objects.get(slug="monaco")
    assert (m.length_m, m.corners, m.wall_proximity) == (3337.0, 19, None)
    assert CircuitProfile.objects.count() == 2


# ---- Mendeley cross-check script (pure part; the real run is DEFERRED) --------------------------------

def test_crosscheck_compare():
    import pandas as pd

    from api.chaos.scripts import crosscheck_mendeley as m

    df = pd.DataFrame({"Year": [2023] * 6, "Round": [1] * 3 + [2] * 3, "LapNumber": [1, 2, 3, 1, 2, 3],
                       "SafetyCar": [0, 1, 1, 0, 0, 0]})
    theirs = m.dataset_laps(df, "Year", "Round", "LapNumber", "SafetyCar")
    assert theirs == {(2023, 1): {2, 3}, (2023, 2): set()}
    ours = {(2023, 1): m.our_laps([("sc", 2, 4), ("vsc", 9, 9)], {"sc"}), (2023, 2): set()}
    rep = m.compare(theirs, ours)
    assert (rep["precision"], rep["recall"]) == (0.6667, 1.0) and rep["races"] == 2


@pytest.mark.django_db
def test_link_circuit_keys_from_trackmap_pointer():
    from django.core.cache import caches

    from api.chaos.circuits import link_circuit_keys
    from api.models import SeasonSchedule
    from api.trackmap.models import TrackGeometry
    from api.trackmap.service import built_key

    TrackGeometry.objects.create(circuit_key=22, year=2024, layout_hash="a", points={"distance": [0.0, 3300.0]}, corners=[{}] * 19)
    SeasonSchedule.objects.create(year=2024, payload={"races": [{"round": 8, "location": "Monte Carlo"}, {"round": 9, "location": "Nowhere"}]})
    caches["telemetry_cache"].set(built_key(2024, 8), [22, "a"], timeout=None)
    populate_circuit_profiles([{"slug": "monaco", "name": "M", "locations": ["Monte Carlo"], "circuit_type": "street"}])
    assert link_circuit_keys(2024) == 1 and link_circuit_keys(2024) == 0  # idempotent
    m = CircuitProfile.objects.get(slug="monaco")
    assert (m.circuit_key, m.length_m, m.corners) == (22, 3300.0, 19)
