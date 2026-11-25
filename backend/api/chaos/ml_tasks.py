"""Chaos ML tasks (queue `ml`, routed by module). torch / sdm are imported ONLY inside `make_model`, which runs in the
ml worker; importing this module (or api.chaos.tasks) never loads them (tested).

run_kumo            : in-context Kumo Tabular per (scope, target); context = earlier races, query = the target race.
calibrate_and_store : isotonic calibration fitted on stored backtest predictions, written as its own ModelRun.

Raw and calibrated predictions live in separate ModelRuns (`kumo_tabular`, `kumo_tabular_calibrated`) so later
backtests always fit calibration on RAW outputs (no feedback loop).
"""
import logging
import os

import numpy as np
from celery import shared_task
from django.db import transaction

from . import features as F
from . import history as H
from .metrics import reliability
from .models import ChaosPrediction, FeatureSet, ModelRun

logger = logging.getLogger(__name__)

RAW_MODEL, CAL_MODEL = "kumo_tabular", "kumo_tabular_calibrated"
MAX_CONTEXT = 50_000          # under Kumo's 60,000-row pretraining scope; sampled above this
CAL_MIN_POINTS = 200          # isotonic needs enough backtest points, else identity
SCOPE_TARGETS = {"race": H.RACE_TARGETS, "driver": H.DRIVER_TARGETS, "lap_window": H.RACE_TARGETS}


def _env_int(name, default):
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


# ---- model interface ------------------------------------------------------------------------------------------

class TabularModel:
    """What run_kumo needs from a model. Tests use a fake with these three methods.
    fit(X, y, num_estimators): X float array (n, d) with NaN allowed, y int array (n,) in {0, 1}.
    predict(X) -> float array (n,) = P(y == 1). clear() releases cached context."""

    def fit(self, X, y, num_estimators): raise NotImplementedError
    def predict(self, X): raise NotImplementedError
    def clear(self): raise NotImplementedError


class KumoAdapter(TabularModel):
    """sdm.models.KumoTabular behind the interface. DEFERRED-VM: not exercised here (no torch in this environment).
    Written to KUMO_SETUP.md: KumoTabular(task, size, device).eval(); fit(X, y[R,1], num_estimators); predict(X);
    clear(). The layout of predict's return (class probabilities) is the unverified part: see `_class1`."""

    def __init__(self, size="small", device="cpu"):
        os.environ.setdefault("HF_HUB_OFFLINE", "1")  # weights are pre-downloaded; never reach the Hub from a task
        import torch  # noqa: PLC0415
        from sdm.models import KumoTabular  # noqa: PLC0415

        self._torch = torch
        self._m = KumoTabular(task="classification", size=size, device=device).eval()

    def fit(self, X, y, num_estimators):
        t = self._torch
        self._m.fit(t.tensor(X, dtype=t.float32), t.tensor(y, dtype=t.long).unsqueeze(-1), num_estimators=num_estimators)

    def predict(self, X):
        t = self._torch
        return self._class1(self._m.predict(t.tensor(X, dtype=t.float32)))

    @staticmethod
    def _class1(out):
        """Class-1 probability per row from whatever predict returns (tensor or TableTensor-like).
        Tolerates (n,), (n,1) and (n,2) layouts.
        sdm's TableTensor blocks torch ops such as detach() and numpy(); its own to_pandas() returns a frame whose columns '0' and '1'
        are the class probabilities (verified on the VM 2026-11-25: rows sum to 1)."""
        if hasattr(type(out), "to_pandas"):
            df = out.to_pandas()
            return np.asarray(df["1"] if "1" in df.columns else df.iloc[:, -1], dtype=float)
        data = getattr(out, "data", out)
        arr = data.detach().cpu().numpy() if hasattr(data, "detach") else np.asarray(data)
        arr = np.asarray(arr, dtype=float).reshape(len(arr), -1)
        return arr[:, 1] if arr.shape[1] >= 2 else arr[:, 0]

    def clear(self):
        self._m.clear()


def model_factory(size="small", device="cpu") -> TabularModel:
    """Patched in tests. Real path imports torch/sdm here, inside the worker."""
    return KumoAdapter(size, device)


# ---- run_kumo ---------------------------------------------------------------------------------------------------

def _context_frame(scope, key, hist):
    """Earlier-race rows of this scope: from the newest FeatureSet Parquet, else recomputed from history."""
    import pandas as pd

    fs = FeatureSet.objects.filter(scope=scope).order_by("-created_at").first()
    if fs and os.path.exists(fs.path):
        df = pd.read_parquet(fs.path)
    else:
        logger.warning("[chaos] no FeatureSet parquet for %s; recomputing context from history", scope)
        df = F.build_tables(hist)[scope]
    return df[(df["id_year"] * 100 + df["id_round"]) < key[0] * 100 + key[1]]


def _bagged(factory, size, device, Xc, yc, Xq, bags, estimators, rng):
    """K fits on random 80% context subsamples; returns (mean, p10, p90) over the K predictions per query row.
    ponytail: the band is sensitivity to the context sample (a proxy for model uncertainty), not a proper
    predictive interval. Replace with Kumo regression quantiles / conformal bands once validated on the VM."""
    preds = []
    for i in range(bags):
        idx = np.arange(len(Xc)) if bags == 1 else rng.choice(len(Xc), size=max(2, int(0.8 * len(Xc))), replace=False)
        if len(set(yc[idx])) < 2:
            idx = np.arange(len(Xc))
        m = factory(size, device)
        try:
            m.fit(Xc[idx], yc[idx], estimators)
            preds.append(np.clip(np.asarray(m.predict(Xq), dtype=float), 0.0, 1.0))
        finally:
            m.clear()
    P = np.vstack(preds)
    return P.mean(0), np.percentile(P, 10, axis=0), np.percentile(P, 90, axis=0)


@shared_task(name="api.chaos.ml_tasks.run_kumo", max_retries=0)
def run_kumo(year: int, round_number: int) -> dict:
    """Raw Kumo predictions for one race. Leakage rule as the baseline: context = races strictly before, query = the
    target race's rows built from that same history. `live_only` columns are dropped (pre-race prediction)."""
    from .tasks import _git_sha

    key = (year, round_number)
    hist, target = H.target_race(year, round_number)
    if not hist:
        return {"status": "no_history", "year": year, "round": round_number}
    size, device = os.environ.get("CHAOS_KUMO_SIZE", "small"), os.environ.get("CHAOS_KUMO_DEVICE", "cpu")
    bags, estimators = max(1, _env_int("CHAOS_KUMO_BAGS", 5)), _env_int("CHAOS_KUMO_ESTIMATORS", 4)
    rng = np.random.RandomState(1234)
    query_tables = F.build_tables(hist + [target])
    rows, skipped, ctx_total, used_cols = [], [], 0, {}
    for scope, targets in SCOPE_TARGETS.items():
        ctx = _context_frame(scope, key, hist)
        q = query_tables[scope]
        q = q[(q["id_year"] == year) & (q["id_round"] == round_number)]
        if ctx.empty or q.empty:
            continue
        groups = F.column_groups(q)
        cols = [c for c in groups["feature"] if c not in groups["live_only"] and c in ctx.columns]
        used_cols[scope] = len(cols)
        if len(ctx) > MAX_CONTEXT:
            ctx = ctx.sample(MAX_CONTEXT, random_state=1234)
        Xc, Xq = ctx[cols].to_numpy(dtype=float), q[cols].to_numpy(dtype=float)
        ctx_total += len(ctx)
        ent = (lambda r: "") if scope == "race" else ((lambda r: r["id_driver"]) if scope == "driver" else (lambda r: f"w{int(r['id_window'])}"))
        entities = [ent(r) for _, r in q.iterrows()]
        for t in targets:
            yc = ctx[f"y_{t}"].to_numpy(dtype=int)
            if len(set(yc)) < 2:
                skipped.append(f"{scope}|{t}")  # one class in context: nothing for the model to learn
                continue
            p, lo, hi = _bagged(model_factory, size, device, Xc, yc, Xq, bags, estimators, rng)
            rows += [dict(scope=scope, entity=e, target=t, probability=float(a), p10=float(min(a, b)), p90=float(max(a, c)))
                     for e, a, b, c in zip(entities, p, lo, hi)]
    with transaction.atomic():
        run, _ = ModelRun.objects.update_or_create(
            model=RAW_MODEL, size=size, race_key=f"{year}-{round_number:02d}",
            defaults={"context_rows": ctx_total, "git_sha": _git_sha(), "calibration": {},
                      "metrics": {"bags": bags, "num_estimators": estimators, "device": device, "history_races": len(hist),
                                  "interval": "context_bagging_p10_p90", "skipped": skipped, "feature_columns": used_cols,
                                  "live_only_dropped": True, "n_predictions": len(rows)}})
        run.predictions.all().delete()
        ChaosPrediction.objects.bulk_create([ChaosPrediction(year=year, round_number=round_number, model_run=run, **r) for r in rows])
    return {"status": "ok", "model_run": run.id, "predictions": len(rows), "context_rows": ctx_total, "skipped": skipped}


# ---- calibrate_and_store ---------------------------------------------------------------------------------------

def _backtest_points(scope, target, key, races_by_key):
    """(raw probability, outcome) over stored RAW kumo predictions for races before `key` that have finished."""
    ps, ys = [], []
    qs = ChaosPrediction.objects.filter(model_run__model=RAW_MODEL, scope=scope, target=target).exclude(
        year=key[0], round_number=key[1]).values_list("year", "round_number", "entity", "probability")
    for y, r, ent, p in qs:
        race = races_by_key.get((y, r))
        if (y, r) < key and race is not None:
            ps.append(p)
            ys.append(H.outcome(race, scope, ent, target))
    return np.array(ps), np.array(ys)


@shared_task(name="api.chaos.ml_tasks.calibrate_and_store", max_retries=0)
def calibrate_and_store(year: int, round_number: int) -> dict:
    """Calibrated copy of the race's raw Kumo predictions. Isotonic regression per (scope, target), fitted on raw
    predictions of EARLIER races whose outcomes are known; identity (flagged in ModelRun.calibration) when there
    are fewer than CAL_MIN_POINTS points or only one outcome class."""
    from sklearn.isotonic import IsotonicRegression  # noqa: PLC0415

    from .tasks import _git_sha

    key = (year, round_number)
    raw = ModelRun.objects.filter(model=RAW_MODEL, race_key=f"{year}-{round_number:02d}").first()
    if raw is None:
        return {"status": "no_raw_predictions", "year": year, "round": round_number}
    races_by_key = {H.race_key(r): r for r in H.load_races(up_to=key)}
    cal, rows, fitted = {}, [], 0
    for scope, targets in SCOPE_TARGETS.items():
        for t in targets:
            cur = list(raw.predictions.filter(scope=scope, target=t))
            if not cur:
                continue
            ps, ys = _backtest_points(scope, t, key, races_by_key)
            if len(ps) >= CAL_MIN_POINTS and len(set(ys)) == 2:
                iso = IsotonicRegression(y_min=0.0, y_max=1.0, out_of_bounds="clip").fit(ps, ys)
                f = lambda v: iso.predict(np.asarray(v, float))  # noqa: E731
                cal[f"{scope}|{t}"] = {"method": "isotonic", "n": int(len(ps)), **reliability(f(ps), ys),
                                       "raw_ece": reliability(ps, ys)["ece"]}
                fitted += 1
            else:
                f = lambda v: np.asarray(v, float)  # noqa: E731
                cal[f"{scope}|{t}"] = {"method": "identity", "n": int(len(ps)),
                                       "reason": f"needs >= {CAL_MIN_POINTS} backtest points with both outcomes"}
            p, lo, hi = f([c.probability for c in cur]), f([c.p10 for c in cur]), f([c.p90 for c in cur])  # monotone: band order kept
            rows += [dict(scope=scope, entity=c.entity, target=t, probability=float(a), p10=float(b), p90=float(d))
                     for c, a, b, d in zip(cur, p, lo, hi)]
    with transaction.atomic():
        run, _ = ModelRun.objects.update_or_create(
            model=CAL_MODEL, size=raw.size, race_key=raw.race_key,
            defaults={"context_rows": raw.context_rows, "git_sha": _git_sha(), "calibration": cal,
                      "metrics": {**raw.metrics, "raw_model_run": raw.id, "calibrated_keys": fitted,
                                  "identity_keys": len(cal) - fitted, "calibrated": fitted > 0}})
        run.predictions.all().delete()
        ChaosPrediction.objects.bulk_create([ChaosPrediction(year=year, round_number=round_number, model_run=run, **r) for r in rows])
    return {"status": "ok", "model_run": run.id, "predictions": len(rows), "fitted": fitted, "identity": len(cal) - fitted}
