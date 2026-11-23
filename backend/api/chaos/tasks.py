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
    from . import features as F
    from . import history as H
    from .models import FeatureSet

    races = H.load_races()
    if not races:
        return {"status": "no_races"}
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
    return {"status": "ok", "version": version, "rows": made}


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

    target_key = (year, round_number)
    hist = [r for r in H.load_races(up_to=target_key) if H.race_key(r) < target_key]
    if not hist:
        return {"status": "no_history", "year": year, "round": round_number}
    meta = H.race_meta(year, round_number, H.circuit_lookup())
    res = RaceResultData.objects.filter(year=year, round_number=round_number, session="R").first()
    results = list((res.payload or {}).get("results", [])) if res else []
    if results:  # race already run: its own driver list and length (codes as build_labels resolves them)
        now = next((r for r in H.load_races(up_to=target_key) if H.race_key(r) == target_key), None)
        drivers, n_win = now["drivers"], -(-now["total_laps"] // 5)
    else:  # upcoming race: assume the latest race's field and the median past length
        drivers = hist[-1]["drivers"]
        laps = sorted(r["total_laps"] for r in hist)
        n_win = -(-laps[len(laps) // 2] // 5)
    preds = B.predict(hist, meta, n_windows=n_win, drivers=drivers)
    with transaction.atomic():
        run, _ = ModelRun.objects.update_or_create(
            model=B.MODEL, size="", race_key=f"{year}-{round_number:02d}",
            defaults={"context_rows": len(hist), "git_sha": _git_sha(),
                      "metrics": {"history_races": len(hist), "prior_strength": H.PRIOR_M, "n_predictions": len(preds)}})
        run.predictions.all().delete()
        ChaosPrediction.objects.bulk_create(
            [ChaosPrediction(year=year, round_number=round_number, model_run=run, **p) for p in preds])
    return {"status": "ok", "model_run": run.id, "predictions": len(preds), "history_races": len(hist)}
