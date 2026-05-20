"""Cursor-based pagination classes for high-cardinality F1 data endpoints.

Use these classes on individual views via the `pagination_class` attribute —
NOT as the global DEFAULT_PAGINATION_CLASS, which is intentionally unset so
that most endpoints remain unpaginated (they return complete JSON payloads).
"""
from rest_framework.pagination import CursorPagination


class LapCursorPagination(CursorPagination):
    """Cursor pagination for lap-level data ordered by lap number.

    Use on endpoints that return per-lap rows where the full season lap list
    would be too large for a single response.
    """
    ordering = "lap_number"
    page_size = 25
    page_size_query_param = "page_size"
    max_page_size = 100


class TelemetryCursorPagination(CursorPagination):
    """Cursor pagination for telemetry samples ordered by distance.

    Telemetry data has many thousands of samples per lap; 500 samples per page
    keeps responses manageable while allowing full traversal.
    """
    ordering = "distance"
    page_size = 500
    page_size_query_param = "page_size"
    max_page_size = 2000


class PositionCursorPagination(CursorPagination):
    """Cursor pagination for position data ordered by lap and driver.

    50 records per page provides a compact view of the timing tower grid
    across multiple laps.
    """
    ordering = ["lap_number", "driver_code"]
    page_size = 50
    page_size_query_param = "page_size"
    max_page_size = 200
