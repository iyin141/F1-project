"""
Celery task definitions for F1 data population.

Pattern for each task:
  1. @shared_task(bind=True, max_retries=0)
  2. Accept task_key as first argument
  3. mark_running(task_key)
  4. Execute the management command (or service function)
  5. mark_complete(task_key) — ONLY after DB write confirmed
  6. On exception: mark_failed(task_key, exc)

Task keys are index-scoped (not unique-constraint-scoped):
  - standings: year only
  - race/qualifying/practice/session: year, round, session
  - telemetry: year, round, session (driver/lap NOT in key — not indexed)
"""
from __future__ import annotations

import logging
from django.core.management import call_command

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
        call_command("populate_standings", year=year)
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
    Task key: race:{year}:{round}:{session}
    """
    logger.info(
        "event=celery_start task=populate_race_results task_key=%s year=%s round=%s session=%s",
        task_key, year, round_number, session_type
    )
    TaskManager.mark_running(task_key)
    
    try:
        call_command("populate_race", year=year, round_number=round_number, session=session_type)
        TaskManager.mark_complete(task_key)
        logger.info(
            "event=celery_success task=populate_race_results task_key=%s year=%s round=%s session=%s",
            task_key, year, round_number, session_type
        )
    except Exception as exc:
        TaskManager.mark_failed(task_key, exc)
        logger.exception(
            "event=celery_failed task=populate_race_results task_key=%s year=%s round=%s session=%s",
            task_key, year, round_number, session_type
        )
        raise


@shared_task(bind=True, max_retries=0)
def populate_session_data(self, task_key: str, year: int, round_number: int, session_type: str):
    """
    Populate unified SessionData (weather, pit_stops, incidents, positions, drs, track_status).
    Task key: session:{year}:{round}:{session}
    """
    logger.info(
        "event=celery_start task=populate_session_data task_key=%s year=%s round=%s session=%s",
        task_key, year, round_number, session_type
    )
    TaskManager.mark_running(task_key)
    
    try:
        call_command("populate_session", year=year, round_number=round_number, session=session_type)
        TaskManager.mark_complete(task_key)
        logger.info(
            "event=celery_success task=populate_session_data task_key=%s year=%s round=%s session=%s",
            task_key, year, round_number, session_type
        )
    except Exception as exc:
        TaskManager.mark_failed(task_key, exc)
        logger.exception(
            "event=celery_failed task=populate_session_data task_key=%s year=%s round=%s session=%s",
            task_key, year, round_number, session_type
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
    lap_number: int,
):
    """
    Populate DriverTelemetry for a single driver/lap.
    Task key: telemetry:{year}:{round}:{session}
      (driver_code and lap_number are NOT in the key — they're not indexed)
    """
    logger.info(
        "event=celery_start task=populate_telemetry task_key=%s year=%s round=%s session=%s driver=%s lap=%s",
        task_key, year, round_number, session_type, driver_code, lap_number
    )
    TaskManager.mark_running(task_key)
    
    try:
        call_command(
            "populate_telemetry",
            year=year,
            round_number=round_number,
            session=session_type,
            driver=driver_code,
            lap=lap_number
        )
        TaskManager.mark_complete(task_key)
        logger.info(
            "event=celery_success task=populate_telemetry task_key=%s year=%s round=%s session=%s driver=%s lap=%s",
            task_key, year, round_number, session_type, driver_code, lap_number
        )
    except Exception as exc:
        TaskManager.mark_failed(task_key, exc)
        logger.exception(
            "event=celery_failed task=populate_telemetry task_key=%s year=%s round=%s session=%s driver=%s lap=%s",
            task_key, year, round_number, session_type, driver_code, lap_number
        )
        raise
