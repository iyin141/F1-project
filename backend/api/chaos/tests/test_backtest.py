"""Phase 2d: leave-one-season-out backtest on synthetic multi-season data (no network, no optional deps)."""
import copy
import io
import json
import math

import numpy as np
import pandas as pd
import pytest
from django.core.management import call_command

from api.chaos import backtest as BT
from api.chaos import features as F
from api.chaos import metrics as Mx
from api.chaos import ml_tasks as M
from api.chaos.models import ChaosPrediction, ModelRun
from api.chaos.tasks import build_features
from api.chaos.tests.test_features_baseline import make_race, seed_db, synth_races


class RateModel(M.TabularModel):
    """Fake reference model: training positive rate. Records the training-set size."""

    seen = []

    def fit(self, X, y, num_estimators):
        self.r = (y.sum() + 1) / (len(y) + 2)
        RateModel.seen.append(len(X))

    def predict(self, X):
        return np.full(len(X), self.r)

    def clear(self):
        pass


@pytest.fixture(autouse=True)
def _reset():
    RateModel.seen = []


# ---- metrics against hand-computed values ---------------------------------------------------------------------------

def test_brier_and_log_loss_by_hand():
    assert Mx.brier([0.9, 0.2], [1, 0]) == pytest.approx((0.01 + 0.04) / 2)
    assert Mx.log_loss([0.9, 0.2], [1, 0]) == pytest.approx(-(math.log(0.9) + math.log(0.8)) / 2)
    assert math.isfinite(Mx.log_loss([0.0, 1.0], [1, 0]))  # clipped, not infinite


def test_auc_by_hand_ties_and_single_class():
    assert Mx.roc_auc([0.1, 0.4, 0.35, 0.8], [0, 0, 1, 1]) == pytest.approx(0.75)  # textbook example
    assert Mx.roc_auc([0.5, 0.5], [0, 1]) == 0.5
    assert Mx.roc_auc([0.1, 0.9], [0, 1]) == 1.0 and Mx.roc_auc([0.9, 0.1], [0, 1]) == 0.0
    assert Mx.roc_auc([0.3, 0.4], [1, 1]) is None and Mx.roc_auc([0.3, 0.4], [0, 0]) is None


def test_reliability_and_ece_by_hand():
    r = Mx.reliability([0.05, 0.05, 0.95, 0.95, 0.95, 0.95], [0, 1, 1, 1, 1, 0], bins=10)
    assert [b["n"] for b in r["bins"]] == [2, 4] and r["bins"][0]["frac_pos"] == 0.5 and r["bins"][1]["frac_pos"] == 0.75
    assert r["ece"] == pytest.approx(2 / 6 * 0.45 + 4 / 6 * 0.2, abs=1e-4)  # reported to 4 dp
    s = Mx.summarize([0.9, 0.2, 0.7], [1, 0, 1], with_reliability=True)
    assert s["n"] == 3 and s["base_rate"] == pytest.approx(2 / 3) and "ece" in s and s["auc"] == 1.0


# ---- splits leak nothing ------------------------------------------------------------------------------------------------

def relabel(races, year):
    """Same races, but every label of `year` flipped (events present <-> absent)."""
    out = []
    for r in races:
        if r["year"] != year:
            out.append(r)
            continue
        ev = [] if r["_ev"] else [{"type": "sc", "driver": "", "lap": 5, "end_lap": 8},
                                  {"type": "dnf_engine", "driver": "AAA", "lap": 4, "end_lap": None},
                                  {"type": "slow_stop", "driver": "BBB", "lap": 9, "end_lap": None}]
        out.append(make_race(r["year"], r["round"], r["circuit"], r["ctype"], ev, lane=(77.0, 88.0)))
    return out


def feature_cols(df):
    g = F.column_groups(df)
    return [c for c in g["feature"] + g["id"] if c not in g["live_only"]]


@pytest.mark.parametrize("held", [2020, 2021, 2022])
def test_held_out_season_never_reaches_any_feature_row(held):
    races = synth_races()
    a = F.build_tables(races, no_update=lambda r: r["year"] == held)
    b = F.build_tables(relabel(races, held), no_update=lambda r: r["year"] == held)
    for scope in a:
        cols = feature_cols(a[scope])
        # every row of every season, training AND held-out, is identical when the held-out labels change
        pd.testing.assert_frame_equal(a[scope][cols].reset_index(drop=True), b[scope][cols].reset_index(drop=True))
    # control: WITHOUT the guard the held season leaks into later seasons' history features
    c = F.build_tables(races)
    d = F.build_tables(relabel(races, held))
    later = c["race"]["id_year"] > held
    if later.any():
        assert not c["race"].loc[later, feature_cols(c["race"])].equals(d["race"].loc[later, feature_cols(d["race"])])


def test_tuned_prior_and_training_rows_ignore_held_out_labels():
    races = synth_races()
    m1, t1, _ = BT.tune_prior(races, 2021)
    m2, t2, _ = BT.tune_prior(relabel(races, 2021), 2021)
    assert m1 == m2
    tr = lambda t: t["race"][t["race"]["id_year"] != 2021].reset_index(drop=True)  # noqa: E731
    pd.testing.assert_frame_equal(tr(t1)[feature_cols(t1["race"])], tr(t2)[feature_cols(t2["race"])])
    # it does depend on the other seasons
    m3, _, _ = BT.tune_prior(relabel(races, 2020), 2021)
    assert m3 in BT.GRID


def test_models_train_on_every_other_season_and_test_on_the_held_one():
    races = synth_races()
    m, preds, skipped, _ = BT.run_fold(races, 2022, {"fake": RateModel})
    n_seasons = 3  # 2020, 2021, 2023 train
    assert set(RateModel.seen) == {4 * n_seasons, 4 * 4 * n_seasons, 4 * 6 * n_seasons} or all(
        n in (4 * n_seasons, 4 * 4 * n_seasons, 4 * 6 * n_seasons) for n in RateModel.seen)  # race / driver / window rows
    for (scope, tg), (p, y) in preds["fake"].items():
        base_p, base_y = preds[BT.BASELINE][(scope, tg)]
        assert len(p) == len(y) == len(base_p) and (y == base_y).all()  # identical held-out rows for every model
    assert len(preds["fake"][("race", "sc_vsc_red")][0]) == 4  # one held-out season = 4 races


def test_single_class_training_cell_is_skipped_for_every_model():
    races = synth_races()
    races = [make_race(r["year"], r["round"], r["circuit"], r["ctype"], [e for e in r["_ev"] if e["type"] != "sc"]) for r in races]
    _, preds, skipped, _ = BT.run_fold(races, 2022, {"fake": RateModel})
    assert "2022|race|sc_vsc_red" in skipped
    assert ("race", "sc_vsc_red") not in preds["fake"] and ("race", "sc_vsc_red") not in preds[BT.BASELINE]


# ---- report -------------------------------------------------------------------------------------------------------------------

def test_run_backtest_and_report_written(tmp_path):
    races = synth_races()
    rep = BT.run_backtest(races, {"fake": RateModel})
    assert rep["seasons"] == [2020, 2021, 2022, 2023] and rep["models"] == [BT.BASELINE, "fake"]
    assert set(rep["prior_strength"]) == {"2020", "2021", "2022", "2023"} and all(m in BT.GRID for m in rep["prior_strength"].values())
    cell = rep["results"]["fake"]["race|sc_vsc_red"]
    assert set(cell["per_season"]) == {"2020", "2021", "2022", "2023"} and cell["overall"]["n"] == 16
    assert 0 <= cell["overall"]["brier"] <= 1 and "bins" in cell["overall"] and "ece" in cell["overall"]
    assert {"brier", "log_loss", "auc", "n", "base_rate"} <= set(cell["per_season"]["2021"])
    paths = BT.write_report(rep, tmp_path / "bt")
    data = json.loads(open(paths["json"], encoding="utf-8").read())
    assert data["prior_strength"] == rep["prior_strength"]
    df = pd.read_csv(paths["csv"])
    assert {"model", "scope", "target", "season", "brier", "log_loss", "auc", "ece"} <= set(df.columns)
    assert set(df["season"].astype(str)) == {"all", "2020", "2021", "2022", "2023"}
    assert len(df) == sum(len(c["per_season"]) + 1 for m in rep["results"].values() for c in m.values())


@pytest.mark.django_db
def test_save_run_stores_metrics_and_reliability():
    rep = BT.run_backtest(synth_races(), {})
    rid = BT.save_run(rep)
    run = ModelRun.objects.get(id=rid)
    assert run.model == "backtest" and run.race_key == "loso-2020-2023"
    assert run.metrics["results"][BT.BASELINE] and run.calibration[BT.BASELINE]["race|sc_vsc_red"]["bins"]
    assert BT.save_run(rep) == rid and ModelRun.objects.filter(model="backtest").count() == 1


def test_needs_two_seasons():
    with pytest.raises(ValueError):
        BT.run_backtest([r for r in synth_races() if r["year"] == 2020], {})


def test_baseline_beats_nothing_claimed_but_probabilities_valid():
    rep = BT.run_backtest(synth_races(), {})
    for cell in rep["results"][BT.BASELINE].values():
        assert 0 <= cell["overall"]["brier"] <= 1 and cell["overall"]["log_loss"] > 0


# ---- optional dependencies ----------------------------------------------------------------------------------------------------

def test_missing_dependencies_skip_cleanly(monkeypatch):
    monkeypatch.setattr(BT, "_have", lambda mod: False)
    reg, skipped = BT.default_registry(["beta_binomial", "lightgbm", "kumo", "mystery"])
    assert reg == {} and set(skipped) == {"lightgbm", "kumo", "mystery"}
    rep = BT.run_backtest(synth_races(), reg, skipped)
    assert rep["models"] == [BT.BASELINE] and "lightgbm" in rep["skipped_models"]


def test_dependencies_present_register_models(monkeypatch):
    monkeypatch.setattr(BT, "_have", lambda mod: True)
    reg, skipped = BT.default_registry(["lightgbm", "kumo"])
    assert set(reg) == {"lightgbm", "kumo"} and skipped == {}


def test_lightgbm_adapter_when_installed():
    pytest.importorskip("lightgbm")
    X = np.random.RandomState(0).rand(200, 3)
    y = (X[:, 0] > 0.5).astype(int)
    m = BT.LightGBMAdapter()
    m.fit(X, y, 4)
    p = m.predict(X)
    assert p.shape == (200,) and Mx.roc_auc(p, y) > 0.9
    m.clear()


# ---- sanity check ------------------------------------------------------------------------------------------------------------------

def canada_races(n, sc):
    return [make_race(2010 + i, 7, "montreal", "hybrid",
                      [{"type": "sc", "driver": "", "lap": 10, "end_lap": 13}] if i < sc else []) for i in range(n)]


def test_canada_sanity_check_on_synthetic_data():
    rates = BT.sc_rates(canada_races(10, 6) + synth_races())
    assert rates["montreal"]["sc_rate"] == 0.6 and rates["montreal"]["n"] == 10
    ok = BT.canada_check(rates)
    assert ok["ok"] is True and "6/10 = 60%" in ok["line"]
    assert BT.canada_check(BT.sc_rates(canada_races(10, 1)))["ok"] is False
    assert BT.canada_check(BT.sc_rates(canada_races(3, 2)))["ok"] is None  # too few races to judge
    assert BT.canada_check({})["ok"] is None


def test_vsc_counts_toward_any_but_not_sc_rate():
    r = make_race(2020, 1, "x", "street", [{"type": "vsc", "driver": "", "lap": 5, "end_lap": 6}])
    s = BT.sc_rates([r])["x"]
    assert (s["sc"], s["any"]) == (0, 1)


# ---- command -----------------------------------------------------------------------------------------------------------------------

@pytest.mark.django_db
def test_command_end_to_end_baseline_only_and_skips(tmp_path, monkeypatch):
    monkeypatch.setenv("CHAOS_FEATURES_DIR", str(tmp_path))
    monkeypatch.setattr(BT, "_have", lambda mod: False)
    seed_db(synth_races())
    out = io.StringIO()
    call_command("chaos_backtest", "--seasons", "2020-2023", stdout=out)
    text = out.getvalue()
    assert "SKIPPED lightgbm" in text and "SKIPPED kumo" in text and "beta_binomial: mean Brier" in text and "Canada SC rate" in text
    files = sorted(p.name for p in (tmp_path / "backtest").iterdir())
    assert files == ["loso_2020-2023.csv", "loso_2020-2023.json"]
    assert ModelRun.objects.filter(model="backtest").exists()


@pytest.mark.django_db
def test_command_backfill_stores_raw_kumo_for_calibration(tmp_path, monkeypatch):
    monkeypatch.setenv("CHAOS_FEATURES_DIR", str(tmp_path))
    monkeypatch.setattr(BT, "_have", lambda mod: True)
    monkeypatch.setattr(M, "model_factory", lambda size, device: RateModel())
    monkeypatch.setattr(BT, "LightGBMAdapter", RateModel)
    races = synth_races()
    seed_db(races)
    build_features()
    out = io.StringIO()
    call_command("chaos_backtest", "--models", "beta_binomial,kumo", "--backfill-kumo", "--seasons", "2020-2023", stdout=out)
    assert "kumo: mean Brier" in out.getvalue()
    raw = ModelRun.objects.filter(model="kumo_tabular")
    assert raw.count() == len(races) - 1  # every race that has any history
    assert ChaosPrediction.objects.filter(model_run__model="kumo_tabular", scope="race").exists()
    # the stored raw predictions are exactly what calibrate_and_store consumes
    last = races[-1]
    assert M.calibrate_and_store(last["year"], last["round"])["status"] == "ok"
