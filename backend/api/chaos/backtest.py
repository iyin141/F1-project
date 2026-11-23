"""Leave-one-season-out backtest for Chaos Point (plan 01 Phase 2 Evaluation).

For each held-out season S:
  * ONE feature pass over all races in time order in which races of S are built from history but never ADDED to it
    (`features.build_tables(no_update=...)`). So training rows never carry S in their history features and the
    held-out rows only know earlier training races. Every model sees exactly these rows (identical splits).
  * Prior strength m is chosen from a small grid on the TRAINING seasons only (sequential baseline Brier over rows
    of seasons != S), never looking at S.
  * Models: `beta_binomial` (the hierarchical posterior columns of the feature table, i.e. the baseline), `lightgbm`
    (CPU reference), `kumo` (through the TabularModel interface). A model whose dependency is missing is skipped
    and named in the report.
Held-out predictions are scored per (scope, target) and per season, and pooled.
"""
import csv
import importlib.util
import json
from pathlib import Path

import numpy as np

from . import features as F
from . import history as H
from . import metrics as Mx
from .ml_tasks import SCOPE_TARGETS, TabularModel

GRID = (2.0, 4.0, 8.0, 16.0, 32.0)
BASELINE = "beta_binomial"
ESTIMATORS = 4
DROP_FEATURES = ("year",)  # a raw calendar year can not transfer to a held-out season; era_2022 carries the regulation change


# ---- optional models --------------------------------------------------------------------------------------------

class LightGBMAdapter(TabularModel):
    """CPU LightGBM classifier; NaN handled natively. Small trees: the tables are a few thousand rows."""

    def __init__(self):
        import lightgbm as lgb  # noqa: PLC0415

        self._lgb = lgb

    def fit(self, X, y, num_estimators):
        self.m = self._lgb.LGBMClassifier(n_estimators=150, learning_rate=0.05, num_leaves=8, min_child_samples=20,
                                          subsample=0.8, subsample_freq=1, colsample_bytree=0.8, n_jobs=1, verbose=-1,
                                          random_state=0).fit(X, y)

    def predict(self, X):
        return self.m.predict_proba(X)[:, 1]

    def clear(self):
        self.m = None


def _have(module: str) -> bool:
    return importlib.util.find_spec(module) is not None


def default_registry(names) -> tuple[dict, dict]:
    """({model: zero-arg factory}, {model: skip reason}). beta_binomial needs nothing and is not in the registry."""
    from . import ml_tasks

    reg, skipped = {}, {}
    for n in names:
        if n == BASELINE:
            continue
        if n == "lightgbm":
            if _have("lightgbm"):
                reg[n] = LightGBMAdapter
            else:
                skipped[n] = "lightgbm not installed"
        elif n == "kumo":
            if _have("sdm") and _have("torch"):
                reg[n] = lambda: ml_tasks.model_factory("small", "cpu")  # looked up at call time (tests patch it)
            else:
                skipped[n] = "sdm/torch not installed"
        else:
            skipped[n] = "unknown model"
    return reg, skipped


# ---- folds ----------------------------------------------------------------------------------------------------------

def baseline_col(scope, target) -> str:
    return f"drv_{target}" if scope == "driver" else f"circ_{target}"


def _train_brier(tables, held) -> float:
    """Mean over (scope, target) of the sequential baseline Brier on rows of seasons != held."""
    vals = []
    for scope, targets in SCOPE_TARGETS.items():
        t = tables[scope]
        t = t[t["id_year"] != held]
        for tg in targets:
            vals.append(Mx.brier(t[baseline_col(scope, tg)], t[f"y_{tg}"]))
    return float(np.mean(vals))


def tune_prior(races, held, grid=GRID):
    """Pick m on training seasons only. Returns (m, tables built with that m, {m: loss})."""
    best, losses = None, {}
    for m in grid:
        tabs = F.build_tables(races, no_update=lambda r: r["year"] == held, m=m)
        losses[m] = _train_brier(tabs, held)
        if best is None or losses[m] < losses[best[0]]:
            best = (m, tabs)
    return best[0], best[1], losses


def _xy(df, cols, target):
    return df[cols].to_numpy(dtype=float), df[f"y_{target}"].to_numpy(dtype=int)


def run_fold(races, held, registry, grid=GRID):
    """-> (chosen m, {model: {(scope, target): (p, y)}}, skipped cells). Identical rows for every model."""
    m, tabs, losses = tune_prior(races, held, grid)
    out = {BASELINE: {}, **{k: {} for k in registry}}
    skipped_cells = []
    for scope, targets in SCOPE_TARGETS.items():
        tab = tabs[scope]
        train, test = tab[tab["id_year"] != held], tab[tab["id_year"] == held]
        g = F.column_groups(tab)
        cols = [c for c in g["feature"] if c not in g["live_only"] and c not in DROP_FEATURES]
        for tg in targets:
            Xtr, ytr = _xy(train, cols, tg)
            if len(set(ytr)) < 2 or test.empty:
                skipped_cells.append(f"{held}|{scope}|{tg}")  # skipped for EVERY model: splits stay identical
                continue
            Xte, yte = _xy(test, cols, tg)
            out[BASELINE][(scope, tg)] = (test[baseline_col(scope, tg)].to_numpy(dtype=float), yte)
            for name, factory in registry.items():
                model = factory()
                try:
                    model.fit(Xtr, ytr, ESTIMATORS)
                    p = np.clip(np.asarray(model.predict(Xte), dtype=float), 0.0, 1.0)
                finally:
                    model.clear()
                out[name][(scope, tg)] = (p, yte)
    return m, out, skipped_cells, losses


# ---- sanity check -------------------------------------------------------------------------------------------------

def sc_rates(races) -> dict:
    """Historical share of races with a safety car (and with any SC/VSC/red) per circuit."""
    acc = {}
    for r in races:
        a = acc.setdefault(r["circuit"], {"n": 0, "sc": 0, "any": 0})
        a["n"] += 1
        a["sc"] += any(e["type"] == "sc" for e in r["events"])
        a["any"] += bool(r["events"])
    return {c: {**a, "sc_rate": a["sc"] / a["n"], "any_rate": a["any"] / a["n"]} for c, a in acc.items()}


CANADA = ("montreal", "Montréal", "Montreal")


def canada_check(rates, expected=0.60, tol=0.15, min_races=5) -> dict:
    """Plan sanity check: Canada's SC race rate near 60 %. ok None = not enough data to judge."""
    c = next((rates[k] for k in CANADA if k in rates), None)
    if c is None or c["n"] < min_races:
        return {"ok": None, "line": f"Canada SC rate: not enough races ({c['n'] if c else 0}) to check against {expected:.0%}"}
    return {"ok": abs(c["sc_rate"] - expected) <= tol,
            "line": f"Canada SC rate: {c['sc']}/{c['n']} = {c['sc_rate']:.0%} (plan expects about {expected:.0%}, tolerance {tol:.0%})"}


# ---- driver -------------------------------------------------------------------------------------------------------------

def run_backtest(races, registry=None, skipped=None, seasons=None, grid=GRID) -> dict:
    """races: ordered race dicts (history.load_races). registry: {name: factory} of optional models."""
    registry, skipped = registry or {}, dict(skipped or {})
    all_seasons = sorted({r["year"] for r in races})
    seasons = [s for s in (seasons or all_seasons) if s in all_seasons]
    if len(all_seasons) < 2 or not seasons:
        raise ValueError("backtest needs at least two stored seasons")
    names = [BASELINE, *registry]
    acc = {n: {} for n in names}  # model -> (scope, target) -> {season: (p, y)}
    chosen, cell_skips = {}, []
    for s in seasons:
        m, preds, sk, _ = run_fold(races, s, registry, grid)
        chosen[str(s)] = m
        cell_skips += sk
        for n in names:
            for key, py in preds[n].items():
                acc[n].setdefault(key, {})[s] = py
    results = {}
    for n in names:
        results[n] = {}
        for (scope, tg), by_season in sorted(acc[n].items()):
            P = np.concatenate([p for p, _ in by_season.values()])
            Y = np.concatenate([y for _, y in by_season.values()])
            results[n][f"{scope}|{tg}"] = {
                "overall": Mx.summarize(P, Y, with_reliability=True),
                "per_season": {str(s): Mx.summarize(p, y) for s, (p, y) in sorted(by_season.items())}}
    rates = sc_rates(races)
    return {"seasons": seasons, "models": names, "skipped_models": skipped, "prior_strength": chosen, "prior_grid": list(grid),
            "cells_skipped": cell_skips, "results": results,
            "sc_rate_by_circuit": {c: {k: (round(v, 3) if isinstance(v, float) else v) for k, v in r.items()} for c, r in sorted(rates.items())},
            "canada_check": canada_check(rates), "races": len(races), "dropped_features": list(DROP_FEATURES)}


def write_report(report, out_dir) -> dict:
    """JSON (everything) and CSV (one row per model, scope, target, season; season 'all' = pooled) under out_dir."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    stem = f"loso_{report['seasons'][0]}-{report['seasons'][-1]}"
    jp, cp = out / f"{stem}.json", out / f"{stem}.csv"
    jp.write_text(json.dumps(report, indent=2), encoding="utf-8")
    with cp.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["model", "scope", "target", "season", "n", "base_rate", "brier", "log_loss", "auc", "ece"])
        for model, cells in report["results"].items():
            for key, v in cells.items():
                scope, tg = key.split("|")
                for season, m in [("all", v["overall"]), *v["per_season"].items()]:
                    w.writerow([model, scope, tg, season, m["n"], m["base_rate"], m["brier"], m["log_loss"], m["auc"], m.get("ece", "")])
    return {"json": str(jp), "csv": str(cp)}


def save_run(report) -> int:
    from .models import ModelRun
    from .tasks import _git_sha

    cal = {n: {k: {"bins": v["overall"]["bins"], "ece": v["overall"]["ece"]} for k, v in cells.items()} for n, cells in report["results"].items()}
    run, _ = ModelRun.objects.update_or_create(
        model="backtest", size="", race_key=f"loso-{report['seasons'][0]}-{report['seasons'][-1]}",
        defaults={"context_rows": report["races"], "git_sha": _git_sha(), "metrics": report, "calibration": cal})
    return run.id
