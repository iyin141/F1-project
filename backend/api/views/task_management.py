"""
Task management endpoints — Module T: TaskManager Methods.

Provides endpoints for:
- Getting task details
- Canceling tasks
- Retrying failed tasks
- Getting queue statistics
- Cleaning up completed tasks
"""

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.status import HTTP_200_OK, HTTP_400_BAD_REQUEST, HTTP_404_NOT_FOUND
from drf_spectacular.utils import extend_schema
import logging

from api.queue.manager import TaskManager

logger = logging.getLogger(__name__)


class TaskDetailsView(APIView):
    """Get detailed information about a specific task."""
    
    @extend_schema(
        operation_id="tasks_details_retrieve",
        summary="Get task details",
        description="Returns complete information about a task including status, timestamps, and error details."
    )
    def get(self, request, task_key: str):
        """Get task details by task_key."""
        details = TaskManager.get_task_details(task_key)
        
        if not details:
            return Response(
                {"error": f"Task not found: {task_key}"},
                status=HTTP_404_NOT_FOUND
            )
        
        logger.info("[TaskDetails] Retrieved task_key=%s status=%s", task_key, details.get("status"))
        return Response(details, status=HTTP_200_OK)


class TaskCancelView(APIView):
    """Cancel a queued or running task."""
    
    @extend_schema(
        operation_id="tasks_cancel_create",
        summary="Cancel a task",
        description="Revokes a task if it's queued or running. Cannot cancel completed or failed tasks."
    )
    def post(self, request, task_key: str):
        """Cancel task by task_key."""
        success = TaskManager.cancel_task(task_key)
        
        if not success:
            return Response(
                {"error": f"Failed to cancel task: {task_key}", "message": "Task may not exist or already completed"},
                status=HTTP_400_BAD_REQUEST
            )
        
        logger.info("[TaskCancel] Task cancelled task_key=%s", task_key)
        return Response(
            {"status": "cancelled", "task_key": task_key},
            status=HTTP_200_OK
        )


class TaskRetryView(APIView):
    """Retry a failed task."""
    
    @extend_schema(
        operation_id="tasks_retry_create",
        summary="Retry a failed task",
        description="Re-enqueues a failed task. Requires the original task function name and arguments."
    )
    def post(self, request, task_key: str):
        """Retry a failed task by task_key."""
        # Note: Retry requires the task function, which we don't have from the key alone.
        # This is a limitation without storing the full task function reference.
        return Response(
            {"error": "Retry requires task function reference which is not stored", 
             "message": "Manual task re-dispatch required"},
            status=HTTP_400_BAD_REQUEST
        )


class TaskQueueStatsView(APIView):
    """Get queue statistics."""
    
    @extend_schema(
        operation_id="tasks_queue_stats_retrieve",
        summary="Get queue statistics",
        description="Returns overall task queue statistics including counts by status."
    )
    def get(self, request):
        """Get queue statistics."""
        stats = TaskManager.get_queue_stats()
        
        logger.info(
            "[QueueStats] Stats retrieved total=%d pending=%d running=%d",
            stats.get("total", 0),
            stats.get("pending", 0),
            stats.get("running", 0)
        )
        return Response(stats, status=HTTP_200_OK)


class TaskCleanupView(APIView):
    """Clean up old completed/failed tasks."""
    
    @extend_schema(
        operation_id="tasks_cleanup_create",
        summary="Clean up old tasks",
        description="Deletes completed/failed tasks older than specified days (default 7)."
    )
    def post(self, request):
        """Trigger cleanup of completed tasks."""
        older_than_days = request.data.get("older_than_days", 7)
        
        # Validate input
        try:
            older_than_days = int(older_than_days)
            if older_than_days < 1:
                return Response(
                    {"error": "older_than_days must be >= 1"},
                    status=HTTP_400_BAD_REQUEST
                )
        except (ValueError, TypeError):
            return Response(
                {"error": "older_than_days must be an integer"},
                status=HTTP_400_BAD_REQUEST
            )
        
        count = TaskManager.cleanup_completed(older_than_days)
        
        logger.info("[TaskCleanup] Cleaned up %d tasks older than %d days", count, older_than_days)
        return Response(
            {"cleaned_up": count, "older_than_days": older_than_days},
            status=HTTP_200_OK
        )
