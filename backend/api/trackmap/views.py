"""Track map, mini-sector and delta endpoints.

Auth, permission and throttle classes are the project defaults (REST_FRAMEWORK in settings:
APIKeyAuthentication, IsAPIKeyAuthenticated, APIKeyThrottle), the same as every analysis view.
"""
import logging

from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework.response import Response
from rest_framework.views import APIView

from api.queue.manager import TaskManager

from . import service
from .serializers import (
    DeltaResponseSerializer,
    MiniSectorsResponseSerializer,
    PendingSerializer,
    TrackMapResponseSerializer,
)
from .tasks import populate_track_geometry

logger = logging.getLogger(__name__)

_SESSION = OpenApiParameter(name="session", location=OpenApiParameter.QUERY, required=False, type=str, description="R (default), Q, S, SQ, FP1, FP2, FP3: session whose persisted telemetry is used")
_SCHEME = OpenApiParameter(name="scheme", location=OpenApiParameter.QUERY, required=False, type=str, description="distance (25 equal segments, default) or corners (one segment per corner)")
_LAP = OpenApiParameter(name="lap", location=OpenApiParameter.QUERY, required=False, type=str, description="'fastest' (default) or a lap number, applied to every driver")


def _bad(exc):
    return Response({"error": str(exc)}, status=400)


def _not_found(exc):
    return Response({"error": str(exc)}, status=404)


def _missing_geometry(year, round_number, scheme="distance"):
    """Geometry not stored. Never loads FastF1 here: 503 + Retry-After if a build failed recently
    (503, not 424/500: the data source is temporarily unusable and a retry later can succeed),
    otherwise enqueue the build and answer 202 right away."""
    failure = service.get_failure(year, round_number)
    if failure:
        resp = Response(
            {"status": "failed", "error": "Track geometry could not be built.", "reason": failure["reason"], "retry_after": failure["retry_after"]},
            status=503,
        )
        resp["Retry-After"] = str(failure["retry_after"])
        return resp
    task_key = f"track_map:{year}:{round_number}:{scheme}"
    TaskManager.enqueue_if_needed(task_key, populate_track_geometry, year, round_number, scheme=scheme)
    return Response(
        {"status": "pending", "task_key": task_key, "detail": "Track geometry is being built; retry shortly."},
        status=202,
    )


class TrackMapAPIView(APIView):

    @extend_schema(
        operation_id="analysis_track_map_retrieve",
        summary="Get track outline, corners, mini-sector boundaries and DRS zones",
        description="Returns the circuit outline built from the pole lap: columnar x/y/z/distance points (about 1,500, uniform distance step), corner markers, the chosen mini-sector scheme as boundaries in metres, and DRS zones. If the geometry has not been built yet the build is queued and the response is an immediate 202 pending; if a recent build failed it is 503 with the reason and Retry-After.",
        parameters=[_SCHEME],
        responses={200: TrackMapResponseSerializer, 202: PendingSerializer, 400: OpenApiResponse(description="Invalid scheme"), 503: OpenApiResponse(description="A recent geometry build failed; see reason and Retry-After")},
    )
    def get(self, request, year, round_number):
        request.endpoint_type = "track_map"
        try:
            scheme = service.parse_scheme(request.query_params.get("scheme"))
        except service.ParamError as exc:
            return _bad(exc)
        geom = service.get_geometry_payload(year, round_number)
        if geom is None:
            return _missing_geometry(year, round_number, scheme)
        return Response(service.track_map_response(geom, scheme, year, round_number))


class MiniSectorsAPIView(APIView):

    @extend_schema(
        operation_id="analysis_mini_sectors_retrieve",
        summary="Compare drivers per mini-sector",
        description="Time per mini-sector for each requested driver, the fastest driver in each segment (the purple-sector map) and every driver's gap to the fastest. Segment times come from each lap's persisted distance and speed traces placed on the track geometry; when the lap table has the lap time, the trace is scaled so the segments add up to it (lap_time_source=official), otherwise lap_time_source=integrated. Returns 202 and queues the geometry build if it does not exist yet, and 404 if a driver has no persisted telemetry.",
        parameters=[
            OpenApiParameter(name="drivers", location=OpenApiParameter.QUERY, required=True, type=str, description="Comma-separated 3-letter driver codes, e.g. VER,NOR (max 20)"),
            _LAP, _SCHEME, _SESSION,
        ],
        responses={200: MiniSectorsResponseSerializer, 202: PendingSerializer, 400: OpenApiResponse(description="Missing or invalid query parameters"), 503: OpenApiResponse(description="A recent geometry build failed"), 404: OpenApiResponse(description="No persisted telemetry for a driver or lap")},
    )
    def get(self, request, year, round_number):
        request.endpoint_type = "telemetry"
        q = request.query_params
        try:
            drivers = service.parse_drivers(q.get("drivers"))
            lap = service.parse_lap(q.get("lap"))
            scheme = service.parse_scheme(q.get("scheme"))
            session = service.parse_session(q.get("session"))
        except service.ParamError as exc:
            return _bad(exc)
        geom = service.get_geometry_payload(year, round_number)
        if geom is None:
            return _missing_geometry(year, round_number, scheme)
        try:
            return Response(service.mini_sectors_response(geom, scheme, year, round_number, session, drivers, lap))
        except service.TraceUnavailable as exc:
            return _not_found(exc)


class TelemetryDeltaAPIView(APIView):

    @extend_schema(
        operation_id="analysis_telemetry_delta_retrieve",
        summary="Delta time between two drivers by distance",
        description="Time difference (cmp minus ref, seconds) at each point of the track geometry's distance grid, both laps interpolated onto that common grid. Positive means cmp is slower. Returns 202 and queues the geometry build if it does not exist yet, and 404 if a driver has no persisted telemetry.",
        parameters=[
            OpenApiParameter(name="ref", location=OpenApiParameter.QUERY, required=True, type=str, description="Reference driver code"),
            OpenApiParameter(name="cmp", location=OpenApiParameter.QUERY, required=True, type=str, description="Compared driver code"),
            _LAP, _SESSION,
        ],
        responses={200: DeltaResponseSerializer, 202: PendingSerializer, 400: OpenApiResponse(description="Missing or invalid query parameters"), 503: OpenApiResponse(description="A recent geometry build failed"), 404: OpenApiResponse(description="No persisted telemetry for a driver or lap")},
    )
    def get(self, request, year, round_number):
        request.endpoint_type = "telemetry"
        q = request.query_params
        try:
            ref = service.parse_driver(q.get("ref"), "ref")
            cmp_ = service.parse_driver(q.get("cmp"), "cmp")
            lap = service.parse_lap(q.get("lap"))
            session = service.parse_session(q.get("session"))
        except service.ParamError as exc:
            return _bad(exc)
        geom = service.get_geometry_payload(year, round_number)
        if geom is None:
            return _missing_geometry(year, round_number)
        try:
            return Response(service.delta_response(geom, year, round_number, session, ref, cmp_, lap))
        except service.TraceUnavailable as exc:
            return _not_found(exc)
