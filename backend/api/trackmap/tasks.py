"""Celery tasks for the trackmap app (routed to tier4_telemetry by module)."""
from __future__ import annotations

import json
import logging

from celery import shared_task
from django.core.cache import caches

from api.services.unified_service import SessionManager

from .geometry import build_from_session
from .models import TrackGeometry
from .service import built_key, geometry_cache_key, geometry_payload, get_geometry_payload, track_map_response  # noqa: F401

logger = logging.getLogger(__name__)


def _load_session(year: int, round_number: int):
    # Qualifying holds the pole lap; fall back to the race if Q is unavailable.
    for st in ("Q", "R"):
        try:
            return SessionManager.get_session(year, round_number, st, required_types=["telemetry"]), st
        except Exception as exc:  # noqa: BLE001
            logger.warning("[trackmap] %s %s/%s load failed: %s", st, year, round_number, exc)
    raise RuntimeError(f"no session with telemetry for {year} R{round_number}")


@shared_task(name="api.trackmap.tasks.build_track_geometry", max_retries=0)
def build_track_geometry(year: int, round_number: int) -> dict:
    """Build and permanently cache the track geometry for one race weekend.

    Idempotent: a second call for the same (year, round) returns the stored row
    without touching FastF1; the same layout from another year reuses its row.
    """
    cache = caches["telemetry_cache"]
    ptr = cache.get(built_key(year, round_number))
    if ptr:
        existing = TrackGeometry.objects.filter(circuit_key=ptr[0], layout_hash=ptr[1]).first()
        if existing:
            return {"status": "exists", "circuit_key": existing.circuit_key, "layout_hash": existing.layout_hash}

    session, st = _load_session(year, round_number)
    circuit_key, fields, who = build_from_session(session)
    layout_hash = fields.pop("layout_hash")
    geom, created = TrackGeometry.objects.get_or_create(
        circuit_key=circuit_key,
        layout_hash=layout_hash,
        defaults={"year": year, "source": f"{year} R{round_number} {st} {who}", **fields},
    )
    cache.set(geometry_cache_key(circuit_key, layout_hash), json.dumps(geometry_payload(geom)), timeout=None)
    cache.set(built_key(year, round_number), [circuit_key, layout_hash], timeout=None)
    return {"status": "created" if created else "exists", "circuit_key": circuit_key, "layout_hash": layout_hash}


@shared_task(bind=True, max_retries=0, queue="tier4_telemetry")
def populate_track_geometry(self, task_key: str, year: int, round_number: int, scheme: str = "distance", **kwargs):
    """Task-manager wrapper (task_key first, like the populate_* tasks): builds the geometry,
    then publishes the track-map response so a waiting SSE/JSON stream completes."""
    from django.utils import timezone

    from api.models import TaskRecord
    from api.services import pubsub, worker_utils

    TaskRecord.objects.filter(task_key=task_key).update(status="running", started_at=timezone.now())
    try:
        build_track_geometry(year, round_number)
        geom = get_geometry_payload(year, round_number)
        if geom is None:
            raise RuntimeError("geometry build finished but nothing was stored")
        worker_utils.handle_result(
            task_key=task_key,
            data_type="track_map",
            serialized_data=track_map_response(geom, scheme, year, round_number),
            cache_key=task_key,
        )
    except Exception as exc:
        pubsub.publish_error(task_key, str(exc))
        TaskRecord.objects.filter(task_key=task_key).update(status="failed", completed_at=timezone.now())
        logger.error("event=celery_exception task=populate_track_geometry task_key=%s error=%s", task_key, exc)
        raise
