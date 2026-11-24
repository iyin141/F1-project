"""Exceptions. Every one derives from F1Error, so `except F1Error` catches them all."""
from __future__ import annotations

from typing import Any, Optional


class F1Error(Exception):
    """Base class. `status` is the HTTP status (None for transport errors), `body` the decoded response body."""

    def __init__(self, message: str, status: Optional[int] = None, body: Any = None):
        super().__init__(message)
        self.status = status
        self.body = body


class BadRequest(F1Error):
    """400: a parameter was rejected."""


class AuthError(F1Error):
    """401 or 403: missing, unknown or disabled API key."""


class NotFound(F1Error):
    """404: no such resource (or no stored data, for the Chaos and MCP-style endpoints)."""


class RateLimited(F1Error):
    """429: the API key's tier budget is used up. `retry_after` is in seconds when the server said."""

    def __init__(self, message: str, status: int = 429, body: Any = None, retry_after: Optional[float] = None):
        super().__init__(message, status, body)
        self.retry_after = retry_after


class ServiceUnavailable(F1Error):
    """503 with Retry-After: the data source is temporarily unusable (for example a recent track-map build failure)."""

    def __init__(self, message: str, status: int = 503, body: Any = None, retry_after: Optional[float] = None):
        super().__init__(message, status, body)
        self.retry_after = retry_after


class ServerError(F1Error):
    """Any other 5xx."""


class PendingError(F1Error):
    """202: the server queued the work (`task_key`) and has no result yet. Retry later, or pass `wait=` to poll."""

    def __init__(self, message: str, body: Any = None, task_key: Optional[str] = None, retry_after: Optional[float] = None):
        super().__init__(message, 202, body)
        self.task_key = task_key
        self.retry_after = retry_after


class PendingTimeout(PendingError):
    """`wait=` ran out while the server still answered 202."""
