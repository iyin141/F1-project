"""Python client for the F1 Control Room API."""
from .client import Answer, F1Client
from .errors import (
    AuthError, BadRequest, F1Error, NotFound, PendingError, PendingTimeout, RateLimited, ServerError,
    ServiceUnavailable,
)
from .sse import Event

__version__ = "0.1.0"
__all__ = [
    "F1Client", "Answer", "Event", "F1Error", "BadRequest", "AuthError", "NotFound", "RateLimited",
    "ServiceUnavailable", "ServerError", "PendingError", "PendingTimeout",
]
