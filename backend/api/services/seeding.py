"""
Seeding service — Phase 6: Historical data population and schedule pre-caching.

Coordinates the dispatch of backfill tasks to seed 5 years of historical data.
Pre-populates FastF1's schedule cache to eliminate GitHub dependency.
"""
from __future__ import annotations

import logging
import time
from typing import List, Tuple
from datetime import datetime

import fastf1
from celery import group, chain
from celery.result import AsyncResult
from django.utils.timezone import now as django_now

from api.models import TaskRecord, SeasonSchedule
from api.queue.manager import TaskManager
from api.tasks import (
    populate_standings,
    populate_constructor_standings,
    populate_driver_season,
    populate_race_results,
    populate_session_data,
    populate_weather,
    populate_incidents,
    populate_pit_stops,
)

logger = logging.getLogger(__name__)


def prepopulate_fastf1_schedule_cache(years: List[int]) -> bool:
    """
    Pre-populate FastF1's schedule cache to avoid GitHub dependency.
    
    FastF1 normally fetches the F1 schedule from GitHub on every session
    instantiation, which can timeout 10–15s. Pre-loading eliminates this.
    
    Returns True if successful, False on error.
    """
    try:
        for year in years:
            logger.info("[SeedService] Pre-caching FastF1 schedule year=%s", year)
            schedule = fastf1.get_event_schedule(year)
            
            if schedule.empty:
                logger.warning("[SeedService] Empty schedule year=%s", year)
                continue
            
            logger.info("[SeedService] Cached %d events year=%s", len(schedule), year)
        
        return True
    except Exception as exc:
        logger.warning("[SeedService] Schedule pre-cache failed: %s", exc)
        return False


def dispatch_season_seed_batch(
    years: List[int],
    max_tasks: int = 0,
) -> List[str]:
    """
    Dispatch seeding tasks for multiple years to the backfill queue.
    
    Seeding order: reverse chronological (most recent first) so interruption
    leaves most-requested data in place.
    
    Returns list of task IDs dispatched.
    """
    logger.info("[SeedService] Starting batch seed for years: %s", years)
    
    # Pre-populate FastF1 schedule cache
    prepopulate_fastf1_schedule_cache(years)
    
    task_ids = []
    task_count = 0
    
    for year in years:
        if max_tasks > 0 and task_count >= max_tasks:
            logger.info("[SeedService] Reached max_tasks limit (%d)", max_tasks)
            break
        
        # Dispatch seed tasks for each year
        year_tasks = _dispatch_year_seed(year)
        task_ids.extend(year_tasks)
        task_count += len(year_tasks)
        
        logger.info(
            "[SeedService] Dispatched %d tasks for year %d (total: %d)",
            len(year_tasks), year, task_count,
        )
    
    return task_ids


def _dispatch_year_seed(year: int) -> List[str]:
    """Dispatch seeding tasks for a single year."""
    task_ids = []
    
    try:
        # Get all races for this year
        schedules = SeasonSchedule.objects.filter(year=year).order_by('round_number')
        
        if not schedules.exists():
            logger.warning("[SeedService] No races found year=%s", year)
            return task_ids
        
        # Seed tasks per data type (independent, can run in parallel within backfill queue)
        seed_tasks = [
            # Tier 1: Standings (fast, pure DB reads)
            ("standings", year, populate_standings, (year,)),
            ("constructor_standings", year, populate_constructor_standings, (year,)),
            ("driver_season", year, populate_driver_season, (year,)),
            
            # Tier 2: Results (FastF1 loads, ~5s each)
            ("race_results", year, populate_race_results, (year,)),
            ("session_data", year, populate_session_data, (year,)),
        ]
        
        for task_type, task_year, task_fn, task_args in seed_tasks:
            task_key = f"seed:{task_type}:{task_year}"
            
            # Use TaskManager to respect queue routing + deduplication
            success = TaskManager.enqueue_if_needed(
                task_key=task_key,
                task_fn=task_fn,
                *task_args,
            )
            
            # Get the task ID from TaskRecord
            if success:
                record = TaskRecord.objects.filter(task_key=task_key).first()
                if record:
                    task_ids.append(record.celery_task_id)
                    logger.info(
                        "[SeedService] Queued seed task task_type=%s year=%s task_id=%s",
                        task_type, task_year, record.celery_task_id,
                    )
        
        logger.info("[SeedService] Dispatched %d seed tasks for year %d", len(task_ids), year)
    
    except Exception as exc:
        logger.error("[SeedService] Year seed dispatch failed year=%s error=%s", year, exc)
    
    return task_ids


def wait_for_seed_batch(
    task_ids: List[str],
    timeout_seconds: int = 3600,
    poll_interval: int = 5,
) -> Tuple[int, int]:
    """
    Wait for a batch of seed tasks to complete.
    
    Returns: (completed_count, failed_count)
    """
    if not task_ids:
        return 0, 0
    
    logger.info(
        "[SeedService] Waiting for seed batch (%d tasks, timeout=%ds)",
        len(task_ids), timeout_seconds,
    )
    
    start_time = time.time()
    completed = 0
    failed = 0
    pending = set(task_ids)
    
    while pending and (time.time() - start_time) < timeout_seconds:
        still_pending = []
        
        for task_id in pending:
            try:
                result = AsyncResult(task_id)
                
                if result.state == "SUCCESS":
                    completed += 1
                    logger.debug("[SeedService] Task completed task_id=%s", task_id)
                elif result.state == "FAILURE":
                    failed += 1
                    logger.warning(
                        "[SeedService] Task failed task_id=%s error=%s",
                        task_id, result.result,
                    )
                elif result.state in ("PENDING", "STARTED", "RETRY"):
                    still_pending.append(task_id)
                else:
                    # Unknown state; assume still running
                    still_pending.append(task_id)
            
            except Exception as exc:
                logger.warning("[SeedService] Status check failed task_id=%s error=%s", task_id, exc)
                still_pending.append(task_id)
        
        pending = still_pending
        
        if pending:
            elapsed = int(time.time() - start_time)
            logger.info(
                "[SeedService] Batch progress: %d completed, %d failed, %d pending (elapsed: %ds)",
                completed, failed, len(pending), elapsed,
            )
            time.sleep(poll_interval)
    
    if pending:
        logger.warning(
            "[SeedService] Seed batch timeout: %d tasks still pending after %ds",
            len(pending), timeout_seconds,
        )
    
    logger.info(
        "[SeedService] Seed batch complete: %d completed, %d failed",
        completed, failed,
    )
    
    return completed, failed


def prefetch_race_completion(year: int, round_number: int) -> List[str]:
    """
    Prefetch highest-traffic endpoints for a completed race.
    
    Phase 6 Problem 21: Proactive warming after race completion to handle
    post-race traffic spikes.
    
    Prefetch: Results, Qualifying, Incidents, Weather (~80KB total)
    
    Returns list of task IDs dispatched.
    """
    logger.info("[SeedService] Prefetching race completion year=%s round=%s", year, round_number)
    
    prefetch_tasks = [
        ("race_results", populate_race_results, (year, round_number)),
        ("session_data", populate_session_data, (year, round_number)),
        ("weather", populate_weather, (year, round_number)),
        ("incidents", populate_incidents, (year, round_number)),
    ]
    
    task_ids = []
    
    for task_type, task_fn, task_args in prefetch_tasks:
        task_key = f"prefetch:{task_type}:{year}:{round_number}"
        
        success = TaskManager.enqueue_if_needed(
            task_key=task_key,
            task_fn=task_fn,
            *task_args,
        )
        
        if success:
            record = TaskRecord.objects.filter(task_key=task_key).first()
            if record:
                task_ids.append(record.celery_task_id)
                logger.info(
                    "[SeedService] Prefetch queued task_type=%s year=%s round=%s",
                    task_type, year, round_number,
                )
    
    logger.info("[SeedService] Prefetch batch dispatched (%d tasks)", len(task_ids))
    return task_ids


def detect_race_completion(year: int, round_number: int) -> bool:
    """
    Detect if a race session has completed.
    
    Returns True if the session is complete, False otherwise.
    """
    try:
        # Check schedule: is the session date in the past?
        schedule = SeasonSchedule.objects.filter(
            year=year,
            round_number=round_number,
        ).first()
        
        if not schedule:
            return False
        
        # Compare session end time to now
        session_end = getattr(schedule, 'race_end_datetime', None) or getattr(schedule, 'race_datetime', None)
        
        if session_end and session_end < django_now():
            return True
        
        return False
    
    except Exception as exc:
        logger.warning(
            "[SeedService] Race completion detection failed year=%s round=%s error=%s",
            year, round_number, exc,
        )
        return False
