"""Phase 2c: Kumo path with a fake model (no torch, no weights), calibration, chain wiring, import isolation."""
import os
import subprocess
import sys

import numpy as np
import pytest

from api.chaos import ml_tasks as M
from api.chaos.models import ChaosPrediction, FeatureSet, ModelRun, RaceEventLabel
from api.chaos.tasks import build_features, build_pipeline, pipeline_targets, refresh_chaos
from api.chaos.tests.test_features_baseline import seed_db, synth_races
from api.models import RaceResultData, SeasonSchedule


class FakeModel(M.TabularModel):
    """Smoothed positive rate of the context, nudged by the first feature so rows differ. Records what it saw."""

    calls = []

    def fit(self, X, y, num_estimators):
        self.rate = (y.sum() + 1) / (len(y) + 2)
        FakeModel.calls.append({"n": len(X), "d": X.shape[1], "est": num_estimators})

    def predict(self, X):
        return np.clip(self.rate + (0.01 * np.nan_to_num(X[:, 0])) % 0.05, 0, 1)

    def clear(self):
        pass


@pytest.fixture
def fake(monkeypatch, tmp_path):
    FakeModel.calls = []
    monkeypatch.setattr(M, "model_factory", lambda size, device: FakeModel())
    monkeypatch.setenv("CHAOS_FEATURES_DIR", str(tmp_path))
    monkeypatch.setenv("CHAOS_KUMO_BAGS", "3")


def seeded():
    races = synth_races()
    seed_db(races)
    build_features()
    return races


# ---- isolation -------------------------------------------------------------------------------------------------

def test_importing_chaos_task_modules_does_not_load_torch_or_sdm():
    from django.conf import settings

    code = ("import os,sys;os.environ['DJANGO_SETTINGS_MODULE']='f1_project.settings_test';import django;django.setup();"
            "import api.chaos.tasks, api.chaos.ml_tasks;"
            "bad=[m for m in ('torch','sdm') if m in sys.modules];print('LOADED',bad);sys.exit(1 if bad else 0)")
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=180, cwd=str(settings.BASE_DIR),
                       env={k: v for k, v in os.environ.items() if k != "PYTHONPATH"})
    assert r.returncode == 0, r.stdout[-500:] + r.stderr[-1500:]


def test_kumo_adapter_class1_layouts():
    f = M.KumoAdapter._class1
    assert f(np.array([[0.2, 0.8], [0.6, 0.4]])).tolist() == [0.8, 0.4]
    assert f(np.array([[0.3], [0.9]])).tolist() == [0.3, 0.9]
    assert f(np.array([0.1, 0.2])).tolist() == [0.1, 0.2]


def test_kumo_adapter_class1_reads_tabletensor_via_to_pandas():
    """sdm's TableTensor raises on detach()/numpy(); the adapter must read it through to_pandas() (columns '0' and '1')."""
    import pandas as pd

    class FakeTableTensor:
        def to_pandas(self):
            return pd.DataFrame({"0": [0.9, 0.7], "1": [0.1, 0.3]})

        def detach(self):  # what the real object does to a caller that treats it like a tensor
            raise NotImplementedError("'aten.detach.default' is not supported for 'TableTensor'")

    assert M.KumoAdapter._class1(FakeTableTensor()).tolist() == [0.1, 0.3]


# ---- run_kumo ----------------------------------------------------------------------------------------------------

@pytest.mark.django_db
def test_run_kumo_end_to_end_with_fake_model(fake):
    races = seeded()
    last = races[-1]
    r = M.run_kumo(last["year"], last["round"])
    assert r["status"] == "ok", r
    run = ModelRun.objects.get(model="kumo_tabular")
    assert run.size == "small" and run.race_key == f"{last['year']}-{last['round']:02d}" and run.metrics["bags"] == 3
    assert run.metrics["live_only_dropped"] and run.context_rows > 0 and run.git_sha is not None
    preds = ChaosPrediction.objects.filter(model_run=run)
    assert {p.scope for p in preds} == {"race", "driver", "lap_window"}
    n_ok = lambda scope, targets: sum(f"{scope}|{t}" not in r["skipped"] for t in targets)  # noqa: E731
    assert preds.filter(scope="race").count() == n_ok("race", M.H.RACE_TARGETS) >= 4
    assert preds.filter(scope="driver").count() == n_ok("driver", M.H.DRIVER_TARGETS) * 4 >= 12
    assert preds.filter(scope="lap_window").count() == n_ok("lap_window", M.H.RACE_TARGETS) * 6
    assert all(0 <= p.p10 <= p.probability <= p.p90 <= 1 for p in preds)
    assert FakeModel.calls and all(c["est"] == 4 for c in FakeModel.calls)
    # the live-only column never reaches the model
    feats = FeatureSet.objects.get(scope="lap_window").meta["feature"]
    assert run.metrics["feature_columns"]["lap_window"] == len([c for c in feats if c != "live_restart_flag"])


@pytest.mark.django_db
def test_run_kumo_context_is_earlier_races_only(fake):
    seeded()
    M.run_kumo(2021, 3)
    sizes = {c["n"] for c in FakeModel.calls}
    # 2020 R1-4 + 2021 R1-2 = 6 earlier races. Race scope: 6 rows, bags use 80 % -> 4. Driver scope: 24 rows.
    # Window scope: 6 races x 6 windows = 36 rows. Nothing may exceed the largest earlier-only scope.
    assert 4 in sizes and max(sizes) <= 36
    assert M.run_kumo(2020, 1)["status"] == "no_history"


@pytest.mark.django_db
def test_run_kumo_rerun_replaces_and_upcoming_race_works(fake):
    seeded()
    M.run_kumo(2022, 2)
    n = ChaosPrediction.objects.count()
    M.run_kumo(2022, 2)
    assert ChaosPrediction.objects.count() == n and ModelRun.objects.count() == 1
    SeasonSchedule.objects.create(year=2024, payload={"races": [{"round": 1, "location": "monaco"}]})
    assert M.run_kumo(2024, 1)["status"] == "ok"  # no result row yet: stub race, features from history only


@pytest.mark.django_db
def test_single_class_context_is_skipped_not_crashed(fake):
    seeded()
    RaceEventLabel.objects.filter(type="sc").delete()
    build_features()
    r = M.run_kumo(2023, 4)
    assert "race|sc_vsc_red" in r["skipped"]
    assert not ChaosPrediction.objects.filter(scope="race", target="sc_vsc_red").exists()


# ---- calibration --------------------------------------------------------------------------------------------------

@pytest.mark.django_db
def test_calibration_is_identity_without_backtest_history(fake):
    seeded()
    M.run_kumo(2021, 2)
    r = M.calibrate_and_store(2021, 2)
    assert r["status"] == "ok" and r["fitted"] == 0
    cal = ModelRun.objects.get(model="kumo_tabular_calibrated")
    assert cal.metrics["calibrated"] is False and all(v["method"] == "identity" for v in cal.calibration.values())
    raw = {(p.scope, p.entity, p.target): p.probability for p in ChaosPrediction.objects.filter(model_run__model="kumo_tabular")}
    out = {(p.scope, p.entity, p.target): p.probability for p in ChaosPrediction.objects.filter(model_run=cal)}
    assert out == raw
    assert M.calibrate_and_store(2030, 1)["status"] == "no_raw_predictions"


@pytest.mark.django_db
def test_calibration_fits_isotonic_when_backtest_exists(fake, monkeypatch):
    monkeypatch.setattr(M, "CAL_MIN_POINTS", 20)
    races = seeded()
    for r in races[2:]:  # backtest raw predictions for earlier races, then the target (last)
        M.run_kumo(r["year"], r["round"])
    last = races[-1]
    res = M.calibrate_and_store(last["year"], last["round"])
    assert res["fitted"] > 0
    cal = ModelRun.objects.get(model="kumo_tabular_calibrated")
    assert cal.metrics["calibrated"] is True
    fitted = [v for v in cal.calibration.values() if v["method"] == "isotonic"]
    assert fitted and all("ece" in v and v["bins"] for v in fitted)
    preds = ChaosPrediction.objects.filter(model_run=cal)
    assert all(0 <= p.p10 <= p.probability <= p.p90 <= 1 for p in preds)  # monotone map keeps the band ordered
    assert ModelRun.objects.filter(model="kumo_tabular").count() == len(races) - 2  # raw runs untouched
    n = ChaosPrediction.objects.count()
    M.calibrate_and_store(last["year"], last["round"])
    assert ChaosPrediction.objects.count() == n  # idempotent


def test_reliability_bins_and_ece():
    r = M.reliability([0.1, 0.1, 0.9, 0.9], [0, 0, 1, 1])
    assert r["ece"] == pytest.approx(0.1) and sum(b["n"] for b in r["bins"]) == 4


# ---- pipeline wiring -------------------------------------------------------------------------------------------

def names(ch):
    return [t.task for t in ch.tasks]


def test_chain_without_kumo(monkeypatch):
    monkeypatch.delenv("CHAOS_ENABLE_KUMO", raising=False)
    assert names(build_pipeline(2024, 5)) == ["api.chaos.tasks.build_labels", "api.chaos.tasks.build_features", "api.chaos.tasks.run_baseline"]


@pytest.mark.parametrize("val", ["1", "true", "True", "yes"])
def test_chain_with_kumo_is_immutable_and_ml_steps_by_name(monkeypatch, val):
    monkeypatch.setenv("CHAOS_ENABLE_KUMO", val)
    ch = build_pipeline(2024, 5)
    assert names(ch)[-2:] == ["api.chaos.ml_tasks.run_kumo", "api.chaos.ml_tasks.calibrate_and_store"] and len(ch.tasks) == 5
    assert all(t.immutable for t in ch.tasks) and ch.tasks[-1].args == (2024, 5)


def test_task_routes_put_ml_steps_on_ml_queue():
    from django.conf import settings

    routes = settings.CELERY_TASK_ROUTES
    assert routes["api.chaos.ml_tasks.*"]["queue"] == "ml" and routes["api.chaos.tasks.*"]["queue"] == "tier3_medium"


@pytest.mark.django_db
def test_pipeline_targets_latest_and_next():
    assert pipeline_targets() == []
    RaceResultData.objects.create(year=2025, round_number=23, session="R", payload={"results": [{"x": 1}]})
    SeasonSchedule.objects.create(year=2025, payload={"races": [{"round": 23}, {"round": 24}]})
    assert pipeline_targets() == [(2025, 23), (2025, 24)]
    RaceResultData.objects.create(year=2025, round_number=24, session="R", payload={"results": [{"x": 1}]})
    SeasonSchedule.objects.create(year=2026, payload={"races": [{"round": 1}]})
    assert pipeline_targets() == [(2025, 24), (2026, 1)]
    SeasonSchedule.objects.filter(year=2026).delete()
    assert pipeline_targets() == [(2025, 24)]


@pytest.mark.django_db
def test_refresh_chaos_queues_one_chain_per_target(monkeypatch):
    RaceResultData.objects.create(year=2025, round_number=3, session="R", payload={"results": [{"x": 1}]})
    SeasonSchedule.objects.create(year=2025, payload={"races": [{"round": 3}, {"round": 4}]})
    sent = []

    class Res:
        id = "abc"

    from celery import canvas

    monkeypatch.setattr(canvas._chain, "apply_async", lambda self, *a, **k: sent.append(names(self)) or Res())
    r = refresh_chaos()
    assert [x["round"] for x in r["runs"]] == [3, 4] and len(sent) == 2
    assert sent[0][0] == "api.chaos.tasks.build_labels"
