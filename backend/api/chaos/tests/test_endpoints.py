"""Phase 2e: chaos endpoints on synthetic stored runs (no network, no torch)."""
from unittest.mock import patch

import numpy as np
import pytest
from django.conf import settings
from django.core.cache import caches
from rest_framework.test import APIClient

from api.chaos import ml_tasks as M
from api.chaos import service as S
from api.chaos.models import ChaosPrediction, ModelRun
from api.chaos.tasks import build_features, populate_chaos, run_baseline
from api.chaos.tests.test_features_baseline import seed_db, synth_races
from api.chaos.views import (
    ChaosCircuitHistoryAPIView, ChaosCircuitListAPIView, ChaosCircuitsSummaryAPIView, ChaosDriverProfileAPIView, ChaosDriversAPIView, ChaosLapsAPIView, ChaosModelAPIView, ChaosRaceAPIView,
)
from api.models import RaceResultData
from api.session.views import AnalysisTelemetryAPIView

Y, R = 2023, 4
BASE = f"/api/chaos/races/{Y}/{R}/"


class Rate(M.TabularModel):
    def fit(self, X, y, num_estimators):
        self.r = (y.sum() + 1) / (len(y) + 2)

    def predict(self, X):
        return np.full(len(X), self.r)

    def clear(self):
        pass


@pytest.fixture(autouse=True)
def _clear_cache():
    caches["default"].clear()
    yield
    caches["default"].clear()


@pytest.fixture
def client():
    c = APIClient()
    c.credentials(HTTP_X_API_KEY=str(settings.INTERNAL_API_KEY))
    return c


@pytest.fixture
def stored(db, tmp_path, monkeypatch):
    """Synthetic history with a baseline run for the last race (2023 R4)."""
    monkeypatch.setenv("CHAOS_FEATURES_DIR", str(tmp_path))
    monkeypatch.setattr(M, "model_factory", lambda size, device: Rate())
    monkeypatch.setenv("CHAOS_KUMO_BAGS", "2")
    seed_db(synth_races())
    build_features()
    run_baseline(Y, R)


@pytest.fixture
def with_kumo(stored):
    M.run_kumo(Y, R)
    M.calibrate_and_store(Y, R)


def ok(client, path):
    r = client.get(path)
    assert r.status_code == 200, r.content
    return r.json()


# ---- race ------------------------------------------------------------------------------------------------------------

def test_race_happy_path_baseline_is_flagged_as_fallback(client, stored):
    d = ok(client, BASE)
    assert d["meta"] == {"year": Y, "round": R, "circuit": "monza", "circuit_type": "permanent"}
    m = d["model"]
    assert m["model"] == "beta_binomial" and m["is_fallback"] is True and "no calibrated Kumo" in m["fallback_reason"]
    assert set(d["targets"]) == {"sc_vsc_red", "dnf_mechanical", "dnf_incident", "slow_stop", "unlucky_stop"}
    assert all(0 <= t["p10"] <= t["probability"] <= t["p90"] <= 1 for t in d["targets"].values())
    assert d["chaos_index"] > 0 and d["index_targets"] == ["sc_vsc_red", "dnf_mechanical", "dnf_incident"]
    assert 0 < len(d["factors"]) <= 5 and all("text" in f and "circuit_history" in f for f in d["factors"])
    assert d["chaos_index_band"]["p10"] <= d["chaos_index"] <= d["chaos_index_band"]["p90"]


def test_chaos_index_is_the_sum_of_the_calibrated_per_target_expectations(client, with_kumo):
    d = ok(client, BASE)
    run = ModelRun.objects.get(model="kumo_tabular_calibrated")
    P = ChaosPrediction.objects.filter(model_run=run)
    s = lambda scope, t: sum(p.probability for p in P.filter(scope=scope, target=t))  # noqa: E731
    expected = {"sc_vsc_red": s("lap_window", "sc_vsc_red"), "dnf_mechanical": s("driver", "dnf_mechanical"),
                "dnf_incident": s("driver", "dnf_incident")}
    for t, v in expected.items():
        assert d["expected_events"][t]["value"] == pytest.approx(v, abs=1e-3)
    assert d["chaos_index"] == pytest.approx(sum(expected.values()), abs=2e-3)
    assert d["chaos_index"] == pytest.approx(sum(d["expected_events"][t]["value"] for t in d["index_targets"]), abs=2e-3)


def test_chaos_index_falls_back_to_race_probability_and_says_so(client, stored):
    run = ModelRun.objects.get(model="beta_binomial")
    run.predictions.filter(scope__in=["driver", "lap_window"]).delete()
    d = ok(client, BASE)
    assert all(e["source"].startswith("race-level") for e in d["expected_events"].values())
    assert d["chaos_index"] == pytest.approx(sum(d["targets"][t]["probability"] for t in d["index_targets"]), abs=2e-3)


# ---- model preference ---------------------------------------------------------------------------------------------------

def test_prefers_calibrated_kumo_then_baseline_and_never_silently(client, with_kumo):
    d = ok(client, BASE)
    assert d["model"]["model"] == "kumo_tabular_calibrated" and d["model"]["is_fallback"] is False
    assert d["model"]["calibration"].startswith("identity")  # no backtest history in this fixture: flagged, not hidden
    assert d["model"]["calibrated"] is False
    # named models
    assert ok(client, BASE + "?model=baseline")["model"]["model"] == "beta_binomial"
    assert ok(client, BASE + "?model=baseline")["model"]["is_fallback"] is False  # asked for, not a fallback
    assert ok(client, BASE + "?model=kumo")["model"]["model"] == "kumo_tabular"
    # calibrated run gone: auto serves the baseline (not raw Kumo) and labels it a fallback
    ModelRun.objects.filter(model="kumo_tabular_calibrated").delete()
    caches["default"].clear()
    d = ok(client, BASE)
    assert d["model"]["model"] == "beta_binomial" and d["model"]["is_fallback"] is True
    # a named model with no run is a 404, never a substitute
    r = client.get(BASE + "?model=kumo_calibrated")
    assert r.status_code == 404 and "kumo_calibrated" in r.json()["error"]


def test_bad_model_param_is_400(client, stored):
    r = client.get(BASE + "?model=gpt")
    assert r.status_code == 400 and "model must be one of" in r.json()["error"]


# ---- drivers / laps ----------------------------------------------------------------------------------------------------------

def test_drivers_happy_path(client, stored):
    d = ok(client, BASE + "drivers/")
    assert [x["driver"] for x in d["drivers"]] and len(d["drivers"]) == 4 and d["model"]["model"] == "beta_binomial"
    row = d["drivers"][0]
    assert set(row["targets"]) == {"dnf_mechanical", "dnf_incident", "slow_stop", "unlucky_stop"} and row["team"] in ("T1", "T2")
    risk = [x["targets"]["dnf_mechanical"]["probability"] + x["targets"]["dnf_incident"]["probability"] for x in d["drivers"]]
    assert risk == sorted(risk, reverse=True) and "luck" in d["note"]


def test_laps_heat_strip(client, stored):
    d = ok(client, BASE + "laps/")
    assert d["target"] == "sc_vsc_red" and d["meta"]["window_size"] == 5 and d["meta"]["total_laps"] == 30
    assert len(d["windows"]) == len(d["strip"]) == 6
    assert d["windows"][0] == {**d["windows"][0], "window": 1, "lap_start": 1, "lap_end": 5}
    assert d["windows"][-1]["lap_end"] == 30
    assert d["strip"][2] == d["windows"][2]["targets"]["sc_vsc_red"]["probability"]
    d2 = ok(client, BASE + "laps/?target=slow_stop")
    assert d2["target"] == "slow_stop" and d2["strip"][0] == d2["windows"][0]["targets"]["slow_stop"]["probability"]
    assert client.get(BASE + "laps/?target=nope").status_code == 400


# ---- pending / 404 / bad params -------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("suffix", ["", "drivers/", "laps/"])
def test_pending_enqueues_pipeline_and_returns_202(client, db, suffix):
    seed_db(synth_races())  # history exists, no runs
    with patch("api.chaos.views.TaskManager.enqueue_if_needed") as enq:
        r = client.get(BASE + suffix)
    assert r.status_code == 202
    assert r.json() == {"status": "pending", "task_key": f"chaos:{Y}:{R}", "detail": "Chaos predictions are being built; retry shortly."}
    enq.assert_called_once()
    assert enq.call_args.args == (f"chaos:{Y}:{R}", populate_chaos, Y, R)


def test_no_history_is_404_not_pending(client, db):
    seed_db(synth_races())
    with patch("api.chaos.views.TaskManager.enqueue_if_needed") as enq:
        r = client.get("/api/chaos/races/2019/1/")
    assert r.status_code == 404 and "nothing to predict from" in r.json()["error"]
    enq.assert_not_called()


@pytest.mark.parametrize("path", ["/api/chaos/races/1800/4/", "/api/chaos/races/2023/0/", "/api/chaos/races/2023/99/drivers/"])
def test_bad_year_or_round_is_400(client, db, path):
    assert client.get(path).status_code == 400


def test_populate_chaos_wrapper_runs_chain_and_keeps_record_running(db):
    from api.models import TaskRecord

    TaskRecord.objects.create(task_key=f"chaos:{Y}:{R}", status="pending")
    with patch("celery.canvas._chain.apply_async") as ap:
        populate_chaos.run(f"chaos:{Y}:{R}", Y, R)
    ap.assert_called_once()
    assert TaskRecord.objects.get(task_key=f"chaos:{Y}:{R}").status == "running"


def test_run_baseline_closes_the_pending_task_record(stored):
    from api.models import TaskRecord

    TaskRecord.objects.create(task_key=f"chaos:{Y}:{R}", status="running")
    run_baseline(Y, R)
    assert TaskRecord.objects.get(task_key=f"chaos:{Y}:{R}").status == "complete"


# ---- circuit history / driver profile ----------------------------------------------------------------------------------------------

def test_circuit_history(client, stored):
    d = ok(client, "/api/chaos/circuits/monaco/history/")
    assert d["circuit"]["slug"] == "monaco" and d["circuit"]["type"] == "street" and d["circuit"]["wall_proximity"] is None
    assert d["summary"]["races"] == len(d["races"]) == 4 and [r["year"] for r in d["races"]] == [2020, 2021, 2022, 2023]
    n_sc = sum(r["safety_cars"] > 0 for r in d["races"])
    assert d["summary"]["safety_car_rate"] == pytest.approx(n_sc / 4)
    assert ok(client, "/api/chaos/circuits/MONACO/history/")["circuit"]["slug"] == "monaco"
    assert client.get("/api/chaos/circuits/atlantis/history/").status_code == 404


def test_driver_profile_is_a_tendency_with_a_wide_interval(client, stored):
    d = ok(client, "/api/chaos/drivers/aaa/profile/")
    assert d["driver"] == "AAA" and d["races"] == 16 and d["last_team"] == "T1" and "not skill" in d["label"]
    assert set(d["tendencies"]) == {"dnf_mechanical", "dnf_incident", "slow_stop", "unlucky_stop"}
    for t in d["tendencies"].values():
        assert 0 <= t["p10"] <= t["tendency"] <= t["p90"] <= 1 and t["races"] == 16
    assert d["tendencies"]["slow_stop"]["p90"] - d["tendencies"]["slow_stop"]["p10"] > 0.05  # 16 races: still wide
    assert client.get("/api/chaos/drivers/ZZZ/profile/").status_code == 404
    assert client.get("/api/chaos/drivers/AB/profile/").status_code == 400


# ---- model page ----------------------------------------------------------------------------------------------------------------------------

def test_model_page_empty_then_populated(client, db):
    assert ok(client, "/api/chaos/model/") == {"current_runs": [], "backtest": None}


def test_model_page_lists_runs_backtest_and_calibration(client, with_kumo):
    from api.chaos import backtest as BT
    from api.chaos import history as H

    BT.save_run(BT.run_backtest(H.load_races(), {}))
    caches["default"].clear()
    d = ok(client, "/api/chaos/model/")
    assert [r["model"] for r in d["current_runs"]] == ["kumo_tabular_calibrated", "kumo_tabular", "beta_binomial"]
    assert d["current_runs"][0]["calibration"] and d["current_runs"][0]["calibrated"] is False
    bt = d["backtest"]
    assert bt["seasons"] == [2020, 2021, 2022, 2023] and bt["canada_check"]["ok"] is None
    cell = bt["results"]["beta_binomial"]["race|sc_vsc_red"]
    assert {"brier", "log_loss", "auc", "ece", "bins"} <= set(cell)


# ---- cache ----------------------------------------------------------------------------------------------------------------------------------------

def test_responses_are_cached_and_invalidated_by_a_new_model_run(client, stored, django_capture_on_commit_callbacks):
    calls = []
    real = S.race_payload
    with patch("api.chaos.service.race_payload", side_effect=lambda *a, **k: calls.append(1) or real(*a, **k)):
        ok(client, BASE)
        ok(client, BASE)
        assert len(calls) == 1  # second request served from cache
        with django_capture_on_commit_callbacks(execute=True):
            run_baseline(Y, R)  # a ModelRun lands -> version bump
        ok(client, BASE)
        assert len(calls) == 2


def test_cache_outage_never_breaks_the_endpoint(client, stored):
    with patch("api.chaos.cache._cache", side_effect=RuntimeError("redis down")):
        assert client.get(BASE).status_code == 200


# ---- auth / throttle parity ------------------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("view", [ChaosRaceAPIView, ChaosDriversAPIView, ChaosLapsAPIView, ChaosCircuitHistoryAPIView, ChaosCircuitListAPIView, ChaosCircuitsSummaryAPIView,
                                  ChaosDriverProfileAPIView, ChaosModelAPIView])
def test_view_classes_match_existing_analysis_view(view):
    ref = AnalysisTelemetryAPIView
    assert view.authentication_classes == ref.authentication_classes
    assert view.permission_classes == ref.permission_classes
    assert view.throttle_classes == ref.throttle_classes
    assert [c.__name__ for c in view.throttle_classes] == ["APIKeyThrottle"]


@pytest.mark.parametrize("path", ["races/2023/4/", "races/2023/4/drivers/", "races/2023/4/laps/", "circuits/monaco/history/",
                                  "drivers/AAA/profile/", "model/", "circuits/summary/"])
def test_requests_without_api_key_are_rejected_like_existing_views(db, path):
    r = APIClient().get("/api/chaos/" + path)
    assert r.status_code in (401, 403)
    assert r.status_code == APIClient().get("/api/analysis/races/2025/5/laps/").status_code


def test_schema_generation_has_no_chaos_warnings():
    from drf_spectacular.generators import SchemaGenerator

    gen = SchemaGenerator()
    schema = gen.get_schema(request=None, public=True)
    paths = [p for p in schema["paths"] if p.startswith("/api/chaos/")]
    assert len(paths) == 8
    ids = {schema["paths"][p]["get"]["operationId"] for p in paths}
    assert len(ids) == 8


# ---- Phase 2g: per_season on model/, circuits/summary/ -------------------------------------------------------------------------------------

def test_model_page_serves_per_season_metrics_and_stays_backward_compatible(client, stored):
    from api.chaos import backtest as BT
    from api.chaos import history as H

    rep = BT.run_backtest(H.load_races(), {})
    BT.save_run(rep)
    caches["default"].clear()
    bt = ok(client, "/api/chaos/model/")["backtest"]
    # old fields untouched
    assert {"run_id", "seasons", "models", "skipped_models", "prior_strength", "canada_check", "races", "results", "note"} <= set(bt)
    assert {"brier", "log_loss", "auc", "ece", "bins", "n", "base_rate"} <= set(bt["results"]["beta_binomial"]["race|sc_vsc_red"])
    # new: model -> scope|target -> season -> same metric names as overall (minus the pooled reliability bins)
    ps = bt["per_season"]
    assert set(ps) == set(bt["results"]) == {"beta_binomial"}
    cell = ps["beta_binomial"]["race|sc_vsc_red"]
    assert set(cell) == {"2020", "2021", "2022", "2023"}
    assert {"n", "base_rate", "brier", "log_loss", "auc"} <= set(cell["2021"])
    assert cell["2021"] == rep["results"]["beta_binomial"]["race|sc_vsc_red"]["per_season"]["2021"]
    assert set(ps["beta_binomial"]) == set(bt["results"]["beta_binomial"])  # same cells as `results`


def test_model_page_without_backtest_has_no_per_season(client, stored):
    assert ok(client, "/api/chaos/model/")["backtest"] is None


def test_circuits_summary_matches_per_circuit_history(client, stored):
    d = ok(client, "/api/chaos/circuits/summary/")
    by = {c["slug"]: c for c in d["circuits"]}
    assert d["count"] == len(d["circuits"]) >= 32 and d["unmatched_circuits"] == []
    assert [c["slug"] for c in d["circuits"]] == sorted(by)
    for slug in ("monaco", "baku", "spa", "monza"):  # the four circuits of the synthetic seasons
        hist = ok(client, f"/api/chaos/circuits/{slug}/history/")
        assert by[slug]["summary"] == hist["summary"] and by[slug]["summary"]["races"] == 4
        assert {"name", "type"} <= set(by[slug])
    empty = by["montreal"]["summary"]  # known circuit, no races stored: present, zero races, null rates
    assert empty["races"] == 0 and empty["safety_car_rate"] is None and empty["mean_mechanical_dnfs"] is None
    assert set(by["monaco"]["summary"]) == {"races", "safety_car_rate", "vsc_rate", "red_flag_rate", "any_neutralisation_rate",
                                            "mean_mechanical_dnfs", "mean_incident_dnfs"}


def test_circuits_summary_lists_unmatched_circuit_texts(client, stored):
    from api.models import SeasonSchedule

    SeasonSchedule.objects.filter(year=2023).update(payload={"races": [{"round": r, "location": "Mystery Park"} for r in range(1, 5)]})
    caches["default"].clear()
    assert ok(client, "/api/chaos/circuits/summary/")["unmatched_circuits"] == ["Mystery Park"]


def test_circuits_summary_is_cached_and_invalidated_by_a_label_build(client, stored, django_capture_on_commit_callbacks):
    from api.chaos.tasks import build_labels

    calls = []
    real = S.circuits_summary
    with patch("api.chaos.service.circuits_summary", side_effect=lambda: calls.append(1) or real()):
        ok(client, "/api/chaos/circuits/summary/")
        ok(client, "/api/chaos/circuits/summary/")
        assert len(calls) == 1
        with django_capture_on_commit_callbacks(execute=True):
            build_labels(Y, R)
        ok(client, "/api/chaos/circuits/summary/")
        assert len(calls) == 2


def test_circuits_summary_does_not_shadow_a_circuit_slug_route(client, stored):
    assert client.get("/api/chaos/circuits/summary/history/").status_code == 404  # "summary" is not a circuit
    assert ok(client, "/api/chaos/circuits/monaco/history/")["circuit"]["slug"] == "monaco"
