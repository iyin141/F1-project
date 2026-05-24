"""
Task status endpoint — Phase 5: Non-blocking views with 202 async pattern.

Implements `/api/tasks/{task_id}/status/` endpoint for polling task progress.
Returns four-state status (queued, loading, complete, failed) plus estimated wait time.
"""
from __future__ import annotations

import logging
from typing import Optional

from celery.result import AsyncResult
from django.core.cache import cache
from django.http import JsonResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status as http_status
from drf_spectacular.utils import extend_schema

from api.models import TaskRecord
from api.queue.manager import TaskManager

logger = logging.getLogger(__name__)


def get_task_status_and_progress(task_id: str) -> tuple[str, dict]:
    """
    Get current task status and progress details.
    
    Returns: (state_str, details_dict) where state_str is one of:
        - "queued" — task enqueued but not started
        - "loading" — worker actively executing
        - "complete" — data ready in Redis
        - "failed" — task failed
    
    Details dict includes:
        - task_id
        - status
        - error (if failed)
        - queue_depth (if queued)
        - estimated_wait_seconds (if queued)
    """
    details = {"task_id": task_id}
    
    try:
        # Check TaskRecord first (our distributed tracking)
        task_record = TaskRecord.objects.filter(celery_task_id=task_id).first()
        
        if task_record:
            # Map TaskRecord status to 4-state model
            if task_record.status == "complete":
                return "complete", {**details, "status": "complete"}
            elif task_record.status == "failed":
                return "failed", {
                    **details,
                    "status": "failed",
                    "error": task_record.error_message or "Unknown error",
                }
            elif task_record.status == "running":
                return "loading", {**details, "status": "loading"}
            elif task_record.status == "pending":
                # Still queued; estimate wait time
                queue_depth = estimate_queue_depth(task_id)
                wait_estimate = estimate_queue_wait_time(queue_depth, task_record.task_key)
                return "queued", {
                    **details,
                    "status": "queued",
                    "queue_depth": queue_depth,
                    "estimated_wait_seconds": wait_estimate,
                }
        
        # Fallback: Check Celery AsyncResult
        celery_result = AsyncResult(task_id)
        
        if celery_result.state == "SUCCESS":
            return "complete", {**details, "status": "complete"}
        elif celery_result.state == "FAILURE":
            return "failed", {
                **details,
                "status": "failed",
                "error": str(celery_result.result),
            }
        elif celery_result.state == "STARTED":
            return "loading", {**details, "status": "loading"}
        elif celery_result.state == "PENDING":
            queue_depth = estimate_queue_depth(task_id)
            wait_estimate = estimate_queue_wait_time(queue_depth, task_id)
            return "queued", {
                **details,
                "status": "queued",
                "queue_depth": queue_depth,
                "estimated_wait_seconds": wait_estimate,
            }
        elif celery_result.state == "RETRY":
            return "loading", {**details, "status": "loading", "note": "Task retrying"}
        elif celery_result.state == "REVOKED":
            return "failed", {**details, "status": "failed", "error": "Task revoked"}
        else:
            # Unknown state
            return "queued", {
                **details,
                "status": "queued",
                "note": f"Unknown Celery state: {celery_result.state}",
            }
    
    except Exception as exc:
        logger.warning("[TaskStatus] Status check failed task_id=%s error=%s", task_id, exc)
        return "queued", {**details, "status": "queued", "error": str(exc)}


def estimate_queue_depth(task_id: str) -> int:
    """
    Estimate how many tasks are queued ahead of this one.
    
    This is a rough estimate based on:
    - Number of pending TaskRecords across all tiers
    - Task's queue tier
    
    Returns estimated depth (0 if unable to determine).
    """
    try:
        # Get task's tier from TaskRecord or estimate
        task_record = TaskRecord.objects.filter(celery_task_id=task_id).first()
        if not task_record:
            return 0
        
        # Count pending tasks (rough estimate across all tiers)
        pending_count = TaskRecord.objects.filter(status="pending").count()
        
        # Cache the estimate briefly so multiple polls don't re-query
        cache.set(f"queue_depth:{task_id}", pending_count, timeout=5)
        
        return pending_count
    except Exception as exc:
        logger.warning("[QueueDepth] Estimation failed task_id=%s error=%s", task_id, exc)
        return 0


def estimate_queue_wait_time(queue_depth: int, task_id: str) -> int:
    """
    Estimate wait time in seconds based on queue depth and task type.
    
    Factors in:
    - Task tier (tier1 ~50ms per task, tier4 ~10s per task)
    - Number of workers per tier
    - Queue depth
    
    Returns estimated wait time in seconds.
    """
    if queue_depth <= 0:
        return 0
    
    try:
        task_record = TaskRecord.objects.filter(celery_task_id=task_id).first()
        if not task_record:
            # Conservative estimate: 1s per task
            return min(queue_depth, 300)  # Cap at 5 min
        
        # Estimate based on typical task duration
        # This is rough; real implementation would use per-tier metrics
        task_key = task_record.task_key
        
        if "telemetry" in task_key or "tier4" in task_key:
            # Tier 4: ~10s per task, 2 workers
            avg_duration = 10
            workers = 2
        elif "laps" in task_key or "tier3" in task_key:
            # Tier 3: ~5s per task, 3-4 workers
            avg_duration = 5
            workers = 3
        elif "results" in task_key or "tier2" in task_key:
            # Tier 2: ~1s per task, 4-6 workers
            avg_duration = 1
            workers = 5
        else:
            # Tier 1: ~0.1s per task, 8-10 workers
            avg_duration = 0.1
            workers = 8
        
        # Estimate: depth / workers * avg_duration
        estimated_wait = (queue_depth / workers) * avg_duration
        
        # Cap at 5 minutes
        return min(int(estimated_wait), 300)
    
    except Exception as exc:
        logger.warning("[WaitTime] Estimation failed task_id=%s error=%s", task_id, exc)
        return min(queue_depth, 300)


@api_view(["GET"])
@never_cache  # Critical: NEVER cache status endpoint
def task_status_view(request, task_id: str):
    """
    Get current task status for polling.
    
    GET /api/tasks/{task_id}/status/
    
    Response (200 OK):
    {
        "task_id": "abc123",
        "status": "queued|loading|complete|failed",
        "queue_depth": 2,
        "estimated_wait_seconds": 15,
        "error": "..." (if failed)
    }
    """
    # Validate task_id format (basic protection against injection)
    if not task_id or len(task_id) > 100 or not all(c.isalnum() or c == "-" for c in task_id):
        return Response(
            {"error": "Invalid task_id format"},
            status=http_status.HTTP_400_BAD_REQUEST,
        )
    
    # Get status
    state, details = get_task_status_and_progress(task_id)
    
    logger.info("[TaskStatusView] Status check task_id=%s state=%s", task_id, state)
    
    # Always return 200 (not 202) for status checks
    return Response(details, status=http_status.HTTP_200_OK)


# Alternative: Class-based view version
from rest_framework.views import APIView


class TaskStatusAPIView(APIView):
    """DRF class-based view for task status polling."""
    
    @extend_schema(operation_id="tasks_status_retrieve")
    def get(self, request, task_id: str):
        """Get task status."""
        # Validate task_id
        if not task_id or len(task_id) > 100 or not all(c.isalnum() or c == "-" for c in task_id):
            return Response(
                {"error": "Invalid task_id format"},
                status=http_status.HTTP_400_BAD_REQUEST,
            )
        
        # Get status
        state, details = get_task_status_and_progress(task_id)
        
        logger.info("[TaskStatusView] Status check task_id=%s state=%s", task_id, state)
        
        # Add no-cache headers explicitly (DRF respects @never_cache at function level)
        response = Response(details, status=http_status.HTTP_200_OK)
        response["Cache-Control"] = "no-cache, no-store, must-revalidate, private"
        response["Pragma"] = "no-cache"
        response["Expires"] = "0"
        return response
