"""Celery tasks for chaos (routed to tier3_medium by module). Torch/sdm never here: see ml_tasks.py."""
import logging

from celery import shared_task
from django.db import transaction

from api.models import IncidentData, PitStopData, PositionData, RaceResultData, TrackStatusData

from . import labels as L
from .models import RaceEventLabel

logger = logging.getLogger(__name__)


def _rows(model, year, rnd):
    obj = model.objects.filter(year=year, round_number=rnd, session="R").first()
    return list((obj.payload or {}).get("data", [])) if obj else []


def _season_durations(year):
    out = []
    for obj in PitStopData.objects.filter(year=year, session="R"):
        out += [s.get("stop_duration_seconds") for s in (obj.payload or {}).get("data", [])]
    return out


@shared_task(name="api.chaos.tasks.build_labels", max_retries=0)
def build_labels(year: int, round_number: int) -> dict:
    """Rebuild every RaceEventLabel for one race from stored data. Idempotent: the race's rows are replaced in one
    transaction, so a repeat call gives the same rows. Skips (returns status) when there is no stored race result."""
    res = RaceResultData.objects.filter(year=year, round_number=round_number, session="R").first()
    results = list((res.payload or {}).get("results", [])) if res else []
    if not results:
        return {"status": "no_results", "year": year, "round": round_number}

    stops = _rows(PitStopData, year, round_number)
    # driver number -> 3-letter code, from any stored table carrying both
    ids = {}
    for r in stops + _rows(PositionData, year, round_number):
        if r.get("driver_number") is not None and r.get("driver_code"):
            ids[r["driver_number"]] = r["driver_code"]
    teams = {ids[r["driver_number"]]: r.get("team") or "" for r in results if r.get("driver_number") in ids}
    total_laps = max((r.get("laps") or 0 for r in results), default=0)

    smap = L.load_status_map()
    neutral, notes = L.neutral_events(_rows(TrackStatusData, year, round_number), _rows(IncidentData, year, round_number))
    threshold = L.season_threshold(_season_durations(year))
    rows = (
        [dict(year=year, round_number=round_number, **e) for e in neutral]
        + L.dnf_labels(year, round_number, results, ids, total_laps, smap)
        + L.pit_labels(year, round_number, stops, neutral, threshold, teams)
    )
    with transaction.atomic():
        RaceEventLabel.objects.filter(year=year, round_number=round_number).delete()
        RaceEventLabel.objects.bulk_create([RaceEventLabel(**r) for r in rows])
    from .cache import bump_version

    transaction.on_commit(bump_version)  # new labels: cached circuit history, summaries and profiles are stale
    unmapped = sorted({r["detail"]["status"] for r in rows if r.get("detail", {}).get("unmapped")})
    if notes or unmapped:
        logger.warning("[chaos] %s R%s labels: crosscheck=%s unmapped_statuses=%s", year, round_number, notes, unmapped)
    return {"status": "ok", "year": year, "round": round_number, "labels": len(rows), "total_laps": total_laps,
            "slow_threshold": threshold, "crosscheck_mismatches": notes, "unmapped_statuses": unmapped}


def label_aggregates(year: int, round_number: int) -> dict:
    """Race / driver-race / 5-lap-window targets for one race, from stored labels (used by build_features in 2b)."""
    res = RaceResultData.objects.filter(year=year, round_number=round_number, session="R").first()
    results = list((res.payload or {}).get("results", [])) if res else []
    total = max((r.get("laps") or 0 for r in results), default=0)
    events = list(RaceEventLabel.objects.filter(year=year, round_number=round_number).values("type", "driver", "lap"))
    drivers = sorted({e["driver"] for e in events if e["driver"]})
    return L.aggregate_labels(events, total, drivers)


# ---- Phase 2b: features and baseline -------------------------------------------------------------------------

def features_dir():
    """CHAOS_FEATURES_DIR, else <DATA_DIR or ~/.f1_control_room>/chaos_features. Never inside the repo."""
    import os
    from pathlib import Path

    base = os.environ.get("CHAOS_FEATURES_DIR")
    return Path(base) if base else Path(os.environ.get("DATA_DIR") or Path.home() / ".f1_control_room") / "chaos_features"


@shared_task(name="api.chaos.tasks.build_features", max_retries=0)
def build_features() -> dict:
    """Write one Parquet per scope covering every race with stored results, and register a FeatureSet each.
    Idempotent: the version is derived from the data (feature version, mapping version, race count, last race), so a
    rerun overwrites the same files and updates the same rows."""
    from . import circuits as CI
    from . import features as F
    from . import history as H
    from .models import FeatureSet

    # circuit identity first: seed rows must exist and geometry-derived keys be linked before features read them
    CI.populate_circuit_profiles()
    linked = CI.link_circuit_keys()
    races = H.load_races()
    if not races:
        return {"status": "no_races"}
    unmatched = sorted({(r["year"], r["round"], r["location"], r["event_name"]) for r in races if not r["circuit_matched"]})
    if unmatched:
        logger.warning("[chaos] build_features: %d race(s) have NO matching circuit (circuit features empty for them): %s",
                       len(unmatched), unmatched[:10])
    smap = L.load_status_map()
    last = races[-1]
    version = f"f{F.FEATURE_VERSION}-m{smap['version']}-n{len(races)}-{last['year']}R{last['round']}"
    out_dir = features_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    made = {}
    for scope, df in F.build_tables(races).items():
        F.check_limits(scope, df)
        path = out_dir / f"{version}_{scope}.parquet"
        df.to_parquet(path, index=False)
        groups = F.column_groups(df)
        FeatureSet.objects.update_or_create(
            version=version, scope=scope,
            defaults={"path": str(path), "columns": list(df.columns), "row_count": len(df),
                      "meta": {**groups, "mapping_version": str(smap["version"]), "feature_version": F.FEATURE_VERSION}})
        made[scope] = len(df)
    return {"status": "ok", "version": version, "rows": made, "circuit_links_made": linked,
            "unmatched_circuits": [{"year": y, "round": r, "location": loc, "event_name": n} for y, r, loc, n in unmatched]}


def _git_sha() -> str:
    import subprocess

    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, timeout=5).stdout.strip()[:40]
    except Exception:  # noqa: BLE001
        return ""


@shared_task(name="api.chaos.tasks.run_baseline", max_retries=0)
def run_baseline(year: int, round_number: int) -> dict:
    """Beta-Binomial predictions for one race from races strictly before it (so a past race is back-tested honestly).
    Idempotent: one ModelRun per (model, race); its predictions are replaced."""
    from . import baseline as B
    from . import history as H
    from .models import ChaosPrediction, ModelRun

    hist, target = H.target_race(year, round_number)
    if not hist:
        return {"status": "no_history", "year": year, "round": round_number}
    preds = B.predict(hist, target, n_windows=len(target["agg"]["windows"]), drivers=target["drivers"])
    with transaction.atomic():
        run, _ = ModelRun.objects.update_or_create(
            model=B.MODEL, size="", race_key=f"{year}-{round_number:02d}",
            defaults={"context_rows": len(hist), "git_sha": _git_sha(),
                      "metrics": {"history_races": len(hist), "prior_strength": H.PRIOR_M, "n_predictions": len(preds)}})
        run.predictions.all().delete()
        ChaosPrediction.objects.bulk_create(
            [ChaosPrediction(year=year, round_number=round_number, model_run=run, **p) for p in preds])
    mark_pipeline_done(year, round_number)
    return {"status": "ok", "model_run": run.id, "predictions": len(preds), "history_races": len(hist)}


# ---- Phase 2c: pipeline ----------------------------------------------------------------------------------------

def kumo_enabled() -> bool:
    import os

    return os.environ.get("CHAOS_ENABLE_KUMO", "").strip().lower() in ("1", "true", "yes", "on")


def build_pipeline(year: int, round_number: int):
    """Celery chain: build_labels -> build_features -> run_baseline [-> run_kumo -> calibrate_and_store when
    CHAOS_ENABLE_KUMO]. All signatures immutable (each step reads the DB, not the previous result). The ml steps are
    referenced by task name, so this process never imports them; the module routes put them on the `ml` queue."""
    from celery import chain, current_app

    steps = [build_labels.si(year, round_number), build_features.si(), run_baseline.si(year, round_number)]
    if kumo_enabled():
        steps += [current_app.signature(f"api.chaos.ml_tasks.{n}", args=(year, round_number), immutable=True)
                  for n in ("run_kumo", "calibrate_and_store")]
    return chain(*steps)


@shared_task(name="api.chaos.tasks.run_chaos_pipeline", max_retries=0)
def run_chaos_pipeline(year: int, round_number: int) -> dict:
    res = build_pipeline(year, round_number).apply_async()
    return {"status": "queued", "year": year, "round": round_number, "kumo": kumo_enabled(), "chain_id": res.id}


def pipeline_targets():
    """[(year, round)]: the latest race with a stored result (re-run after the race) and the round after it
    (before the race), if the schedule has it (next season's round 1 at season end)."""
    from api.models import SeasonSchedule

    last = RaceResultData.objects.filter(session="R").order_by("-year", "-round_number").first()
    if last is None:
        return []
    out = [(last.year, last.round_number)]
    for y, r in ((last.year, last.round_number + 1), (last.year + 1, 1)):
        sched = SeasonSchedule.objects.filter(year=y).first()
        if sched and any(x.get("round") == r for x in sched.payload.get("races", [])):
            out.append((y, r))
            break
    return out


@shared_task(name="api.chaos.tasks.refresh_chaos", max_retries=0)
def refresh_chaos() -> dict:
    """Beat entry point: run the pipeline for the latest completed race and the next scheduled one. Idempotent."""
    targets = pipeline_targets()
    return {"targets": targets, "runs": [run_chaos_pipeline(y, r) for y, r in targets]}


def pipeline_task_key(year, round_number) -> str:
    return f"chaos:{year}:{round_number}"


def mark_pipeline_done(year, round_number):
    """Predictions exist: close the TaskRecord the endpoints opened while the caller got 202 pending."""
    from django.utils import timezone

    from api.models import TaskRecord

    TaskRecord.objects.filter(task_key=pipeline_task_key(year, round_number)).update(status="complete", completed_at=timezone.now())


@shared_task(bind=True, max_retries=0)
def populate_chaos(self, task_key: str, year: int, round_number: int, **kwargs):
    """Task-manager wrapper (task_key first, like the populate_* tasks) used by the endpoints: runs the pipeline chain.
    The record stays `running` until run_baseline finishes (mark_pipeline_done), so repeated requests do not requeue."""
    from django.utils import timezone

    from api.models import TaskRecord

    TaskRecord.objects.filter(task_key=task_key).update(status="running", started_at=timezone.now())
    try:
        build_pipeline(year, round_number).apply_async()
    except Exception as exc:
        TaskRecord.objects.filter(task_key=task_key).update(status="failed", completed_at=timezone.now(), error_message=str(exc)[:500])
        raise
