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

from api.models import TaskRecord

logger = logging.getLogger(__name__)


STALE_MINUTES = 10


class TaskManager:
    """
    Stateless service for Celery task lifecycle — dispatch, tracking, and state transitions.
    All methods are class methods (no instance state).
    """

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
        
        The lock (TaskRecord) is created BEFORE the task is queued, ensuring that
        any concurrent enqueue_if_needed call will see the pending record and skip.
        """
        # Create the lock record FIRST — establishes distributed lock
        record = TaskRecord.objects.create(task_key=task_key, status="pending")
        logger.info("[TaskManager] task_lock_acquired task_key=%s record_id=%s", task_key, record.id)

        # Queue the task — handle Redis being unavailable silently
        try:
            async_result = task_fn.delay(task_key, *args, **kwargs)
            record.celery_task_id = async_result.id
            record.save(update_fields=["celery_task_id"])
            logger.info("[TaskManager] Enqueued task_key=%s celery_id=%s", task_key, async_result.id)
            return True
        except Exception as exc:
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
        """
        try:
            record = TaskRecord.objects.get(task_key=task_key)
            record.status = "running"
            record.save(update_fields=["status"])
            logger.info("event=task_running task_key=%s", task_key)
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
        """
        try:
            record = TaskRecord.objects.get(task_key=task_key)
            record.status = "complete"
            record.completed_at = django_now()
            record.save(update_fields=["status", "completed_at"])
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
        """
        try:
            record = TaskRecord.objects.get(task_key=task_key)
            record.status = "failed"
            record.error_message = format_exc()
            record.completed_at = django_now()
            record.save(update_fields=["status", "error_message", "completed_at"])
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
