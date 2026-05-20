"""
Request ID middleware for distributed tracing across HTTP and Celery task boundaries.

Every HTTP request gets a UUID4 assigned and stored in threading.local(). This allows:
- All logs from a single request to share the same request_id
- Celery tasks spawned by a request to inherit the parent request_id
- End-to-end tracing from HTTP request → task enqueue → task execution → DB

Usage:
    # In view or any handler:
    from api.common.request_id import get_request_id
    request_id = get_request_id()  # Returns UUID4 or "no-request-id" from Celery worker
    
    # In Celery task:
    @shared_task(bind=True)
    def my_task(self, request_id="no-request-id"):
        # request_id automatically passed by view when enqueuing via TaskManager
        logger.info("Task started", extra={"request_id": request_id})
"""

import uuid
import threading
from typing import Optional

from django.http import HttpRequest, HttpResponse
from django.utils.deprecation import MiddlewareMixin


# Thread-local storage for request ID
_request_id_storage = threading.local()


class RequestIdMiddleware(MiddlewareMixin):
    """
    Middleware that assigns a unique request ID to every HTTP request.
    
    Request ID is stored in threading.local() for access anywhere in the request lifecycle
    without passing as a parameter. Also sets X-Request-ID response header.
    """

    def process_request(self, request: HttpRequest) -> Optional[HttpResponse]:
        """Generate and store UUID4 request ID."""
        request_id = str(uuid.uuid4())
        _request_id_storage.request_id = request_id
        return None

    def process_response(self, request: HttpRequest, response: HttpResponse) -> HttpResponse:
        """Add X-Request-ID header to response."""
        request_id = getattr(_request_id_storage, "request_id", "no-request-id")
        response["X-Request-ID"] = request_id
        return response


def get_request_id() -> str:
    """
    Retrieve the request ID for the current request/task context.
    
    Returns:
        str: UUID4 string if called within HTTP request context, "no-request-id" if called
             from Celery worker or other async context.
    """
    return getattr(_request_id_storage, "request_id", "no-request-id")
