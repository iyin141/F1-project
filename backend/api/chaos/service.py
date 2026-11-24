"""Payload builders for the chaos endpoints (no HTTP here). All numbers come from stored ModelRuns / ChaosPredictions
and stored labels; nothing is computed live except cheap comparisons against the history."""
from types import SimpleNamespace

from scipy.stats import beta as beta_dist

from api.models import RaceResultData

from . import history as H
from .models import CircuitProfile, ChaosPrediction, ModelRun

WINDOW = 5
AUTO, KUMO_CAL, KUMO_RAW, BASELINE = "auto", "kumo_calibrated", "kumo", "baseline"
MODEL_CHOICES = {AUTO: None, KUMO_CAL: "kumo_tabular_calibrated", KUMO_RAW: "kumo_tabular", BASELINE: "beta_binomial"}
AUTO_ORDER = ("kumo_tabular_calibrated", "beta_binomial")  # raw Kumo is only served when asked for explicitly
INDEX_TARGETS = ("sc_vsc_red", "dnf_mechanical", "dnf_incident")  # "disruptive": slow and unlucky stops are shown, not summed
LABELS = {"sc_vsc_red": "Safety car, VSC or red flag", "dnf_mechanical": "Mechanical retirement",
          "dnf_incident": "Accident or collision retirement", "slow_stop": "Slow pit stop", "unlucky_stop": "Unlucky pit stop (stop then SC/VSC)"}


class ParamError(ValueError):
    pass


class NotFound(LookupError):
    pass


# ---- params -------------------------------------------------------------------------------------------------------------

def parse_race(year, rnd):
    if not 1950 <= year <= 2100 or not 1 <= rnd <= 40:
        raise ParamError("year must be 1950-2100 and round 1-40")
    return year, rnd


def parse_model(raw) -> str:
    v = (raw or AUTO).strip().lower()
    if v not in MODEL_CHOICES:
        raise ParamError(f"model must be one of {', '.join(MODEL_CHOICES)}")
    return v


def parse_target(raw, allowed) -> str:
    v = (raw or allowed[0]).strip().lower()
    if v not in allowed:
        raise ParamError(f"target must be one of {', '.join(allowed)}")
    return v


def parse_driver(code) -> str:
    c = (code or "").strip().upper()
    if len(c) != 3 or not c.isalpha():
        raise ParamError("driver code must be 3 letters")
    return c


# ---- run selection --------------------------------------------------------------------------------------------------------

def has_history(year, rnd) -> bool:
    from django.db.models import Q

    return RaceResultData.objects.filter(session="R").filter(Q(year__lt=year) | Q(year=year, round_number__lt=rnd)).exists()


def select_run(year, rnd, choice=AUTO):
    """-> (run, block) or (None, None). Never silent: `block` always names the model served and why."""
    key = f"{year}-{rnd:02d}"
    if choice != AUTO:
        run = ModelRun.objects.filter(model=MODEL_CHOICES[choice], race_key=key).first()
        return (run, model_block(run, forced=True)) if run else (None, None)
    for m in AUTO_ORDER:
        run = ModelRun.objects.filter(model=m, race_key=key).first()
        if run:
            return run, model_block(run, forced=False)
    return None, None


def model_block(run, forced) -> dict:
    cal = run.metrics.get("calibrated")
    if run.model == "kumo_tabular_calibrated":
        calibration = "isotonic" if cal else "identity (too little backtest history: raw Kumo probabilities)"
    elif run.model == "kumo_tabular":
        calibration = "none (raw Kumo probabilities)"
    else:
        calibration = "none (Beta-Binomial posterior)"
    fallback = (not forced) and run.model == "beta_binomial"
    return {"model": run.model, "size": run.size, "run_id": run.id, "race_key": run.race_key, "context_rows": run.context_rows,
            "calibration": calibration, "calibrated": bool(cal) and run.model == "kumo_tabular_calibrated",
            "is_fallback": fallback,
            "fallback_reason": "no calibrated Kumo run exists for this race (Kumo disabled or not run yet); baseline served" if fallback else None,
            "selected_by": "request" if forced else "default order: calibrated Kumo, then baseline",
            "interval": run.metrics.get("interval", "beta_posterior_p10_p90"), "updated": run.created_at.isoformat()}


def predictions(run) -> dict:
    """{scope: {entity: {target: {probability, p10, p90}}}}"""
    out = {}
    for p in ChaosPrediction.objects.filter(model_run=run):
        out.setdefault(p.scope, {}).setdefault(p.entity, {})[p.target] = {
            "probability": round(p.probability, 5), "p10": round(p.p10, 5), "p90": round(p.p90, 5)}
    return out


def _meta(year, rnd, target) -> dict:
    return {"year": year, "round": rnd, "circuit": target["circuit"] if target else None,
            "circuit_type": target["ctype"] if target else None}


# ---- race ---------------------------------------------------------------------------------------------------------------------

def _expected(preds) -> dict:
    """Expected number of events per target, from the same run's per-entity probabilities. sc_vsc_red = sum over lap
    windows (expected neutralised windows, close to the number of neutralisations); driver targets = sum over drivers.
    Falls back to the race-level probability, and says so, when a scope is missing for a target."""
    race = preds.get("race", {}).get("", {})
    out = {}
    for t in race:
        scope = "lap_window" if t == "sc_vsc_red" else "driver"
        ents = [v[t] for v in preds.get(scope, {}).values() if t in v]
        if ents:
            out[t] = {"value": sum(e["probability"] for e in ents), "p10": sum(e["p10"] for e in ents),
                      "p90": sum(e["p90"] for e in ents), "source": f"sum of {len(ents)} {'lap windows' if scope == 'lap_window' else 'drivers'}"}
        else:
            out[t] = {"value": race[t]["probability"], "p10": race[t]["p10"], "p90": race[t]["p90"], "source": "race-level probability (at least one)"}
    return out


def _factors(year, rnd, race_preds, top=5) -> list[dict]:
    hist, target = H.target_race(year, rnd)
    if not hist or target is None:
        return []
    counts = H.Counts()
    for r in hist:
        counts.update(r)
    chain = H.race_chain(target)
    out = []
    for t, p in race_preds.items():
        glob = counts.rate("race", t, chain[:1])[0]
        typ = counts.rate("race", t, chain[:2])[0] if target["ctype"] else None
        k, n = counts.c.get(("race", t, "c", target["circuit"]), (0, 0))
        ref, ref_name = (typ, f"{target['ctype']} circuits") if typ is not None else (glob, "all circuits")
        d = p["probability"] - ref
        out.append({"target": t, "label": LABELS.get(t, t), "predicted": p["probability"], "reference": round(ref, 4),
                    "reference_name": ref_name, "difference": round(d, 4), "direction": "higher" if d > 0 else "lower",
                    "circuit_history": {"races_with_event": k, "races": n},
                    "text": f"{LABELS.get(t, t)}: {p['probability']:.0%} here vs {ref:.0%} typical for {ref_name}"
                            + (f"; happened in {k} of {n} past races at this circuit" if n else "; no past races at this circuit")})
    return sorted(out, key=lambda f: -abs(f["difference"]))[:top]


def race_payload(year, rnd, run, block) -> dict:
    preds = predictions(run)
    race = preds.get("race", {}).get("", {})
    exp = _expected(preds)
    idx = [t for t in INDEX_TARGETS if t in exp]
    _, target = H.target_race(year, rnd)
    return {"meta": _meta(year, rnd, target), "model": block, "targets": race,
            "chaos_index": round(sum(exp[t]["value"] for t in idx), 4),
            "chaos_index_band": {"p10": round(sum(exp[t]["p10"] for t in idx), 4), "p90": round(sum(exp[t]["p90"] for t in idx), 4),
                                 "note": "sums of per-entity p10/p90: a wide, conservative band, not a joint interval"},
            "index_targets": idx, "expected_events": {t: {k: (round(v, 4) if isinstance(v, float) else v) for k, v in e.items()} for t, e in exp.items()},
            "factors": _factors(year, rnd, race)}


def drivers_payload(year, rnd, run, block) -> dict:
    preds = predictions(run)
    _, target = H.target_race(year, rnd)
    teams = {c: d["team"] for c, d in (target["drivers"].items() if target else [])}
    rows = [{"driver": c, "team": teams.get(c, ""), "targets": t} for c, t in preds.get("driver", {}).items()]
    risk = lambda r: -(r["targets"].get("dnf_mechanical", {"probability": 0})["probability"] + r["targets"].get("dnf_incident", {"probability": 0})["probability"])  # noqa: E731
    return {"meta": _meta(year, rnd, target), "model": block, "ranked_by": "combined retirement probability, highest first",
            "note": "Unlucky stop is mostly luck and team strategy: a tendency with a wide interval, never a skill rating.",
            "drivers": sorted(rows, key=lambda r: (risk(r), r["driver"]))}


def laps_payload(year, rnd, run, block, target) -> dict:
    preds = predictions(run)
    _, race = H.target_race(year, rnd)
    total = race["total_laps"] if race else None
    wins = sorted(((int(e[1:]), v) for e, v in preds.get("lap_window", {}).items()))
    windows = [{"window": w, "lap_start": (w - 1) * WINDOW + 1, "lap_end": min(w * WINDOW, total) if total else w * WINDOW, "targets": v}
               for w, v in wins]
    return {"meta": {**_meta(year, rnd, race), "window_size": WINDOW, "total_laps": total,
                     "total_laps_note": "latest known race length: the median of past races until this race has run"},
            "model": block, "target": target,
            "strip": [(w["targets"].get(target) or {}).get("probability") for w in windows], "windows": windows}


# ---- circuit history / driver profile / model ---------------------------------------------------------------------------------

def circuit_list() -> dict:
    """Every circuit the matcher knows (seed overlaid with stored profiles), so clients need not guess slugs."""
    from .circuits import load_index

    stored = set(CircuitProfile.objects.values_list("slug", flat=True))
    rows = [{"slug": p["slug"], "name": p.get("name"), "type": p.get("circuit_type"), "aliases": p.get("locations", []),
             "circuit_key": p.get("circuit_key"), "length_m": p.get("length_m"), "corners": p.get("corners"),
             "stored": p["slug"] in stored} for p in load_index().profiles.values()]
    return {"count": len(rows), "history_url": "/api/chaos/circuits/<slug>/history/", "circuits": sorted(rows, key=lambda r: r["slug"])}


def circuit_history(slug) -> dict:
    from .circuits import load_index

    prof_d = load_index().profiles.get(slug.lower())
    if prof_d is None:
        raise NotFound(f"unknown circuit '{slug}': list the known slugs at /api/chaos/circuits/")
    prof = SimpleNamespace(**{k: prof_d.get(k) for k in ("slug", "name", "circuit_type", "length_m", "corners", "wall_proximity", "overtaking_index", "elevation_range_m")})
    races = [r for r in H.load_races() if r["circuit"] == prof.slug]
    rows = []
    for r in races:
        ev = r["events"]
        a = r["agg"]["race"]
        rows.append({"year": r["year"], "round": r["round"],
                     "safety_cars": sum(e["type"] == "sc" for e in ev), "vscs": sum(e["type"] == "vsc" for e in ev),
                     "red_flags": sum(e["type"] == "red_flag" for e in ev),
                     "neutralisation_laps": [e["lap"] for e in ev if e["lap"] is not None],
                     "dnf_mechanical": a["dnf_mechanical"], "dnf_incident": a["dnf_incident"],
                     "slow_stops": a["slow_stop"], "unlucky_stops": a["unlucky_stop"]})
    n = len(rows)
    share = lambda f: round(sum(1 for r in rows if f(r)) / n, 4) if n else None  # noqa: E731
    mean = lambda k: round(sum(r[k] for r in rows) / n, 3) if n else None  # noqa: E731
    return {"circuit": {"slug": prof.slug, "name": prof.name, "type": prof.circuit_type, "length_m": prof.length_m, "corners": prof.corners,
                        "wall_proximity": prof.wall_proximity, "overtaking_index": prof.overtaking_index, "elevation_range_m": prof.elevation_range_m},
            "summary": {"races": n, "safety_car_rate": share(lambda r: r["safety_cars"]), "vsc_rate": share(lambda r: r["vscs"]),
                        "red_flag_rate": share(lambda r: r["red_flags"]),
                        "any_neutralisation_rate": share(lambda r: r["safety_cars"] or r["vscs"] or r["red_flags"]),
                        "mean_mechanical_dnfs": mean("dnf_mechanical"), "mean_incident_dnfs": mean("dnf_incident")},
            "races": rows}


def driver_profile(code) -> dict:
    races = [r for r in H.load_races() if code in r["drivers"]]
    if not races:
        raise NotFound(f"no stored races for driver '{code}'")
    counts = H.Counts()
    for r in H.load_races():
        counts.update(r)
    team = races[-1]["drivers"][code]["team"]
    chain = H.drv_chain(code, team)
    out = {}
    for t in H.DRIVER_TARGETS:
        p, a, b, _ = counts.rate("drv", t, chain)
        k, n = counts.c.get(("drv", t, "d", code), (0, 0))
        out[t] = {"label": LABELS[t], "tendency": round(p, 4), "p10": round(min(p, float(beta_dist.ppf(0.10, a, b))), 4),
                  "p90": round(max(p, float(beta_dist.ppf(0.90, a, b))), 4), "races_with_event": k, "races": n}
    return {"driver": code, "last_team": team, "seasons": sorted({r["year"] for r in races}), "races": len(races),
            "label": "Tendencies, not skill ratings: shrunk toward the team and field average; read the interval, which is wide for few races.",
            "tendencies": out}


def _run_row(run) -> dict:
    m = run.metrics or {}
    return {"id": run.id, "model": run.model, "size": run.size, "race_key": run.race_key, "context_rows": run.context_rows, "git_sha": run.git_sha,
            "updated": run.created_at.isoformat(), "calibrated": m.get("calibrated"), "interval": m.get("interval"),
            "calibration": run.calibration if run.model.startswith("kumo") else None}


def model_page() -> dict:
    current = []
    for m in ("kumo_tabular_calibrated", "kumo_tabular", "beta_binomial"):
        run = ModelRun.objects.filter(model=m).order_by("-created_at", "-id").first()
        if run:
            current.append(_run_row(run))
    bt = ModelRun.objects.filter(model="backtest").order_by("-created_at", "-id").first()
    backtest = None
    if bt:
        m = bt.metrics
        backtest = {"run_id": bt.id, "seasons": m.get("seasons"), "models": m.get("models"), "skipped_models": m.get("skipped_models"),
                    "prior_strength": m.get("prior_strength"), "canada_check": m.get("canada_check"), "races": m.get("races"),
                    "results": {mod: {cell: v["overall"] for cell, v in cells.items()} for mod, cells in (m.get("results") or {}).items()},
                    "note": "overall = pooled leave-one-season-out predictions; bins are the 10-bin reliability table"}
    return {"current_runs": current, "backtest": backtest}
