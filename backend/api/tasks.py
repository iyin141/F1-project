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

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=0, queue="tier1_instant")
def populate_standings(self, task_key: str, year: int):
    """
    Populate DriverStandings for a season year.
    Task key: standings:{year}
    """
    logger.info("event=celery_start task=populate_standings task_key=%s year=%s", task_key, year)
    TaskManager.mark_running(task_key)

    try:
        from api.management.commands.populate_standings import run
        run(year=int(year))
        TaskManager.mark_complete(task_key)
        logger.info("event=celery_success task=populate_standings task_key=%s year=%s", task_key, year)
    except Exception as exc:
        TaskManager.mark_failed(task_key, exc)
        logger.exception("event=celery_failed task=populate_standings task_key=%s year=%s", task_key, year)
        raise


@shared_task(bind=True, max_retries=0, queue="tier2_fast")
def populate_race_results(self, task_key: str, year: int, round_number: int, session_type: str):
    """
    Populate race results (R, Q, FP1-3, S, SQ).
    Task key: race_results/qualifying/practice/sprint_results/sprint_shootout:{year}:{round}
    """
    logger.info(
        "event=celery_start task=populate_race_results task_key=%s year=%s round=%s session=%s",
        task_key, year, round_number, session_type,
    )
    TaskManager.mark_running(task_key)

    try:
        from api.management.commands.populate_race import run
        run(year=int(year), round_number=int(round_number), session_type=str(session_type))
        TaskManager.mark_complete(task_key)
        logger.info(
            "event=celery_success task=populate_race_results task_key=%s year=%s round=%s session=%s",
            task_key, year, round_number, session_type,
        )
    except Exception as exc:
        TaskManager.mark_failed(task_key, exc)
        logger.exception(
            "event=celery_failed task=populate_race_results task_key=%s year=%s round=%s session=%s",
            task_key, year, round_number, session_type,
        )
        raise


@shared_task(bind=True, max_retries=0, queue="tier2_fast")
def populate_session_data(self, task_key: str, year: int, round_number: int, session_type: str):
    """
    Populate unified SessionData (weather, pit_stops, incidents, positions, drs, track_status).
    Task key: session_data:{year}:{round}:{session}
    """
    logger.info(
        "event=celery_start task=populate_session_data task_key=%s year=%s round=%s session=%s",
        task_key, year, round_number, session_type,
    )
    TaskManager.mark_running(task_key)

    try:
        from api.management.commands.populate_session import run
        run(year=int(year), round_number=int(round_number), session_type=str(session_type))
        TaskManager.mark_complete(task_key)
        logger.info(
            "event=celery_success task=populate_session_data task_key=%s year=%s round=%s session=%s",
            task_key, year, round_number, session_type,
        )
    except Exception as exc:
        TaskManager.mark_failed(task_key, exc)
        logger.exception(
            "event=celery_failed task=populate_session_data task_key=%s year=%s round=%s session=%s",
            task_key, year, round_number, session_type,
        )
        raise


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
    logger.info(
        "event=celery_start task=populate_telemetry task_key=%s year=%s round=%s session=%s driver=%s",
        task_key, year, round_number, session_type, driver_code,
    )
    TaskManager.mark_running(task_key)

    try:
        from api.management.commands.populate_telemetry import run
        run(
            year=int(year),
            round_number=int(round_number),
            session_type=str(session_type),
            driver_code=str(driver_code),
        )
        TaskManager.mark_complete(task_key)
        logger.info(
            "event=celery_success task=populate_telemetry task_key=%s year=%s round=%s session=%s driver=%s",
            task_key, year, round_number, session_type, driver_code,
        )
    except Exception as exc:
        TaskManager.mark_failed(task_key, exc)
        logger.exception(
            "event=celery_failed task=populate_telemetry task_key=%s year=%s round=%s session=%s driver=%s",
            task_key, year, round_number, session_type, driver_code,
        )
        raise


@shared_task(bind=True, max_retries=0, queue="tier1_instant")
def populate_constructor_standings(self, task_key: str, year: int):
    """
    Populate ConstructorStandings for a season year.
    Task key: constructor_standings:{year}
    """
    logger.info("event=celery_start task=populate_constructor_standings task_key=%s year=%s", task_key, year)
    TaskManager.mark_running(task_key)

    try:
        from api.management.commands.populate_constructor_standings import run
        run(year=int(year))
        TaskManager.mark_complete(task_key)
        logger.info("event=celery_success task=populate_constructor_standings task_key=%s year=%s", task_key, year)
    except Exception as exc:
        TaskManager.mark_failed(task_key, exc)
        logger.exception("event=celery_failed task=populate_constructor_standings task_key=%s year=%s", task_key, year)
        raise


@shared_task(bind=True, max_retries=0, queue="tier1_instant")
def populate_schedule(self, task_key: str, year: int):
    """
    Populate SeasonSchedule for a season year.
    Task key: schedule:{year}
    """
    logger.info("event=celery_start task=populate_schedule task_key=%s year=%s", task_key, year)
    TaskManager.mark_running(task_key)

    try:
        from api.management.commands.populate_schedule import run
        run(year=int(year))
        TaskManager.mark_complete(task_key)
        logger.info("event=celery_success task=populate_schedule task_key=%s year=%s", task_key, year)
    except Exception as exc:
        TaskManager.mark_failed(task_key, exc)
        logger.exception("event=celery_failed task=populate_schedule task_key=%s year=%s", task_key, year)
        raise


@shared_task(bind=True, max_retries=0, queue="tier1_instant")
def populate_driver_career(self, task_key: str, driver_code: str):
    """
    Populate DriverCareer for a driver.
    Task key: driver_career:{driver_code}
    """
    logger.info("event=celery_start task=populate_driver_career task_key=%s driver=%s", task_key, driver_code)
    TaskManager.mark_running(task_key)

    try:
        from api.management.commands.populate_driver_career import run
        run(driver_code=str(driver_code))
        TaskManager.mark_complete(task_key)
        logger.info("event=celery_success task=populate_driver_career task_key=%s driver=%s", task_key, driver_code)
    except Exception as exc:
        TaskManager.mark_failed(task_key, exc)
        logger.exception("event=celery_failed task=populate_driver_career task_key=%s driver=%s", task_key, driver_code)
        raise


@shared_task(bind=True, max_retries=0, queue="tier1_instant")
def populate_driver_season(self, task_key: str, driver_code: str, year: int):
    """
    Populate DriverSeasonBreakdown for a driver/year.
    Task key: driver_season:{driver_code}:{year}
    """
    logger.info("event=celery_start task=populate_driver_season task_key=%s driver=%s year=%s", task_key, driver_code, year)
    TaskManager.mark_running(task_key)

    try:
        from api.management.commands.populate_driver_season import run
        run(driver_code=str(driver_code), year=int(year))
        TaskManager.mark_complete(task_key)
        logger.info("event=celery_success task=populate_driver_season task_key=%s driver=%s year=%s", task_key, driver_code, year)
    except Exception as exc:
        TaskManager.mark_failed(task_key, exc)
        logger.exception("event=celery_failed task=populate_driver_season task_key=%s driver=%s year=%s", task_key, driver_code, year)
        raise


@shared_task(bind=True, max_retries=0, queue="tier2_fast")
def populate_weather(self, task_key: str, year: int, round_number: int):
    """
    Populate weather data for a race session.
    Task key: weather:{year}:{round}
    Phase 6: Used in race completion prefetching and historical seeding.
    """
    logger.info("event=celery_start task=populate_weather task_key=%s year=%s round=%s", task_key, year, round_number)
    TaskManager.mark_running(task_key)

    try:
        from api.management.commands.populate_race import run
        # Weather is typically loaded as part of race session data
        run(year=int(year), round_number=int(round_number), session_type="R")
        TaskManager.mark_complete(task_key)
        logger.info("event=celery_success task=populate_weather task_key=%s year=%s round=%s", task_key, year, round_number)
    except Exception as exc:
        TaskManager.mark_failed(task_key, exc)
        logger.exception("event=celery_failed task=populate_weather task_key=%s year=%s round=%s", task_key, year, round_number)
        raise


@shared_task(bind=True, max_retries=0, queue="tier2_fast")
def populate_incidents(self, task_key: str, year: int, round_number: int):
    """
    Populate incidents/race control messages for a race.
    Task key: incidents:{year}:{round}
    Phase 6: Used in race completion prefetching and historical seeding.
    """
    logger.info("event=celery_start task=populate_incidents task_key=%s year=%s round=%s", task_key, year, round_number)
    TaskManager.mark_running(task_key)

    try:
        from api.management.commands.populate_race import run
        # Incidents loaded as part of race results
        run(year=int(year), round_number=int(round_number), session_type="R")
        TaskManager.mark_complete(task_key)
        logger.info("event=celery_success task=populate_incidents task_key=%s year=%s round=%s", task_key, year, round_number)
    except Exception as exc:
        TaskManager.mark_failed(task_key, exc)
        logger.exception("event=celery_failed task=populate_incidents task_key=%s year=%s round=%s", task_key, year, round_number)
        raise


@shared_task(bind=True, max_retries=0, queue="tier2_fast")
def populate_pit_stops(self, task_key: str, year: int, round_number: int):
    """
    Populate pit stop data for a race.
    Task key: pit_stops:{year}:{round}
    Phase 6: Used in historical seeding.
    """
    logger.info("event=celery_start task=populate_pit_stops task_key=%s year=%s round=%s", task_key, year, round_number)
    TaskManager.mark_running(task_key)

    try:
        from api.management.commands.populate_race import run
        # Pit stops loaded as part of race results
        run(year=int(year), round_number=int(round_number), session_type="R")
        TaskManager.mark_complete(task_key)
        logger.info("event=celery_success task=populate_pit_stops task_key=%s year=%s round=%s", task_key, year, round_number)
    except Exception as exc:
        TaskManager.mark_failed(task_key, exc)
        logger.exception("event=celery_failed task=populate_pit_stops task_key=%s year=%s round=%s", task_key, year, round_number)
        raise


# ---------------------------------------------------------------------------
# Phase 6: historical seeding + prefetch + beat
# ---------------------------------------------------------------------------

_SEED_SESSION_MAP: dict[str, str] = {
    "race_results": "R",
    "qualifying": "Q",
    "sprint_results": "S",
    "sprint_shootout": "SQ",
}


@shared_task(bind=True, max_retries=0, queue="backfill", rate_limit="3/m")
def seed_historical_round(self, task_key: str, year: int, round_number: int, data_types: list):
    """
    Seed a single historical round for the given data_types.

    Dispatches sub-tasks (populate_race_results / populate_session_data) for
    each requested type so that backfill can be interrupted and resumed without
    losing partial progress.

    Task key: seed_round:{year}:{round}
    Phase 6: Dispatched by seed_historical management command / seeding service.
    """
    logger.info(
        "event=celery_start task=seed_historical_round task_key=%s year=%s round=%s types=%s",
        task_key, year, round_number, data_types,
    )
    TaskManager.mark_running(task_key)

    try:
        for dtype in data_types:
            session_type = _SEED_SESSION_MAP.get(dtype)
            if session_type:
                sub_key = f"race_results:{int(year)}:{int(round_number)}:{session_type}"
                TaskManager.enqueue_if_needed(
                    sub_key,
                    populate_race_results,
                    int(year),
                    int(round_number),
                    session_type,
                )
            elif dtype == "session_data":
                sub_key = f"session_data:{int(year)}:{int(round_number)}:R"
                TaskManager.enqueue_if_needed(
                    sub_key,
                    populate_session_data,
                    int(year),
                    int(round_number),
                    "R",
                )

        TaskManager.mark_complete(task_key)
        logger.info(
            "event=celery_success task=seed_historical_round task_key=%s year=%s round=%s",
            task_key, year, round_number,
        )
    except Exception as exc:
        TaskManager.mark_failed(task_key, exc)
        logger.exception(
            "event=celery_failed task=seed_historical_round task_key=%s year=%s round=%s",
            task_key, year, round_number,
        )
        raise


@shared_task(bind=True, max_retries=0, queue="tier2_fast")
def prefetch_race_weekend(self, task_key: str, year: int, round_number: int):
    """
    Prefetch core data for a newly-completed race weekend.

    Loads race results, qualifying, and race session data (weather, incidents,
    pit stops).  Does NOT prefetch telemetry, positions, or DRS — those are
    expensive and should only be loaded on demand.

    Task key: prefetch:{year}:{round}
    Phase 6: Fired by check_for_completed_sessions beat task.
    """
    logger.info(
        "event=celery_start task=prefetch_race_weekend task_key=%s year=%s round=%s",
        task_key, year, round_number,
    )
    TaskManager.mark_running(task_key)

    try:
        # Race results + qualifying results
        for session_type, prefix in [("R", "race_results"), ("Q", "qualifying")]:
            sub_key = f"{prefix}:{int(year)}:{int(round_number)}"
            TaskManager.enqueue_if_needed(
                sub_key,
                populate_race_results,
                int(year),
                int(round_number),
                session_type,
            )

        # Session-level data (weather, incidents, pit stops) for the race session
        sd_key = f"session_data:{int(year)}:{int(round_number)}:R"
        TaskManager.enqueue_if_needed(
            sd_key,
            populate_session_data,
            int(year),
            int(round_number),
            "R",
        )

        TaskManager.mark_complete(task_key)
        logger.info(
            "event=celery_success task=prefetch_race_weekend task_key=%s year=%s round=%s",
            task_key, year, round_number,
        )
    except Exception as exc:
        TaskManager.mark_failed(task_key, exc)
        logger.exception(
            "event=celery_failed task=prefetch_race_weekend task_key=%s year=%s round=%s",
            task_key, year, round_number,
        )
        raise


@shared_task(bind=False, max_retries=0, queue="tier1_instant")
def check_for_completed_sessions():
    """
    Beat task: detect race sessions that ended in the last 15 minutes and fire
    prefetch_race_weekend for each.

    Queries SeasonSchedule for the current year and checks each round's
    session5_date_utc (the main race session).  A 16-minute look-back window
    ensures overlap with the previous run so no session is missed on edge-case
    timing.

    Runs every 15 minutes via app.conf.beat_schedule in celery.py.
    Phase 6.
    """
    from datetime import datetime, timedelta
    from django.utils.timezone import now as django_now
    from api.models import SeasonSchedule

    logger.info("event=celery_start task=check_for_completed_sessions")

    now = django_now()
    window_start = now - timedelta(minutes=16)

    try:
        current_year = now.year
        schedule_record = SeasonSchedule.objects.filter(year=current_year).first()

        if not schedule_record:
            logger.info("event=no_schedule task=check_for_completed_sessions year=%s", current_year)
            return

        races = schedule_record.payload.get("races", [])
        fired = 0

        for race in races:
            session5_date = race.get("session5_date_utc")
            if not session5_date:
                continue

            try:
                session_dt = datetime.fromisoformat(session5_date.replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                continue

            if window_start <= session_dt <= now:
                round_number = race.get("round")
                if not round_number:
                    continue

                task_key = f"prefetch:{int(current_year)}:{int(round_number)}"
                logger.info(
                    "event=session_completed year=%s round=%s session_dt=%s",
                    current_year, round_number, session5_date,
                )
                TaskManager.enqueue_if_needed(
                    task_key,
                    prefetch_race_weekend,
                    int(current_year),
                    int(round_number),
                )
                fired += 1

        logger.info(
            "event=celery_success task=check_for_completed_sessions fired=%d year=%s",
            fired, current_year,
        )
    except Exception as exc:
        logger.exception("event=celery_failed task=check_for_completed_sessions error=%s", exc)
        raise


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
    logger.info("event=celery_start task=sync_drivers_task task_key=%s year=%s", task_key, year)
    TaskManager.mark_running(task_key)

    try:
        from api.drivers.services.sync_service import DriverSyncService
        service = DriverSyncService()
        result = service.sync_season_drivers(int(year))
        
        TaskManager.mark_complete(task_key)
        logger.info(
            "event=celery_success task=sync_drivers_task task_key=%s year=%s synced=%d errors=%d",
            task_key, year, result.get("synced", 0), result.get("errors", 0),
        )
    except Exception as exc:
        TaskManager.mark_failed(task_key, exc)
        logger.exception("event=celery_failed task=sync_drivers_task task_key=%s year=%s", task_key, year)
        raise


@shared_task(bind=True, max_retries=0, queue="tier4_telemetry")
def sync_all_drivers_task(self, task_key: str, start: int = 1950, end: int = 2025):
    """
    Sync drivers for all seasons (1950–2025) asynchronously via Celery.
    
    Uses DriverSyncService to fetch drivers from Jolpica with 0.3s rate limiting
    and upsert to F1Driver model. Run this once on setup to populate the DB.
    Task key: sync_drivers_all
    """
    logger.info(
        "event=celery_start task=sync_all_drivers_task task_key=%s start=%s end=%s",
        task_key, start, end,
    )
    TaskManager.mark_running(task_key)

    try:
        from api.drivers.services.sync_service import DriverSyncService
        service = DriverSyncService()
        result = service.sync_all_seasons(start=int(start), end=int(end))
        
        TaskManager.mark_complete(task_key)
        logger.info(
            "event=celery_success task=sync_all_drivers_task task_key=%s total_synced=%d total_errors=%d",
            task_key, result.get("total_synced", 0), result.get("total_errors", 0),
        )
    except Exception as exc:
        TaskManager.mark_failed(task_key, exc)
        logger.exception("event=celery_failed task=sync_all_drivers_task task_key=%s", task_key)
        raise


# =========================================================================
# Registration & Email Tasks — API key lifecycle management
# =========================================================================


@shared_task(bind=True, max_retries=3, queue="tier6_notifications")
def send_verification_email(self, task_key: str, api_key_id: str, email: str, verification_link: str):
    """
    Send email verification link for new API key registration.
    Task key: email_verification:{api_key_id}
    """
    logger.info("event=celery_start task=send_verification_email task_key=%s email=%s", task_key, email)
    
    try:
        from django.core.mail import send_mail
        from django.conf import settings
        
        subject = "Verify your F1 API Account"
        message = f"""
Welcome to the F1 API!

Click the link below to verify your email and activate your API key:
{verification_link}

If you didn't create this account, you can ignore this email.

Best regards,
F1 API Team
"""
        send_mail(
            subject,
            message,
            settings.DEFAULT_FROM_EMAIL or 'noreply@f1api.example.com',
            [email],
            fail_silently=False,
        )
        
        logger.info("event=email_sent task=send_verification_email email=%s", email)
    except Exception as exc:
        logger.error("event=email_failed task=send_verification_email email=%s error=%s", email, str(exc))
        raise


@shared_task(bind=True, max_retries=3, queue="tier6_notifications")
def send_welcome_email(self, task_key: str, api_key_id: str, email: str, tier: str):
    """
    Send welcome email after email verification.
    Task key: email_welcome:{api_key_id}
    """
    logger.info("event=celery_start task=send_welcome_email task_key=%s email=%s tier=%s", task_key, email, tier)
    
    try:
        from django.core.mail import send_mail
        from django.conf import settings
        
        tier_limits = {
            'free': '100 requests/min',
            'standard': '500 requests/min',
            'premium': '2000 requests/min',
            'internal': '10000 requests/min',
        }
        limit = tier_limits.get(tier, 'Unknown')
        
        subject = f"Welcome! Your {tier.title()} API Key is Active"
        message = f"""
Your API key is now active and ready to use!

Tier: {tier.title()}
Rate Limit: {limit}

Get started:
https://docs.f1api.example.com/getting-started

Questions? Contact support@f1api.example.com

Best regards,
F1 API Team
"""
        send_mail(
            subject,
            message,
            settings.DEFAULT_FROM_EMAIL or 'noreply@f1api.example.com',
            [email],
            fail_silently=False,
        )
        
        logger.info("event=email_sent task=send_welcome_email email=%s", email)
    except Exception as exc:
        logger.error("event=email_failed task=send_welcome_email email=%s error=%s", email, str(exc))
        raise


@shared_task(bind=True, max_retries=3, queue="tier6_notifications")
def send_tier_upgrade_email(self, task_key: str, api_key_id: str, email: str, new_tier: str, old_tier: str):
    """
    Send notification email when API key tier is upgraded.
    Task key: email_tier_upgrade:{api_key_id}
    """
    logger.info("event=celery_start task=send_tier_upgrade_email task_key=%s email=%s", task_key, email)
    
    try:
        from django.core.mail import send_mail
        from django.conf import settings
        
        tier_limits = {
            'free': '100 requests/min',
            'standard': '500 requests/min',
            'premium': '2000 requests/min',
            'internal': '10000 requests/min',
        }
        new_limit = tier_limits.get(new_tier, 'Unknown')
        
        subject = f"Your API Key Upgraded to {new_tier.title()}"
        message = f"""
Great news! Your API key tier has been upgraded.

Old Tier: {old_tier.title()}
New Tier: {new_tier.title()}
New Rate Limit: {new_limit}

Your changes are effective immediately.

Questions? Contact support@f1api.example.com

Best regards,
F1 API Team
"""
        send_mail(
            subject,
            message,
            settings.DEFAULT_FROM_EMAIL or 'noreply@f1api.example.com',
            [email],
            fail_silently=False,
        )
        
        logger.info("event=email_sent task=send_tier_upgrade_email email=%s", email)
    except Exception as exc:
        logger.error("event=email_failed task=send_tier_upgrade_email email=%s error=%s", email, str(exc))
        raise


@shared_task(bind=True, max_retries=3, queue="tier6_notifications")
def send_rate_limit_warning_email(self, task_key: str, api_key_id: str, email: str, usage_percent: int):
    """
    Send warning email when rate limit threshold is approaching.
    Task key: email_rate_limit_warning:{api_key_id}
    """
    logger.info("event=celery_start task=send_rate_limit_warning_email task_key=%s email=%s usage=%d%%", task_key, email, usage_percent)
    
    try:
        from django.core.mail import send_mail
        from django.conf import settings
        
        subject = f"Rate Limit Warning ({usage_percent}% Used)"
        message = f"""
You're using {usage_percent}% of your rate limit.

If you need more capacity, consider upgrading to a higher tier:
https://dashboard.f1api.example.com/upgrade

Current usage: {usage_percent}%
Reset time: Next hour

Questions? Contact support@f1api.example.com

Best regards,
F1 API Team
"""
        send_mail(
            subject,
            message,
            settings.DEFAULT_FROM_EMAIL or 'noreply@f1api.example.com',
            [email],
            fail_silently=False,
        )
        
        logger.info("event=email_sent task=send_rate_limit_warning_email email=%s", email)
    except Exception as exc:
        logger.error("event=email_failed task=send_rate_limit_warning_email email=%s error=%s", email, str(exc))
        raise


@shared_task(bind=True, max_retries=3, queue="tier6_notifications")
def send_key_revocation_email(self, task_key: str, api_key_id: str, email: str):
    """
    Send confirmation email after API key is revoked.
    Task key: email_revocation:{api_key_id}
    """
    logger.info("event=celery_start task=send_key_revocation_email task_key=%s email=%s", task_key, email)
    
    try:
        from django.core.mail import send_mail
        from django.conf import settings
        
        subject = "API Key Revoked"
        message = f"""
Your API key has been revoked and is no longer active.

If this was unexpected or you'd like to re-activate, please contact:
support@f1api.example.com

Best regards,
F1 API Team
"""
        send_mail(
            subject,
            message,
            settings.DEFAULT_FROM_EMAIL or 'noreply@f1api.example.com',
            [email],
            fail_silently=False,
        )
        
        logger.info("event=email_sent task=send_key_revocation_email email=%s", email)
    except Exception as exc:
        logger.error("event=email_failed task=send_key_revocation_email email=%s error=%s", email, str(exc))
        raise


@shared_task(bind=True, max_retries=3, queue="tier6_notifications")
def send_monthly_usage_report(self, task_key: str, api_key_id: str, email: str, requests_count: int, tier: str):
    """
    Send monthly usage report for API key.
    Task key: email_monthly_report:{api_key_id}
    """
    logger.info("event=celery_start task=send_monthly_usage_report task_key=%s email=%s requests=%d", task_key, email, requests_count)
    
    try:
        from django.core.mail import send_mail
        from django.conf import settings
        
        subject = "Your F1 API Monthly Usage Report"
        message = f"""
Here's your monthly API usage summary:

Tier: {tier.title()}
Requests This Month: {requests_count}
Monthly Reset: 1st of month

View detailed analytics:
https://dashboard.f1api.example.com/analytics

Questions? Contact support@f1api.example.com

Best regards,
F1 API Team
"""
        send_mail(
            subject,
            message,
            settings.DEFAULT_FROM_EMAIL or 'noreply@f1api.example.com',
            [email],
            fail_silently=False,
        )
        
        logger.info("event=email_sent task=send_monthly_usage_report email=%s", email)
    except Exception as exc:
        logger.error("event=email_failed task=send_monthly_usage_report email=%s error=%s", email, str(exc))
        raise


# =========================================================================
# Pagination Tasks — tier5_pagination queue (Module J)
# =========================================================================

@shared_task(bind=True, max_retries=1, queue="tier5_pagination")
def paginate_laps(self, task_key: str, year: int, round_number: int, session: str, page_size: int = 50):
    """
    Paginate lap data for a session.
    
    Retrieves full lap dataset and stores as paginated pages in cache.
    Task key: paginate_laps:{year}:{round}:{session}
    """
    logger.info(
        "event=celery_start task=paginate_laps task_key=%s year=%s round=%s session=%s page_size=%d",
        task_key, year, round_number, session, page_size,
    )
    TaskManager.mark_running(task_key)
    
    try:
        from api.services.pagination_cache import set_paginated_data
        from api.services.cache import ttl_for
        
        # Retrieve full lap dataset from repository/cache
        # This is a placeholder — actual retrieval would call the laps service
        lap_data = []  # TODO: Call api.drivers.services.laps or similar to get full data
        
        ttl = ttl_for("laps", year)
        set_paginated_data(year, round_number, session, "laps", lap_data, page_size, ttl)
        
        TaskManager.mark_complete(task_key)
        logger.info(
            "event=celery_success task=paginate_laps task_key=%s year=%s round=%s session=%s pages=%d",
            task_key, year, round_number, session,
            (len(lap_data) + page_size - 1) // page_size if lap_data else 0,
        )
    except Exception as exc:
        TaskManager.mark_failed(task_key, exc)
        logger.exception("event=celery_failed task=paginate_laps task_key=%s", task_key)
        raise


@shared_task(bind=True, max_retries=1, queue="tier5_pagination")
def paginate_positions(self, task_key: str, year: int, round_number: int, session: str, page_size: int = 50):
    """
    Paginate position data for a session.
    
    Retrieves full position dataset and stores as paginated pages in cache.
    Task key: paginate_positions:{year}:{round}:{session}
    """
    logger.info(
        "event=celery_start task=paginate_positions task_key=%s year=%s round=%s session=%s page_size=%d",
        task_key, year, round_number, session, page_size,
    )
    TaskManager.mark_running(task_key)
    
    try:
        from api.services.pagination_cache import set_paginated_data
        from api.services.cache import ttl_for
        
        # Retrieve full position dataset from repository/cache
        position_data = []  # TODO: Call api.drivers.services.positions or similar
        
        ttl = ttl_for("positions", year)
        set_paginated_data(year, round_number, session, "positions", position_data, page_size, ttl)
        
        TaskManager.mark_complete(task_key)
        logger.info(
            "event=celery_success task=paginate_positions task_key=%s year=%s round=%s session=%s pages=%d",
            task_key, year, round_number, session,
            (len(position_data) + page_size - 1) // page_size if position_data else 0,
        )
    except Exception as exc:
        TaskManager.mark_failed(task_key, exc)
        logger.exception("event=celery_failed task=paginate_positions task_key=%s", task_key)
        raise


@shared_task(bind=True, max_retries=1, queue="tier5_pagination")
def paginate_telemetry(self, task_key: str, year: int, round_number: int, session: str, page_size: int = 50):
    """
    Paginate telemetry data for a session.
    
    Retrieves full telemetry dataset and stores as paginated pages in cache.
    Task key: paginate_telemetry:{year}:{round}:{session}
    """
    logger.info(
        "event=celery_start task=paginate_telemetry task_key=%s year=%s round=%s session=%s page_size=%d",
        task_key, year, round_number, session, page_size,
    )
    TaskManager.mark_running(task_key)
    
    try:
        from api.services.pagination_cache import set_paginated_data
        from api.services.cache import ttl_for
        
        # Retrieve full telemetry dataset from repository/cache
        telemetry_data = []  # TODO: Call api.services.telemetry or similar
        
        ttl = ttl_for("telemetry", year)
        set_paginated_data(year, round_number, session, "telemetry", telemetry_data, page_size, ttl)
        
        TaskManager.mark_complete(task_key)
        logger.info(
            "event=celery_success task=paginate_telemetry task_key=%s year=%s round=%s session=%s pages=%d",
            task_key, year, round_number, session,
            (len(telemetry_data) + page_size - 1) // page_size if telemetry_data else 0,
        )
    except Exception as exc:
        TaskManager.mark_failed(task_key, exc)
        logger.exception("event=celery_failed task=paginate_telemetry task_key=%s", task_key)
        raise


@shared_task(bind=True, max_retries=0, queue="tier3_medium")
def sync_champions_task(self, task_key: str, year: int = None):
    """
    Sync F1 champions from Jolpica into F1Champion table.
    Task key: sync_champions or sync_champions:{year}
    """
    logger.info("event=celery_start task=sync_champions_task task_key=%s year=%s", task_key, year)
    TaskManager.mark_running(task_key)

    try:
        from api.drivers.services.champions_sync_service import ChampionsSyncService
        service = ChampionsSyncService()

        if year:
            result = service.sync_year_champion(int(year))
        else:
            result = service.sync_all_champions()

        TaskManager.mark_complete(task_key)
        logger.info("event=celery_success task=sync_champions_task task_key=%s result=%s", task_key, result)
    except Exception as exc:
        TaskManager.mark_failed(task_key, exc)
        logger.exception("event=celery_failed task=sync_champions_task task_key=%s", task_key)
        raise


# =========================================================================
# Notification Task Aliases/Wrappers — Module K
# Maps CELERY_TASK_ROUTES names to per-email-type implementations
# =========================================================================

@shared_task(bind=True, max_retries=3, queue="tier6_notifications")
def send_api_key_email(self, task_key: str, api_key_id: str, email: str, verification_link: str):
    """
    Unified API key email task (routes to send_verification_email + send_welcome_email).
    
    This wrapper allows CELERY_TASK_ROUTES to reference send_api_key_email
    while delegating to specific per-email-type tasks.
    
    Task key: email_api_key:{api_key_id}
    """
    logger.info("event=celery_start task=send_api_key_email task_key=%s email=%s", task_key, email)
    
    try:
        # Call the underlying per-email-type task
        send_verification_email.apply_async(
            args=(task_key, api_key_id, email, verification_link),
            queue="tier6_notifications",
        )
        logger.info("event=celery_success task=send_api_key_email task_key=%s", task_key)
    except Exception as exc:
        logger.exception("event=celery_failed task=send_api_key_email task_key=%s error=%s", task_key, exc)
        raise


@shared_task(bind=True, max_retries=3, queue="tier6_notifications")
def send_rate_limit_warning(self, task_key: str, api_key_id: str, email: str, usage_percent: int):
    """
    Unified rate limit warning task (routes to send_rate_limit_warning_email).
    
    This wrapper allows CELERY_TASK_ROUTES to reference send_rate_limit_warning
    while delegating to the per-email-type implementation.
    
    Task key: email_rate_limit:{api_key_id}
    """
    logger.info("event=celery_start task=send_rate_limit_warning task_key=%s email=%s usage=%d%%", task_key, email, usage_percent)
    
    try:
        # Call the underlying per-email-type task
        send_rate_limit_warning_email.apply_async(
            args=(task_key, api_key_id, email, usage_percent),
            queue="tier6_notifications",
        )
        logger.info("event=celery_success task=send_rate_limit_warning task_key=%s", task_key)
    except Exception as exc:
        logger.exception("event=celery_failed task=send_rate_limit_warning task_key=%s error=%s", task_key, exc)
        raise


@shared_task(bind=True, max_retries=3, queue="tier6_notifications")
def send_usage_summary(self, task_key: str, api_key_id: str, email: str, requests_count: int, tier: str):
    """
    Unified usage summary task (routes to send_monthly_usage_report).
    
    This wrapper allows CELERY_TASK_ROUTES to reference send_usage_summary
    while delegating to the per-email-type implementation.
    
    Task key: email_usage_summary:{api_key_id}
    """
    logger.info("event=celery_start task=send_usage_summary task_key=%s email=%s requests=%d", task_key, email, requests_count)
    
    try:
        # Call the underlying per-email-type task
        send_monthly_usage_report.apply_async(
            args=(task_key, api_key_id, email, requests_count, tier),
            queue="tier6_notifications",
        )
        logger.info("event=celery_success task=send_usage_summary task_key=%s", task_key)
    except Exception as exc:
        logger.exception("event=celery_failed task=send_usage_summary task_key=%s error=%s", task_key, exc)
        raise


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
