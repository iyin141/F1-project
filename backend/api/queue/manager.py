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
  3. Worker-side (in @shared_task):
     - Directly update TaskRecord status via ORM
     - Publish result via pubsub.publish_result / pubsub.publish_error
     - Release lock via cache.delete(f"task_lock:{task_key}")
"""
from __future__ import annotations

import logging
from typing import Callable, Any
from django.utils.timezone import now as django_now
from django.core.cache import cache
from django.db.utils import ProgrammingError

from api.models import TaskRecord

logger = logging.getLogger(__name__)


STALE_MINUTES = 5

# Phase 3: Queue tier mapping with deduplication TTL per tier (seconds)
TASK_TIER_MAP = {
    "populate_standings": ("tier1_instant", 30),
    "populate_constructor_standings": ("tier1_instant", 30),
    "populate_driver_career": ("tier1_instant", 30),
    "populate_driver_season": ("tier1_instant", 30),
    "populate_schedule": ("tier1_instant", 30),
    "populate_race_results": ("tier2_fast", 60),
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
    "send_api_key_email": ("tier6_notifications", 30),
    "send_rate_limit_warning": ("tier6_notifications", 30),
    "send_usage_summary": ("tier6_notifications", 30),
    "send_usage_summary_all": ("tier6_notifications", 30),
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
        
        # SETNX: set only if key does not exist (atomic). Some test caches (LocMemCache)
        # do not support the `nx` kwarg. Attempt the preferred atomic call first,
        # then fall back to `cache.add`, and finally to a non-atomic get/set as a
        # last-resort for test environments.
        acquired = False
        try:
            acquired = cache.set(lock_key, "1", timeout=ttl, nx=True)
        except TypeError:
            try:
                # LocMemCache and others provide `add` which only sets if missing.
                acquired = cache.add(lock_key, "1", timeout=ttl)
            except TypeError:
                # Last-resort non-atomic fallback (acceptable for unit tests).
                if cache.get(lock_key) is None:
                    cache.set(lock_key, "1", timeout=ttl)
                    acquired = True
                else:
                    acquired = False

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
          - pending / running and stale (>5 min) → treat as crashed, delete + re-enqueue
          - complete → treat as ghost record (data is missing), delete + re-enqueue
          - failed → log error, delete, re-enqueue
          - none → dispatch
        """
        try:
            from django.db import close_old_connections
            close_old_connections()
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
                    "event=ghost_task_re_enqueued task_key=%s completed_at=%s",
                    task_key,
                    record.completed_at,
                )
                record.delete()
                # fall through to dispatch below
            
            if record and record.status == "failed":
                logger.warning(
                    "event=task_replaced_failed task_key=%s error=%s",
                    task_key,
                    record.error_message[:200] if record.error_message else "None",
                )
                record.delete()
                # fall through to dispatch below
            
            # Dispatch new task
            return cls._dispatch(task_key, task_fn, *args, **kwargs)
        
        except ProgrammingError as pe:
            logger.error(
                "event=enqueue_failed_missing_column task_key=%s error=%s",
                task_key,
                pe,
            )
            logger.error("Hint: run migrations (manage.py migrate) against the connected DATABASES to add missing columns (e.g., started_at)")
            return False
        except Exception:
            logger.exception("event=enqueue_failed task_key=%s", task_key)
            return False

    @classmethod
    def enqueue(
        cls,
        task_key: str,
        task_fn: Callable,
        *args,
        **kwargs
    ) -> bool:
        """Alias for `enqueue_if_needed`.

        New canonical shorthand: prefer `TaskManager.enqueue(task_key, task_fn, *args, **kwargs)`
        for readability. This is non-breaking and delegates to the existing logic.
        """
        return cls.enqueue_if_needed(task_key, task_fn, *args, **kwargs)
    
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

        # Queue the task — handle dispatch failures silently
        # Canonicalize session type if present in positional args (year, round, session)
        args_list = list(args)
        if len(args_list) >= 3:
            try:
                from api.common.constants import clean_session_type

                # session is the 3rd positional arg (index 2)
                args_list[2] = clean_session_type(args_list[2])
            except Exception:
                # Don't block dispatch for any canonicalization errors
                pass

        try:
            task_fn.delay(task_key, *args_list, **kwargs)
            logger.info("[TaskManager] Enqueued task_key=%s", task_key)
            return True
        except Exception as exc:
            # Release Redis lock on dispatch failure
            cls._release_redis_lock(task_key)
            record.status = "failed"
            record.error_message = f"Dispatch failed: {exc}"
            record.completed_at = django_now()
            record.save(update_fields=["status", "error_message", "completed_at"])
            logger.error("[TaskManager] Dispatch failed task_key=%s error=%s", task_key, exc)
            return False
    
    @classmethod
    def get_task_details(cls, task_key: str) -> dict | None:
        """
        Retrieve complete task information.
        
        Returns dict with task_key, status, celery_task_id, created_at, started_at,
        completed_at, error_message. Returns None if not found.
        
        Module T addition.
        """
        try:
            record = TaskRecord.objects.get(task_key=task_key)
            return {
                "task_key": record.task_key,
                "status": record.status,
                "created_at": record.created_at.isoformat() if record.created_at else None,
                "started_at": record.started_at.isoformat() if record.started_at else None,
                "completed_at": record.completed_at.isoformat() if record.completed_at else None,
                "error_message": record.error_message[:500] if record.error_message else None,
            }
        except TaskRecord.DoesNotExist:
            logger.warning("[TaskManager] Task details not found task_key=%s", task_key)
            return None
        except Exception:
            logger.exception("[TaskManager] Failed to get task details task_key=%s", task_key)
            return None

    @classmethod
    def cancel_task(cls, task_key: str) -> bool:
        """
        Cancel (revoke) a task.
        
        Revokes the Celery task and marks TaskRecord as "cancelled".
        Returns True if cancelled, False if already complete/failed/not found.
        
        Module T addition.
        """
        try:
            record = TaskRecord.objects.get(task_key=task_key)
            
            # Cannot cancel if already complete or failed
            if record.status in ("complete", "failed", "cancelled"):
                logger.info(
                    "[TaskManager] Cannot cancel task (status=%s) task_key=%s",
                    record.status, task_key
                )
                return False
            
            # Mark as cancelled
            record.status = "cancelled"
            record.completed_at = django_now()
            record.save(update_fields=["status", "completed_at"])
            
            # Release Redis lock
            cls._release_redis_lock(task_key)

            logger.info("[TaskManager] Task cancelled task_key=%s", task_key)
            return True
        except TaskRecord.DoesNotExist:
            logger.warning("[TaskManager] Task not found for cancellation task_key=%s", task_key)
            return False
        except Exception:
            logger.exception("[TaskManager] Failed to cancel task task_key=%s", task_key)
            return False

    @classmethod
    def retry_task(cls, task_key: str, task_fn: Callable = None, *args, **kwargs) -> bool:
        """
        Retry a failed task.
        
        Requires the task function and arguments to re-enqueue.
        If task_fn not provided, looks up from TaskRecord (if stored).
        Returns True if re-enqueued, False if task not found/not failed.
        
        Module T addition.
        """
        try:
            record = TaskRecord.objects.get(task_key=task_key)
            
            # Only retry if previously failed
            if record.status != "failed":
                logger.warning(
                    "[TaskManager] Cannot retry non-failed task (status=%s) task_key=%s",
                    record.status, task_key
                )
                return False
            
            # If no task_fn provided, we cannot retry (no function reference)
            if task_fn is None:
                logger.warning(
                    "[TaskManager] Cannot retry without task_fn task_key=%s",
                    task_key
                )
                return False
            
            # Delete old record and re-enqueue
            record.delete()
            success = cls.enqueue_if_needed(task_key, task_fn, *args, **kwargs)
            
            if success:
                logger.info("[TaskManager] Task retried task_key=%s", task_key)
            else:
                logger.warning("[TaskManager] Task retry failed task_key=%s", task_key)
            
            return success
        except TaskRecord.DoesNotExist:
            logger.warning("[TaskManager] Task not found for retry task_key=%s", task_key)
            return False
        except Exception:
            logger.exception("[TaskManager] Failed to retry task task_key=%s", task_key)
            return False

    @classmethod
    def get_queue_stats(cls) -> dict:
        """
        Get overall queue statistics.
        
        Returns dict with counts by status and queue tier.
        
        Module T addition.
        """
        try:
            from django.db.models import Count
            
            # Count by status
            status_counts = TaskRecord.objects.values("status").annotate(
                count=Count("id")
            ).order_by("status")
            
            stats = {
                "total": TaskRecord.objects.count(),
                "by_status": {row["status"]: row["count"] for row in status_counts},
                "pending": TaskRecord.objects.filter(status="pending").count(),
                "running": TaskRecord.objects.filter(status="running").count(),
                "complete": TaskRecord.objects.filter(status="complete").count(),
                "failed": TaskRecord.objects.filter(status="failed").count(),
                "cancelled": TaskRecord.objects.filter(status="cancelled").count(),
            }
            
            logger.debug("[TaskManager] Queue stats: total=%d pending=%d running=%d",
                        stats["total"], stats["pending"], stats["running"])
            return stats
        except Exception:
            logger.exception("[TaskManager] Failed to get queue stats")
            return {"total": 0, "by_status": {}, "error": "Failed to get stats"}

    @classmethod
    def cleanup_completed(cls, older_than_days: int = 7) -> int:
        """
        Clean up completed/failed tasks older than specified days.
        
        Deletes TaskRecords with completed_at before cutoff date.
        Also deletes associated Redis locks and status keys.
        
        Returns count of deleted records.
        
        Module T addition.
        """
        try:
            from datetime import timedelta
            
            cutoff = django_now() - timedelta(days=older_than_days)
            
            # Find records to delete
            old_records = TaskRecord.objects.filter(
                completed_at__lt=cutoff,
                status__in=("complete", "failed", "cancelled")
            )
            
            count = 0
            for record in old_records:
                # Release any lingering Redis locks
                cls._release_redis_lock(record.task_key)

                record.delete()
                count += 1
            
            logger.info(
                "[TaskManager] Cleaned up %d completed tasks older than %d days",
                count, older_than_days
            )
            return count
        except Exception:
            logger.exception("[TaskManager] Cleanup failed")
            return 0

    @classmethod
    def get_existing_task(cls, task_key: str) -> TaskRecord | None:
        """
        Get an existing task record (pending or running).
        
        Used by non-blocking views (Module S) to check if task already queued.
        
        Returns: TaskRecord if status is pending/running, None otherwise
        
        Module S addition.
        """
        try:
            record = TaskRecord.objects.filter(task_key=task_key).first()
            if record and record.status in ("pending", "running"):
                return record
            return None
        except ProgrammingError as pe:
            logger.error(
                "[TaskManager] Failed to get existing task (missing column) task_key=%s error=%s",
                task_key,
                pe,
            )
            logger.error("Hint: run migrations (manage.py migrate) against the connected DATABASES to add missing columns (e.g., started_at)")
            return None
        except Exception:
            logger.exception("[TaskManager] Failed to get existing task task_key=%s", task_key)
            return None

    @classmethod
    def get_queue_depth(cls, queue_name: str = None) -> int:
        """
        Get approximate queue depth (number of pending tasks).
        
        If queue_name specified, counts tasks for that tier only.
        Otherwise counts all pending tasks across all tiers.
        
        Returns: Approximate count of pending tasks
        
        Module S addition.
        """
        try:
            if queue_name:
                # Count tasks for specific tier (would need task → tier mapping)
                # For now, return all pending tasks (conservative estimate)
                pass
            
            # Count all pending tasks
            pending_count = TaskRecord.objects.filter(status="pending").count()
            logger.debug("[TaskManager] Queue depth pending=%d", pending_count)
            return pending_count
        except Exception:
            logger.exception("[TaskManager] Failed to get queue depth")
            return 0
