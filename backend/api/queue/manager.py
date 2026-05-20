"""
TaskManager — Distributed task queue lifecycle management.

Stateless service layer for enqueueing, tracking, and managing the lifecycle
of Celery tasks. All state lives in TaskRecord model; TaskManager is just the
orchestrator.

Lifecycle:
  1. enqueue_if_needed(task_key, task_fn, ...) — entry point
     - Check TaskRecord status by task_key
     - pending/running/complete → skip (idempotent)
     - failed → log error, delete record, re-enqueue
     - none → dispatch
  2. _dispatch(task_key, task_fn, ...) — internal
     - Create TaskRecord(status=pending) FIRST — establishes distributed lock
     - Call task_fn.delay(task_key, ...) — queue the task
     - Save celery_task_id in TaskRecord
  3. Worker-side (in @shared_task):
     - Call mark_running(task_key)
     - Execute business logic (management command)
     - Call mark_complete(task_key) ONLY after DB write confirmed
     - On exception: mark_failed(task_key, exc)
"""
from __future__ import annotations

import logging
from typing import Callable, Any
from traceback import format_exc

from django.utils.timezone import now as django_now
from django.core.cache import cache

from api.models import TaskRecord

logger = logging.getLogger(__name__)


STALE_MINUTES = 10

# Phase 3: Queue tier mapping with deduplication TTL per tier (seconds)
TASK_TIER_MAP = {
    "populate_standings": ("tier1_instant", 30),
    "populate_constructor_standings": ("tier1_instant", 30),
    "populate_driver_career": ("tier1_instant", 30),
    "populate_driver_season": ("tier1_instant", 30),
    "populate_schedule": ("tier1_instant", 30),
    "populate_race_results": ("tier2_fast", 60),
    "populate_session_data": ("tier2_fast", 60),
    "populate_weather": ("tier2_fast", 60),
    "populate_incidents": ("tier2_fast", 60),
    "populate_pit_stops": ("tier2_fast", 60),
    "populate_laps": ("tier3_medium", 90),
    "populate_pace": ("tier3_medium", 90),
    "populate_stints": ("tier3_medium", 90),
    "populate_sectors": ("tier3_medium", 90),
    "populate_positions": ("tier3_medium", 90),
    "populate_drs": ("tier3_medium", 90),
    "populate_tyre_strategy": ("tier3_medium", 90),
    "populate_telemetry": ("tier4_telemetry", 180),
    "populate_telemetry_overlay": ("tier4_telemetry", 180),
    "populate_telemetry_summary": ("tier4_telemetry", 180),
    "seed_historical_round": ("backfill", 120),
}


class TaskManager:
    """
    Stateless service for Celery task lifecycle — dispatch, tracking, and state transitions.
    All methods are class methods (no instance state).
    
    Phase 3 addition: Redis SETNX deduplication locks per task tier.
    """

    @staticmethod
    def _get_tier_and_ttl(task_fn_name: str) -> tuple[str, int]:
        """
        Determine queue tier and deduplication lock TTL (seconds) for a task.
        
        Returns: (queue_tier, ttl_seconds)
        """
        # Extract task function name from the full path (e.g., "api.tasks.populate_standings" → "populate_standings")
        short_name = task_fn_name.split(".")[-1] if "." in task_fn_name else task_fn_name
        return TASK_TIER_MAP.get(short_name, ("tier3_medium", 90))  # Default to tier3

    @staticmethod
    def _get_redis_lock_key(task_key: str) -> str:
        """Format the Redis lock key for a given task_key."""
        return f"task_lock:{task_key}"

    @classmethod
    def _acquire_redis_lock(cls, task_key: str, task_fn_name: str) -> bool:
        """
        Acquire a Redis deduplication lock via SETNX.
        
        Returns True if lock acquired, False if already locked (another worker is processing).
        """
        _, ttl = cls._get_tier_and_ttl(task_fn_name)
        lock_key = cls._get_redis_lock_key(task_key)
        
        # SETNX: set only if key does not exist (atomic)
        acquired = cache.set(lock_key, "1", timeout=ttl, nx=True)
        if acquired:
            logger.info("[TaskManager] Redis lock acquired task_key=%s tier_ttl=%ss", task_key, ttl)
        else:
            logger.info("[TaskManager] Redis lock already held task_key=%s", task_key)
        return acquired

    @classmethod
    def _release_redis_lock(cls, task_key: str) -> bool:
        """Release a Redis deduplication lock."""
        lock_key = cls._get_redis_lock_key(task_key)
        cache.delete(lock_key)
        logger.info("[TaskManager] Redis lock released task_key=%s", task_key)
        return True

    @classmethod
    def enqueue_if_needed(
        cls,
        task_key: str,
        task_fn: Callable,
        *args,
        **kwargs
    ) -> bool:
        """
        Enqueue *task_fn* with *args/*kwargs* if no active record for *task_key* exists.
        
        Returns True if a task was enqueued, False if skipped.
        
        Lifecycle of TaskRecord.status:
          - pending / running and fresh → skip (idempotent)
          - pending / running and stale (>10 min) → treat as crashed, delete + re-enqueue
          - complete → skip
          - failed → log error, delete, re-enqueue
          - none → dispatch
        """
        try:
            record = TaskRecord.objects.filter(task_key=task_key).first()
            
            if record and record.status in ("pending", "running"):
                age = django_now() - record.created_at
                if age.total_seconds() > STALE_MINUTES * 60:
                    logger.warning(
                        "[TaskManager] Stale task detected task_key=%s status=%s age=%ss",
                        task_key, record.status, int(age.total_seconds()),
                    )
                    record.delete()
                    # fall through to dispatch below
                else:
                    logger.info(
                        "[TaskManager] Skipped duplicate task_key=%s status=%s",
                        task_key, record.status,
                    )
                    return False
            
            if record and record.status == "complete":
                logger.info(
                    "event=task_already_complete task_key=%s completed_at=%s",
                    task_key,
                    record.completed_at,
                )
                return False
            
            if record and record.status == "failed":
                logger.warning(
                    "event=task_replaced_failed task_key=%s error=%s",
                    task_key,
                    record.error_message[:200],  # First 200 chars
                )
                record.delete()
            
            # Dispatch new task
            return cls._dispatch(task_key, task_fn, *args, **kwargs)
        
        except Exception:
            logger.exception("event=enqueue_failed task_key=%s", task_key)
            return False
    
    @classmethod
    def _dispatch(
        cls,
        task_key: str,
        task_fn: Callable,
        *args,
        **kwargs
    ) -> bool:
        """
        Dispatch a task: create TaskRecord(pending) → .delay() → save celery_task_id.
        
        Phase 3 addition: Acquire Redis SETNX lock before creating TaskRecord.
        If lock acquisition fails, it means another worker/process is already handling this task;
        skip dispatch (idempotent, same as duplicate TaskRecord check).
        
        Phase 5 addition: Set initial "queued" status in Redis for polling.
        
        The lock (TaskRecord) is created BEFORE the task is queued, ensuring that
        any concurrent enqueue_if_needed call will see the pending record and skip.
        """
        # Phase 3: Attempt to acquire Redis deduplication lock (SETNX)
        task_fn_name = getattr(task_fn, "name", str(task_fn))  # Get task name (e.g., "api.tasks.populate_standings")
        if not cls._acquire_redis_lock(task_key, task_fn_name):
            # Lock already held — another worker is processing this task
            logger.info("[TaskManager] Skipped dispatch (Redis lock held) task_key=%s", task_key)
            return False

        # Create the lock record FIRST — establishes distributed lock in DB
        record = TaskRecord.objects.create(task_key=task_key, status="pending")
        logger.info("[TaskManager] task_lock_acquired task_key=%s record_id=%s", task_key, record.id)

        # Queue the task — handle Redis being unavailable silently
        try:
            async_result = task_fn.delay(task_key, *args, **kwargs)
            record.celery_task_id = async_result.id
            record.save(update_fields=["celery_task_id"])
            
            # Phase 5: Set initial "queued" status in Redis for polling
            from api.services.cache_service import set_task_status
            set_task_status(async_result.id, "queued", timeout=600)
            
            logger.info("[TaskManager] Enqueued task_key=%s celery_id=%s", task_key, async_result.id)
            return True
        except Exception as exc:
            # Release Redis lock on dispatch failure
            cls._release_redis_lock(task_key)
            record.status = "failed"
            record.error_message = f"Redis unavailable: {exc}"
            record.completed_at = django_now()
            record.save(update_fields=["status", "error_message", "completed_at"])
            logger.error("[TaskManager] Redis unavailable task_key=%s error=%s", task_key, exc)
            return False
    
    @classmethod
    def mark_running(cls, task_key: str) -> bool:
        """
        Mark task as running. Called by the worker before executing the business logic.
        
        Phase 5: Also update Redis for task status polling.
        """
        try:
            record = TaskRecord.objects.get(task_key=task_key)
            record.status = "running"
            record.save(update_fields=["status"])
            
            # Phase 5: Update task status in Redis for polling
            from api.services.cache_service import set_task_status
            set_task_status(record.celery_task_id, "loading", timeout=600)
            
            logger.info("event=task_running task_key=%s celery_id=%s", task_key, record.celery_task_id)
            return True
        except TaskRecord.DoesNotExist:
            logger.error("event=task_not_found task_key=%s", task_key)
            return False
        except Exception:
            logger.exception("event=mark_running_failed task_key=%s", task_key)
            return False
    
    @classmethod
    def mark_complete(cls, task_key: str) -> bool:
        """
        Mark task as complete. ONLY called after the DB write (data row) is confirmed.
        Sets completed_at timestamp.
        
        Phase 3 addition: Release Redis lock immediately on completion.
        Phase 5 addition: Update task status to "complete" for polling.
        """
        try:
            record = TaskRecord.objects.get(task_key=task_key)
            record.status = "complete"
            record.completed_at = django_now()
            record.save(update_fields=["status", "completed_at"])
            
            # Phase 3: Release Redis lock on completion (don't wait for TTL)
            cls._release_redis_lock(task_key)
            
            # Phase 5: Update task status in Redis for polling
            from api.services.cache_service import set_task_status
            set_task_status(record.celery_task_id, "complete", timeout=600)
            
            logger.info("event=task_complete task_key=%s completed_at=%s", task_key, record.completed_at)
            return True
        except TaskRecord.DoesNotExist:
            logger.error("event=task_not_found task_key=%s", task_key)
            return False
        except Exception:
            logger.exception("event=mark_complete_failed task_key=%s", task_key)
            return False
    
    @classmethod
    def mark_failed(cls, task_key: str, exc: Exception) -> bool:
        """
        Mark task as failed. Saves the exception traceback to error_message.
        Called by the @shared_task in its except handler.
        
        Phase 3 addition: Release Redis lock immediately on failure.
        Phase 5 addition: Update task status to "failed" for polling.
        """
        try:
            record = TaskRecord.objects.get(task_key=task_key)
            record.status = "failed"
            record.error_message = format_exc()
            record.completed_at = django_now()
            record.save(update_fields=["status", "error_message", "completed_at"])
            
            # Phase 3: Release Redis lock on failure (don't wait for TTL)
            cls._release_redis_lock(task_key)
            
            # Phase 5: Update task status in Redis for polling
            from api.services.cache_service import set_task_status
            set_task_status(record.celery_task_id, "failed", timeout=600)
            
            logger.error(
                "event=task_failed task_key=%s error=%s",
                task_key,
                record.error_message[:200],
            )
            return True
        except TaskRecord.DoesNotExist:
            logger.error("event=task_not_found task_key=%s", task_key)
            return False
        except Exception:
            logger.exception("event=mark_failed_failed task_key=%s", task_key)
            return False
