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


@shared_task(bind=True, max_retries=0)
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


@shared_task(bind=True, max_retries=0)
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


@shared_task(bind=True, max_retries=0)
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


@shared_task(bind=True, max_retries=0)
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


@shared_task(bind=True, max_retries=0)
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


@shared_task(bind=True, max_retries=0)
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


@shared_task(bind=True, max_retries=0)
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


@shared_task(bind=True, max_retries=0)
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
