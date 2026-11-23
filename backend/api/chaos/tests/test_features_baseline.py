"""Phase 2b: features + Beta-Binomial baseline on synthetic multi-season fixtures (no network)."""
import copy
import random

import pandas as pd
import pytest

from api.chaos import baseline as B
from api.chaos import features as F
from api.chaos import history as H
from api.chaos import labels as L
from api.chaos.models import ChaosPrediction, CircuitProfile, FeatureSet, ModelRun, RaceEventLabel
from api.chaos.tasks import build_features, run_baseline
from api.models import PositionData, RaceResultData, SeasonSchedule

SMAP = L.load_status_map()
CIRCUITS = [("monaco", "street", 0.7), ("baku", "street", 0.5), ("spa", "permanent", 0.3), ("monza", "permanent", 0.1)]
DRIVERS = [("AAA", "T1"), ("BBB", "T1"), ("CCC", "T2"), ("DDD", "T2")]


def synth_events(rng, ctype, p_sc, total):
    ev = []
    if rng.random() < p_sc:
        lap = rng.randint(2, total - 6)
        ev.append({"type": "sc", "driver": "", "lap": lap, "end_lap": lap + 3})
    for code, _ in DRIVERS:
        if rng.random() < 0.15:
            ev.append({"type": "dnf_engine", "driver": code, "lap": rng.randint(1, total), "end_lap": None})
        if rng.random() < 0.10:
            ev.append({"type": "dnf_collision", "driver": code, "lap": rng.randint(1, total), "end_lap": None})
        if rng.random() < 0.20:
            ev.append({"type": "slow_stop", "driver": code, "lap": rng.randint(5, total - 5), "end_lap": None})
    return ev


def make_race(year, rnd, circuit, ctype, events, total=30, lane=(22.0, 23.0)):
    drivers = {c: {"team": t, "grid": i + 1} for i, (c, t) in enumerate(DRIVERS)}
    return {"year": year, "round": rnd, "circuit": circuit, "ctype": ctype, "location": circuit,
            "profile": {"length_m": 5000.0, "corners": 15}, "total_laps": total, "drivers": drivers,
            "weather": {"track_temp_c": 30.0, "rain_frac": 0.0},
            "agg": L.aggregate_labels(events, total, list(drivers), SMAP),
            "events": [e for e in events if e["type"] in L.NEUTRAL], "lane": list(lane), "_ev": events}


def synth_races(seasons=(2020, 2021, 2022, 2023), seed=3):
    rng, races = random.Random(seed), []
    for y in seasons:
        for rnd, (circ, ct, p) in enumerate(CIRCUITS, 1):
            races.append(make_race(y, rnd, circ, ct, synth_events(rng, ct, p, 30)))
    return races


# ---- leakage ---------------------------------------------------------------------------------------------

def tables_upto(races, n):
    return F.build_tables(races[:n])


def rebuild_with_flipped_labels(races, idx):
    out = copy.deepcopy(races)
    r = out[idx]
    ev = [] if r["_ev"] else [{"type": "sc", "driver": "", "lap": 5, "end_lap": 8}] + \
        [{"type": f"dnf_{g}", "driver": c, "lap": 4, "end_lap": None} for c in ("AAA", "BBB") for g in ("engine", "collision")]
    out[idx] = make_race(r["year"], r["round"], r["circuit"], r["ctype"], ev, lane=(99.0, 99.0))
    return out


@pytest.mark.parametrize("idx", [0, 5, 14])
def test_features_never_see_the_race_itself_or_later_races(idx):
    races = synth_races()
    base, changed = F.build_tables(races), F.build_tables(rebuild_with_flipped_labels(races, idx))
    key = (races[idx]["year"], races[idx]["round"])
    for scope in base:
        b, c = base[scope], changed[scope]
        g = F.column_groups(b)
        feat = [c for c in g["feature"] + g["id"] if c not in g["live_only"]]  # live-only = the race's own in-race info
        upto = (b["id_year"] * 100 + b["id_round"]) <= key[0] * 100 + key[1]
        pd.testing.assert_frame_equal(b.loc[upto, feat].reset_index(drop=True), c.loc[upto, feat].reset_index(drop=True))
    later = base["race"].index[(base["race"]["id_year"] * 100 + base["race"]["id_round"]) > key[0] * 100 + key[1]]
    if len(later):  # sanity: the change IS visible to later races, so the equality above is a real test
        feat = F.column_groups(base["race"])["feature"]
        assert not base["race"].loc[later, feat].equals(changed["race"].loc[later, feat])


def test_first_race_has_only_the_uninformative_prior():
    t = F.build_tables(synth_races())
    first = t["race"].iloc[0]
    assert first["prior_races"] == 0 and first["glob_sc_vsc_red"] == 0.5 and first["circ_sc_vsc_red"] == 0.5
    assert pd.isna(first["circuit_lane_rel"])
    assert t["driver"].iloc[0]["drv_slow_stop"] == 0.5


def test_pit_lane_relative_feature_uses_earlier_races_only():
    races = [make_race(2020, 1, "a", "street", [], lane=(20.0,)), make_race(2020, 2, "b", "street", [], lane=(30.0,)),
             make_race(2021, 1, "a", "street", [], lane=(20.0,))]
    t = F.build_tables(races)["race"]
    assert pd.isna(t.loc[0, "circuit_lane_rel"]) and pd.isna(t.loc[1, "circuit_lane_rel"])
    assert t.loc[2, "circuit_lane_rel"] == pytest.approx(20.0 / 25.0)  # circuit a median 20 / global median of (20, 30)


# ---- table shape -------------------------------------------------------------------------------------------

def test_feature_columns_are_numeric_and_limits_hold():
    for scope, df in F.build_tables(synth_races()).items():
        g = F.column_groups(df)
        assert all(pd.api.types.is_numeric_dtype(df[c]) for c in g["feature"] + g["target"]), scope
        F.check_limits(scope, df)
        assert not any(c.startswith("id_") for c in g["feature"])
    with pytest.raises(ValueError):
        F.check_limits("x", pd.DataFrame({f"c{i}": [0] for i in range(101)}))


def test_era_flag_one_hot_window_and_live_flags():
    t = F.build_tables(synth_races())
    assert set(t["race"].groupby("year")["era_2022"].first()) == {0, 1}
    assert t["race"].query("year < 2022")["era_2022"].eq(0).all()
    w = t["lap_window"]
    assert w.query("window == 1")["first_window"].eq(1).all() and w.query("window > 1")["first_window"].eq(0).all()
    assert (t["race"][[f"circuit_is_{x}" for x in F.TYPES]].sum(axis=1) == 1).all()
    assert F.column_groups(w)["live_only"] == ["live_restart_flag"]
    sc = make_race(2020, 1, "a", "street", [{"type": "sc", "driver": "", "lap": 3, "end_lap": 12}])
    wf = F.build_tables([sc])["lap_window"]
    assert list(wf["live_restart_flag"]) == [0, 0, 1, 0, 0, 0]  # SC ends lap 12 -> window 3
    assert wf["y_sc_vsc_red"].tolist() == [1, 0, 0, 0, 0, 0]


# ---- shrinkage ----------------------------------------------------------------------------------------------

def _hist(circuit_counts):
    """circuit_counts: {circuit: (n_races, n_with_sc)}, all of type street."""
    races, rnd = [], 1
    for circ, (n, k) in circuit_counts.items():
        for i in range(n):
            ev = [{"type": "sc", "driver": "", "lap": 5, "end_lap": 8}] if i < k else []
            races.append(make_race(2020 + i, rnd, circ, "street", ev))
        rnd += 1
    return sorted(races, key=H.race_key)


def rate(history, target):
    c = H.Counts()
    for r in history:
        c.update(r)
    return c.rate("race", "sc_vsc_red", H.race_chain(target))[0]


def test_small_sample_circuit_is_pulled_toward_its_type():
    target = {"circuit": "tiny", "ctype": "street"}
    others = {"b1": (10, 2), "b2": (10, 2), "b3": (10, 2)}  # street type rate ~ 20 %
    type_rate = rate(_hist(others), {"circuit": "none", "ctype": "street"})
    one = rate(_hist({**others, "tiny": (1, 1)}), target)       # 1 race, 1 SC: raw 100 %
    many = rate(_hist({**others, "tiny": (40, 40)}), target)    # 40 of 40: raw 100 %
    assert type_rate < one < 0.5, (type_rate, one)               # barely moved off the type rate
    assert one < many and many > 0.8                             # data wins as the sample grows
    # unknown circuit type falls back to global; never errors
    assert 0 < rate(_hist(others), {"circuit": "new", "ctype": None}) < 1


def test_driver_rate_shrinks_to_team_then_global():
    hist = [make_race(2020, i, "c", "street", [{"type": "dnf_engine", "driver": "AAA", "lap": 5, "end_lap": None}]) for i in range(1, 4)]
    c = H.Counts()
    for r in hist:
        c.update(r)
    drv = c.rate("drv", "dnf_mechanical", H.drv_chain("AAA", "T1"))[0]
    mate = c.rate("drv", "dnf_mechanical", H.drv_chain("BBB", "T1"))[0]
    other_team = c.rate("drv", "dnf_mechanical", H.drv_chain("CCC", "T2"))[0]
    assert drv > mate > other_team  # teammate shares some of the team's record, other team shares none


# ---- predictions ----------------------------------------------------------------------------------------------

def test_predictions_are_probabilities_with_ordered_bands():
    races = synth_races()
    preds = B.predict(races[:-1], races[-1], n_windows=6, drivers=races[-1]["drivers"])
    assert {p["scope"] for p in preds} == {"race", "driver", "lap_window"}
    assert len(preds) == 5 + 4 * 4 + 6 * 5
    for p in preds:
        assert 0 <= p["p10"] <= p["probability"] <= p["p90"] <= 1, p
    assert {p["target"] for p in preds if p["scope"] == "driver"} == set(H.DRIVER_TARGETS)


def test_more_history_narrows_the_band():
    races = synth_races()
    width = lambda n: next(p["p90"] - p["p10"] for p in B.predict(races[:n], races[n], 0, {}) if p["target"] == "sc_vsc_red")  # noqa: E731
    assert width(14) < width(2)


# ---- DB tasks ----------------------------------------------------------------------------------------------

def seed_db(races):
    CircuitProfile.objects.bulk_create([CircuitProfile(slug=c, name=c, locations=[c], circuit_type=t) for c, t, _ in CIRCUITS])
    by_year = {}
    for r in races:
        by_year.setdefault(r["year"], []).append({"round": r["round"], "location": r["circuit"]})
        RaceResultData.objects.create(year=r["year"], round_number=r["round"], session="R", payload={"results": [
            {"driver_number": i + 1, "team": d["team"], "status": "Finished", "laps": r["total_laps"], "grid_position": d["grid"]}
            for i, d in enumerate(r["drivers"].values())]})
        PositionData.objects.create(year=r["year"], round_number=r["round"], session="R", payload={"data": [  # number -> code
            {"driver_code": c, "driver_number": i + 1} for i, c in enumerate(r["drivers"])]})
    for y, rs in by_year.items():
        SeasonSchedule.objects.create(year=y, payload={"races": rs})
    for r in races:
        RaceEventLabel.objects.bulk_create([RaceEventLabel(year=r["year"], round_number=r["round"], source="t", **{
            k: e[k] for k in ("type", "driver", "lap", "end_lap")}) for e in r["_ev"]])


@pytest.mark.django_db
def test_build_features_writes_parquet_registers_and_is_idempotent(tmp_path, monkeypatch):
    monkeypatch.setenv("CHAOS_FEATURES_DIR", str(tmp_path))
    races = synth_races()
    seed_db(races)
    r1 = build_features()
    assert r1["status"] == "ok" and set(r1["rows"]) == {"race", "driver", "lap_window"}
    assert r1["rows"]["race"] == len(races) and r1["rows"]["driver"] == len(races) * 4
    files = sorted(p.name for p in tmp_path.iterdir())
    assert len(files) == 3 and all(f.endswith(".parquet") for f in files)
    fs = FeatureSet.objects.get(scope="race")
    df = pd.read_parquet(fs.path)
    assert fs.row_count == len(df) and fs.columns == list(df.columns) and fs.version == r1["version"]
    assert fs.meta["target"] and fs.meta["feature"] and fs.meta["mapping_version"] == "2"
    # the DB path reproduces the pure tables (circuit type, history) from stored rows
    pure = F.build_tables(races)["race"]
    assert df["glob_sc_vsc_red"].tolist() == pytest.approx(pure["glob_sc_vsc_red"].tolist())
    assert df["circuit_is_street"].tolist() == pure["circuit_is_street"].tolist()
    r2 = build_features()
    assert r2 == r1 and FeatureSet.objects.count() == 3 and sorted(p.name for p in tmp_path.iterdir()) == files
    pd.testing.assert_frame_equal(pd.read_parquet(fs.path), df)


@pytest.mark.django_db
def test_build_features_default_dir_is_outside_the_repo(monkeypatch):
    from pathlib import Path

    from api.chaos.tasks import features_dir

    monkeypatch.delenv("CHAOS_FEATURES_DIR", raising=False)
    monkeypatch.delenv("DATA_DIR", raising=False)
    d = features_dir().resolve()
    assert Path(__file__).resolve().parents[3] not in d.parents and d.name == "chaos_features"


@pytest.mark.django_db
def test_run_baseline_past_and_upcoming_race_and_idempotent():
    races = synth_races()
    seed_db(races)
    last = races[-1]
    r1 = run_baseline(last["year"], last["round"])
    assert r1["status"] == "ok" and r1["history_races"] == len(races) - 1
    n = ChaosPrediction.objects.count()
    assert n == 5 + 4 * 4 + 6 * 5 and ModelRun.objects.get().model == "beta_binomial"
    snap = sorted(ChaosPrediction.objects.values_list("scope", "entity", "target", "probability", "p10", "p90"))
    r2 = run_baseline(last["year"], last["round"])
    assert r2["predictions"] == r1["predictions"] and ModelRun.objects.count() == 1 and ChaosPrediction.objects.count() == n
    assert sorted(ChaosPrediction.objects.values_list("scope", "entity", "target", "probability", "p10", "p90")) == snap
    # upcoming race: schedule row, no results yet -> uses the latest field and median length
    SeasonSchedule.objects.filter(year=2024).delete()
    SeasonSchedule.objects.create(year=2024, payload={"races": [{"round": 1, "location": "monaco"}]})
    up = run_baseline(2024, 1)
    assert up["status"] == "ok" and ModelRun.objects.count() == 2
    assert run_baseline(2019, 1)["status"] == "no_history"
    assert all(0 <= p.p10 <= p.probability <= p.p90 <= 1 for p in ChaosPrediction.objects.all())


@pytest.mark.django_db
def test_baseline_ignores_later_races_in_the_db():
    races = synth_races()
    seed_db(races)
    run_baseline(2021, 3)
    snap = sorted(ChaosPrediction.objects.values_list("scope", "entity", "target", "probability"))
    RaceEventLabel.objects.filter(year__gte=2022).delete()  # remove the future: prediction must not change
    run_baseline(2021, 3)
    assert sorted(ChaosPrediction.objects.values_list("scope", "entity", "target", "probability")) == snap
