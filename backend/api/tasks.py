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
