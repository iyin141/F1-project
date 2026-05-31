"""
Celery task definitions for F1 data population.

Pattern for each task:
  1. @shared_task(bind=True, max_retries=0)
  2. Accept task_key as first argument
  3. mark_running(task_key)
  4. Call the run() function from the management command directly (no call_command)
  5. mark_complete(task_key) — ONLY after DB write confirmed
  6. On exception: mark_failed(task_key, exc)

Task key formats (must match persistence spec exactly):
  schedule:{year}
  race_results:{year}:{round}
  sprint_results:{year}:{round}
  sprint_shootout:{year}:{round}
  qualifying:{year}:{round}
  practice:{year}:{round}:{session}
  laps/pace/sector/stints/tyre_strategy:{year}:{round}   (written by populate_race)
  telemetry:{year}:{round}:{session}:{driver_code}:{lap}
  telemetry_overlay:{year}:{round}:{session}:{lap}
  telemetry_summary:{year}:{round}:{session}:{driver_code}
  session_data:{year}:{round}:{session}
  standings:{year}
  constructor_standings:{year}
  driver_career:{driver_code}
  driver_season:{driver_code}:{year}
"""
from __future__ import annotations

import logging

from celery import shared_task

from api.services.task_manager import TaskManager
from api.workers.tier6_notifications.email_helpers import send_plain_api_key_email

logger = logging.getLogger(__name__)

# Tier1 task implementations moved to worker modules
from api.workers.tier1_instant.populate_standings import populate_standings
from api.workers.tier1_instant.populate_constructor_standings import populate_constructor_standings
from api.workers.tier1_instant.populate_schedule import populate_schedule
from api.workers.tier1_instant.populate_driver_career import populate_driver_career
from api.workers.tier1_instant.populate_driver_season import populate_driver_season
from api.workers.tier1_instant.check_for_completed_sessions import check_for_completed_sessions
from api.workers.tier2_fast.populate_race_results import populate_race_results
from api.workers.tier2_fast.populate_session_data import populate_session_data
from api.workers.tier2_fast.populate_weather import populate_weather
from api.workers.tier2_fast.populate_incidents import populate_incidents
from api.workers.tier2_fast.populate_pit_stops import populate_pit_stops
from api.workers.tier2_fast.prefetch_race_weekend import prefetch_race_weekend
from api.workers.tier2_fast.seed_historical_round import seed_historical_round
from api.workers.tier3_medium.sync_drivers_task import sync_drivers_task
from api.workers.tier3_medium.sync_champions_task import sync_champions_task
from api.workers.tier4_telemetry.populate_telemetry import populate_telemetry
from api.workers.tier4_telemetry.sync_all_drivers_task import sync_all_drivers_task
from api.workers.tier5_pagination.paginate_laps import paginate_laps
from api.workers.tier5_pagination.paginate_positions import paginate_positions
from api.workers.tier5_pagination.paginate_telemetry import paginate_telemetry
from api.workers.tier6_notifications.send_verification_email import send_verification_email
from api.workers.tier6_notifications.send_welcome_email import send_welcome_email
from api.workers.tier6_notifications.send_tier_upgrade_email import send_tier_upgrade_email
from api.workers.tier6_notifications.send_rate_limit_warning_email import send_rate_limit_warning_email
from api.workers.tier6_notifications.send_key_revocation_email import send_key_revocation_email
from api.workers.tier6_notifications.send_monthly_usage_report import send_monthly_usage_report
from api.workers.tier6_notifications.send_api_key_email import send_api_key_email
from api.workers.tier6_notifications.send_rate_limit_warning import send_rate_limit_warning
from api.workers.tier6_notifications.send_usage_summary import send_usage_summary
from api.workers.tier6_notifications.send_usage_summary_all import send_usage_summary_all
from api.workers.tier6_notifications.update_api_key_usage import update_api_key_usage


# `populate_standings` moved to `api.workers.tier1_instant.populate_standings`


# `populate_race_results` moved to `api.workers.tier2_fast.populate_race_results`


# `populate_session_data` moved to `api.workers.tier2_fast.populate_session_data`


@shared_task(bind=True, max_retries=0, queue="tier4_telemetry", ack_late=True)
def populate_telemetry(
    self,
    task_key: str,
    year: int,
    round_number: int,
    session_type: str,
    driver_code: str,
):
    """
    Populate DriverTelemetry for one driver — all laps stored in a single row.
    Task key: telemetry:{year}:{round_number}:{session}:{driver_code}
    """
    # `populate_telemetry` moved to `api.workers.tier4_telemetry.populate_telemetry`


# `populate_constructor_standings` moved to `api.workers.tier1_instant.populate_constructor_standings`


# `populate_schedule` moved to `api.workers.tier1_instant.populate_schedule`


# `populate_driver_career` moved to `api.workers.tier1_instant.populate_driver_career`


# `populate_driver_season` moved to `api.workers.tier1_instant.populate_driver_season`


# `populate_weather` moved to `api.workers.tier2_fast.populate_weather`


# `populate_incidents` moved to `api.workers.tier2_fast.populate_incidents`


# `populate_pit_stops` moved to `api.workers.tier2_fast.populate_pit_stops`


# ---------------------------------------------------------------------------
# Phase 6: historical seeding + prefetch + beat
# ---------------------------------------------------------------------------

_SEED_SESSION_MAP: dict[str, str] = {
    "race_results": "R",
    "qualifying": "Q",
    "sprint_results": "S",
    "sprint_shootout": "SQ",
}


# `seed_historical_round` moved to `api.workers.tier2_fast.seed_historical_round`


# `prefetch_race_weekend` moved to `api.workers.tier2_fast.prefetch_race_weekend`


# `check_for_completed_sessions` moved to `api.workers.tier1_instant.check_for_completed_sessions`


# =========================================================================
# Driver Sync Tasks — F1Driver model synchronization (Phase 8)
# =========================================================================


@shared_task(bind=True, max_retries=0, queue="tier3_medium")
def sync_drivers_task(self, task_key: str, year: int):
    """
    Sync drivers for a single season asynchronously via Celery.
    
    Uses DriverSyncService to fetch drivers from Jolpica and upsert to F1Driver model.
    Task key: sync_drivers:{year}
    """
    # Registration & Email Tasks — API key lifecycle management
    # Implementations moved to per-queue worker modules under:
    # backend/api/workers/tier6_notifications/
    #
    # Exported task functions are imported at the top of this module so
    # CELERY_TASK_ROUTES and other code can continue referencing the
    # original task names (e.g. `send_verification_email`, `send_api_key_email`).
@shared_task(bind=False, max_retries=1, queue="tier6_notifications")
def send_usage_summary_all():
    """
    Broadcast usage summary emails to all active API keys.
    
    Queried by weekly beat schedule (604800s = 7 days).
    Iterates through all active APIKeys and sends monthly report to each.
    
    Task key: scheduled_send_usage_summary_all
    """
    logger.info("event=celery_start task=send_usage_summary_all")
    
    try:
        from api.models import APIKey
        from datetime import datetime, timedelta
        
        # Get all active API keys
        active_keys = APIKey.objects.filter(is_active=True)
        sent_count = 0
        
        # For each key, calculate requests in last 30 days and send report
        thirty_days_ago = datetime.now() - timedelta(days=30)
        
        for api_key in active_keys:
            # Calculate usage for this key in last 30 days
            # This would normally query a usage analytics table
            # For now, use request_count as a proxy
            requests_count = api_key.request_count
            
            task_key = f"email_usage_summary_all:{api_key.id}"
            logger.info("event=sending_usage_summary email=%s key_id=%s", api_key.email, api_key.id)
            
            send_usage_summary.apply_async(
                args=(task_key, str(api_key.id), api_key.email, requests_count, api_key.tier),
                queue="tier6_notifications",
            )
            sent_count += 1
        
        logger.info("event=celery_success task=send_usage_summary_all sent_count=%d", sent_count)
    except Exception as exc:
        logger.exception("event=celery_failed task=send_usage_summary_all error=%s", exc)
        raise


# =========================================================================
# API Key Usage Tracking Task — tier6_notifications queue
# =========================================================================

@shared_task(bind=False, max_retries=0, queue="tier6_notifications")
def update_api_key_usage(api_key_id: str):
    """
    Asynchronously update API key usage (last_used_at and request_count).
    
    Called from APIKeyAuthentication.authenticate() for every authenticated request.
    Uses F() expression for atomic DB-level increment to avoid stale-object issues.
    
    This is a fire-and-forget task; failures are logged but don't block auth.
    Without a Celery worker running, the task queues but doesn't execute (acceptable for local testing).
    """
    try:
        from api.models.auth import APIKey
        from django.db.models import F
        from django.utils import timezone
        
        APIKey.objects.filter(id=api_key_id).update(
            last_used_at=timezone.now(),
            request_count=F("request_count") + 1,
        )
        logger.debug("event=api_key_usage_updated api_key_id=%s", api_key_id)
    except Exception as exc:
        logger.warning("event=api_key_usage_update_failed api_key_id=%s error=%s", api_key_id, exc)
