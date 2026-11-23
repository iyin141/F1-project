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
