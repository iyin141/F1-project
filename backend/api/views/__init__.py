from rest_framework.response import Response
from rest_framework import serializers as drf_serializers
from rest_framework.views import APIView
from drf_spectacular.utils import OpenApiExample, OpenApiParameter, OpenApiResponse, OpenApiTypes, extend_schema, inline_serializer
import logging
import time
from datetime import datetime

from django.utils import timezone
from django.utils.timezone import make_aware

from ..serializers import (
    ConstructorSerializer,
    ConstructorStandingsResponseSerializer,
    DriverStandingsResponseSerializer,
    DriverStandingSerializer,
    LapAnalysisResponseSerializer,
    PaceAnalysisResponseSerializer,
    PracticeResultSerializer,
    QualifyingResultSerializer,
    RaceResultsSerializer,
    RaceSerializer,
    StintAnalysisResponseSerializer,
    SectorAnalysisResponseSerializer,
    TelemetryAnalysisResponseSerializer,
    TelemetryOverlayResponseSerializer,
    TelemetrySummaryResponseSerializer,
    TyreStrategyResponseSerializer,
    WeatherResponseSerializer,
    PitStopResponseSerializer,
    IncidentResponseSerializer,
    PositionResponseSerializer,
    DRSResponseSerializer,
    TrackStatusResponseSerializer,
)
from ..services.analysis import (
    get_lap_analysis,
    get_pace_analysis,
    get_sector_analysis,
    get_stint_analysis,
    get_telemetry_overlay,
    get_telemetry_snapshot,
    get_telemetry_summary,
    get_tyre_strategy_analysis,
)
from ..services.unified_service import SessionManager, TelemetryExtractor, WeatherExtractor, PitStopExtractor, IncidentExtractor, PositionExtractor, DRSExtractor, TrackStatusExtractor, EXTRACTORS_MAP
from ..services.constructors import get_constructor_standings
from ..services.drivers import get_driver_standings
from ..services.readiness import is_data_unavailable_error
from ..services.results import get_practice_session_results, get_qualifying_results, get_race_results, get_sprint_results, get_sprint_shootout_results
from ..services.schedule import get_race_by_round, get_season_schedule
from ..tasks import (
    populate_weather,
    populate_pit_stops,
    populate_incidents,
    populate_positions,
    populate_drs,
    populate_track_status,
    populate_race_results,
    populate_laps,
    populate_stint_analysis,
    populate_pace_analysis,
    populate_sector_analysis,
    populate_tyre_strategy,
    populate_telemetry,
    populate_telemetry_overlay,
    populate_telemetry_summary,
)
from ..services.task_manager import TaskManager
from ..services.utils import is_current_year
from ..services import nonblocking
from ..services.streaming import stream_unified_full_session_json


logger = logging.getLogger(__name__)


def _is_unsupported_session_error(exc: Exception) -> bool:
    return is_data_unavailable_error(exc)


def _build_unified_unavailable_response(year, round_number, session_name, unavailable_type, detail_message, driver=None, limit=None):
    return {
        "meta": {
            "year": int(year),
            "round": int(round_number),
            "session": str(session_name).upper(),
            "row_count": 0,
            "extracted_at": datetime.now().isoformat(),
            "limit_max": 2000,
            "can_proceed": False,
            "available_data": [],
            "unavailable_data": [str(unavailable_type)],
            "message": detail_message,
            "warnings": [detail_message],
        },
        "filters_applied": {
            "driver": str(driver).upper() if driver else None,
            "limit": limit,
        },
        "data": [],
    }


def _build_checklist(can_proceed=True, available_data=None, unavailable_data=None, message=None, warnings=None):
    available_data = available_data or []
    unavailable_data = unavailable_data or []
    if warnings is None:
        warnings = [] if can_proceed else ([message] if message else [])
    return {
        "can_proceed": bool(can_proceed),
        "available_data": list(available_data),
        "unavailable_data": list(unavailable_data),
        "message": message,
        "warnings": list(warnings),
    }


def _ensure_payload_meta_checklist(payload, available_defaults=None, unavailable_defaults=None):
    available_defaults = available_defaults or []
    unavailable_defaults = unavailable_defaults or []
    if not isinstance(payload, dict):
        return payload

    meta = payload.get("meta")
    if not isinstance(meta, dict):
        return payload

    if "can_proceed" in meta and "available_data" in meta and "unavailable_data" in meta:
        return payload

    row_count = meta.get("row_count", 0)
    can_proceed = bool(row_count) and not bool(unavailable_defaults)
    message = meta.get("message")
    if not can_proceed and not message:
        if unavailable_defaults:
            message = f"Session loaded, but required data is unavailable. Missing: {', '.join(unavailable_defaults)}."
        else:
            message = "No data available for the requested dataset."
    meta.update(
        _build_checklist(
            can_proceed=can_proceed,
            available_data=available_defaults if can_proceed else [],
            unavailable_data=[] if can_proceed else (unavailable_defaults or available_defaults),
            message=None if can_proceed else message,
            warnings=[] if can_proceed else ([message] if message else []),
        )
    )
    return payload


def _error_payload(domain, message, code):
    return {
        "error": f"{domain} error: {message}",
        "error_code": code,
    }


class ConstructorStandingsAPIView(APIView):
    @extend_schema(
        summary="Get constructor championship standings",
        description=(
            "Same dual-source strategy as driver standings but aggregated at the constructor "
            "(team) level. Returns each team's total points and wins for the season. "
            "Useful for building a Constructors' Championship table or a team-comparison view."
        ),
        responses={200: ConstructorStandingsResponseSerializer},
        examples=[
            OpenApiExample(
                "Constructor Standings Readiness",
                value={
                    "year": 2021,
                    "constructors": [
                        {
                            "position": 1,
                            "constructor_name": "Mercedes",
                            "points": 613.5,
                            "wins": 9,
                        }
                    ],
                    "readiness": {
                        "can_proceed": True,
                        "available_data": ["constructor_standings_api"],
                        "unavailable_data": [],
                        "message": None,
                        "warnings": [],
                    },
                },
                response_only=True,
                status_codes=["200"],
            )
        ],
    )
    def get(self, request, year):
        try:
            standings = get_constructor_standings(year)
            if isinstance(standings, dict):
                rows = standings.get("data", [])
                readiness = standings.get("meta", {}).get("readiness")
            else:
                rows = standings
                readiness = None

            serializer = ConstructorSerializer(rows, many=True)
            return Response(
                {
                    "year": year,
                    "constructors": serializer.data,
                    "readiness": readiness
                    or _build_checklist(
                        bool(rows),
                        ["constructor_standings_api"] if rows else [],
                        [] if rows else ["constructor_standings_api"],
                        None if rows else f"No constructor standings data returned for {year}.",
                        [] if rows else [f"No constructor standings data returned for {year}."]
                    ),
                }
            )
        except Exception as exc:
            return Response(_error_payload("constructors.standings", str(exc), "CONSTRUCTORS_STANDINGS_ERROR"), status=500)


class AnalysisLapsAPIView(APIView):
    @extend_schema(
        summary="Get lap-by-lap analysis",
        description=(
            "Returns one row per valid lap containing the driver, lap number, total lap time, "
            "all three sector times, tyre compound, stint number, and a personal-best flag. "
            "Laps with no recorded LapTime are excluded. Supports all five session types "
            "(R, Q, FP1-FP3). Use the driver filter to narrow to one driver and limit to "
            "cap the result set."
        ),
        parameters=[
            OpenApiParameter(name="session", location=OpenApiParameter.QUERY, required=False, type=str, description="R, Q, S, SQ, FP1, FP2, FP3"),
            OpenApiParameter(name="driver", location=OpenApiParameter.QUERY, required=False, type=str, description="3-letter driver code"),
            OpenApiParameter(name="limit", location=OpenApiParameter.QUERY, required=False, type=int, description="Maximum rows to return"),
        ],
        responses={
            200: LapAnalysisResponseSerializer,
            400: OpenApiResponse(description="Invalid query parameters"),
        },
        examples=[
            OpenApiExample(
                "Readiness Proceed",
                value={
                    "meta": {
                        "year": 2020,
                        "round": 2,
                        "session": "R",
                        "row_count": 5,
                        "limit_max": 2000,
                        "can_proceed": True,
                        "available_data": ["laps", "track_status"],
                        "unavailable_data": [],
                        "message": None,
                        "warnings": [],
                    },
                    "filters_applied": {"driver": None, "limit": 5},
                    "data": [
                        {
                            "driver_code": "VER",
                            "lap_number": 1,
                            "lap_time": "0 days 00:01:37.123000",
                            "sector1": "0 days 00:00:31.100000",
                            "sector2": "0 days 00:00:33.000000",
                            "sector3": "0 days 00:00:33.023000",
                            "compound": "MEDIUM",
                            "stint": 1,
                            "is_personal_best": False,
                        }
                    ],
                },
                response_only=True,
                status_codes=["200"],
            ),
            OpenApiExample(
                "Readiness Partial Unsupported",
                value={
                    "meta": {
                        "year": 2016,
                        "round": 3,
                        "session": "R",
                        "row_count": 0,
                        "limit_max": 2000,
                        "can_proceed": False,
                        "available_data": ["track_status"],
                        "unavailable_data": ["laps"],
                        "message": "Session loaded, but required data is unavailable for 2016 Round 3 (R). Missing: laps.",
                        "warnings": ["Session loaded, but required data is unavailable for 2016 Round 3 (R). Missing: laps."],
                    },
                    "filters_applied": {"driver": None, "limit": 5},
                    "data": [],
                },
                response_only=True,
                status_codes=["200"],
            ),
        ],
    )
    def get(self, request, year, round_number):
        try:
            session_name = request.query_params.get("session", "R")
            driver = request.query_params.get("driver")
            limit_param = request.query_params.get("limit")

            limit = None
            if limit_param is not None and limit_param != "":
                try:
                    limit = int(limit_param)
                except (TypeError, ValueError):
                    return Response({"error": "limit must be an integer"}, status=400)

            normalized_driver = str(driver).upper() if driver else ""
            cache_key = f"analysis_laps:{year}:{round_number}:{session_name}:{normalized_driver}:{limit or ''}"
            task_key = cache_key

            def db_fetch():
                from ..services.persistence import get_persisted_lap_analysis
                persisted = get_persisted_lap_analysis(year, round_number, str(session_name).upper(), driver, limit)
                if persisted and persisted.get("data"):
                    # Apply checklist format
                    payload = _ensure_payload_meta_checklist(persisted, ["laps"], [])
                    # Apply DRF serializer formatting directly in the fetch so the cached data matches exactly
                    serializer = LapAnalysisResponseSerializer(payload)
                    return serializer.data
                return None

            return nonblocking.handle_data_request(
                cache_key=cache_key,
                db_fetch_fn=db_fetch,
                task_fn=populate_laps,
                task_key=task_key,
                task_args=(year, round_number, session_name),
                task_kwargs={"driver": driver, "limit": limit},
            )
        except ValueError as exc:
            return Response({"error": str(exc)}, status=400)
        except Exception as exc:
            return Response(_error_payload("analysis.laps", str(exc), "ANALYSIS_LAPS_ERROR"), status=500)


class AnalysisStintsAPIView(APIView):
    @extend_schema(
        summary="Get stint-level analysis",
        description=(
            "Groups consecutive laps on the same tyre compound into stints and returns "
            "per-stint statistics: compound name, start/end lap, and median/min/max lap time. "
            "For Race sessions the service reads pre-computed StintData rows from the database, "
            "bypassing a live FastF1 call entirely. Useful for visualising tyre degradation "
            "and strategy comparison across drivers."
        ),
        parameters=[
            OpenApiParameter(name="session", location=OpenApiParameter.QUERY, required=False, type=str, description="R, Q, S, SQ, FP1, FP2, FP3. Default: R"),
            OpenApiParameter(name="driver", location=OpenApiParameter.QUERY, required=False, type=str, description="3-letter driver code filter"),
            OpenApiParameter(name="limit", location=OpenApiParameter.QUERY, required=False, type=int, description="Maximum rows to return"),
        ],
        responses={200: StintAnalysisResponseSerializer, 400: OpenApiResponse(description="Invalid parameters")},
    )
    def get(self, request, year, round_number):
        try:
            session_name = request.query_params.get("session", "R")
            driver = request.query_params.get("driver")
            limit_param = request.query_params.get("limit")

            limit = None
            if limit_param is not None and limit_param != "":
                try:
                    limit = int(limit_param)
                except (TypeError, ValueError):
                    return Response({"error": "limit must be an integer"}, status=400)

            normalized_driver = str(driver).upper() if driver else ""
            cache_key = f"analysis_stints:{year}:{round_number}:{session_name}:{normalized_driver}:{limit or ''}"
            task_key = cache_key

            def db_fetch():
                from ..services.persistence import get_persisted_stint_analysis
                persisted = get_persisted_stint_analysis(year, round_number, str(session_name).upper(), driver, limit)
                if persisted and persisted.get("data"):
                    payload = _ensure_payload_meta_checklist(persisted, ["laps"], [])
                    serializer = StintAnalysisResponseSerializer(payload)
                    return serializer.data
                return None

            return nonblocking.handle_data_request(
                cache_key=cache_key,
                db_fetch_fn=db_fetch,
                task_fn=populate_stint_analysis,
                task_key=task_key,
                task_args=(year, round_number, session_name),
                task_kwargs={"driver": driver, "limit": limit},
            )
        except ValueError as exc:
            return Response({"error": str(exc)}, status=400)
        except Exception as exc:
            return Response(_error_payload("analysis.stints", str(exc), "ANALYSIS_STINTS_ERROR"), status=500)


class AnalysisPaceAPIView(APIView):
    @extend_schema(
        summary="Get driver pace analysis",
        description=(
            "Aggregates lap times per driver to expose median pace, best lap, and consistency "
            "(standard deviation). For Race sessions the service reads pre-computed DriverMetric "
            "rows from the database before falling back to a live FastF1 computation, making it "
            "fast for recently populated seasons. Ideal for building a pace-comparison chart "
            "across the entire grid."
        ),
        parameters=[
            OpenApiParameter(name="session", location=OpenApiParameter.QUERY, required=False, type=str, description="R, Q, S, SQ, FP1, FP2, FP3. Default: R"),
            OpenApiParameter(name="driver", location=OpenApiParameter.QUERY, required=False, type=str, description="3-letter driver code filter"),
            OpenApiParameter(name="limit", location=OpenApiParameter.QUERY, required=False, type=int, description="Maximum rows to return"),
        ],
        responses={200: PaceAnalysisResponseSerializer, 400: OpenApiResponse(description="Invalid parameters")},
    )
    def get(self, request, year, round_number):
        try:
            session_name = request.query_params.get("session", "R")
            driver = request.query_params.get("driver")
            limit_param = request.query_params.get("limit")

            limit = None
            if limit_param is not None and limit_param != "":
                try:
                    limit = int(limit_param)
                except (TypeError, ValueError):
                    return Response({"error": "limit must be an integer"}, status=400)

            normalized_driver = str(driver).upper() if driver else ""
            cache_key = f"analysis_pace:{year}:{round_number}:{session_name}:{normalized_driver}:{limit or ''}"
            task_key = cache_key

            def db_fetch():
                from ..services.persistence import get_persisted_pace_analysis
                persisted = get_persisted_pace_analysis(year, round_number, str(session_name).upper(), driver, limit)
                if persisted and persisted.get("data"):
                    payload = _ensure_payload_meta_checklist(persisted, ["laps"], [])
                    serializer = PaceAnalysisResponseSerializer(payload)
                    return serializer.data
                return None

            return nonblocking.handle_data_request(
                cache_key=cache_key,
                db_fetch_fn=db_fetch,
                task_fn=populate_pace_analysis,
                task_key=task_key,
                task_args=(year, round_number, session_name),
                task_kwargs={"driver": driver, "limit": limit},
            )
        except ValueError as exc:
            return Response({"error": str(exc)}, status=400)
        except Exception as exc:
            return Response(_error_payload("analysis.pace", str(exc), "ANALYSIS_PACE_ERROR"), status=500)


class AnalysisTyreStrategyAPIView(APIView):
    @extend_schema(
        summary="Get tyre strategy analysis",
        description=(
            "Extends the stint view with tyre-strategy-specific fields: average lap time per "
            "stint, median lap time, and per-lap degradation in seconds. Sourced from persisted "
            "StintData for Race sessions and computed live from FastF1 otherwise. Ideal for "
            "building tyre-strategy timeline charts that show compound changes and pace impact "
            "across the race."
        ),
        parameters=[
            OpenApiParameter(name="session", location=OpenApiParameter.QUERY, required=False, type=str, description="R, Q, S, SQ, FP1, FP2, FP3. Default: R"),
            OpenApiParameter(name="driver", location=OpenApiParameter.QUERY, required=False, type=str, description="3-letter driver code filter"),
            OpenApiParameter(name="limit", location=OpenApiParameter.QUERY, required=False, type=int, description="Maximum rows to return"),
        ],
        responses={200: TyreStrategyResponseSerializer, 400: OpenApiResponse(description="Invalid parameters")},
    )
    def get(self, request, year, round_number):
        try:
            session_name = request.query_params.get("session", "R")
            driver = request.query_params.get("driver")
            limit_param = request.query_params.get("limit")

            limit = None
            if limit_param is not None and limit_param != "":
                try:
                    limit = int(limit_param)
                except (TypeError, ValueError):
                    return Response({"error": "limit must be an integer"}, status=400)

            normalized_driver = str(driver).upper() if driver else ""
            cache_key = f"analysis_tyre_strategy:{year}:{round_number}:{session_name}:{normalized_driver}:{limit or ''}"
            task_key = cache_key

            def db_fetch():
                from ..services.persistence import get_persisted_tyre_strategy_analysis
                persisted = get_persisted_tyre_strategy_analysis(year, round_number, str(session_name).upper(), driver, limit)
                if persisted and persisted.get("data"):
                    payload = _ensure_payload_meta_checklist(persisted, ["laps"], [])
                    serializer = TyreStrategyResponseSerializer(payload)
                    return serializer.data
                return None

            return nonblocking.handle_data_request(
                cache_key=cache_key,
                db_fetch_fn=db_fetch,
                task_fn=populate_tyre_strategy,
                task_key=task_key,
                task_args=(year, round_number, session_name),
                task_kwargs={"driver": driver, "limit": limit},
            )
        except ValueError as exc:
            return Response({"error": str(exc)}, status=400)
        except Exception as exc:
            return Response(_error_payload("analysis.tyre_strategy", str(exc), "ANALYSIS_TYRE_STRATEGY_ERROR"), status=500)


class AnalysisSectorAPIView(APIView):
    @extend_schema(
        summary="Get sector-time analysis",
        description=(
            "For each driver returns best and median times for Sectors 1, 2, and 3, alongside "
            "their best actual lap and the theoretical best lap (sum of each sector's individual "
            "best). The delta between actual best and theoretical best shows how close a driver "
            "came to perfecting their lap. Race-session results are served from persisted "
            "SectorAggregate rows when available."
        ),
        parameters=[
            OpenApiParameter(name="session", location=OpenApiParameter.QUERY, required=False, type=str, description="R, Q, FP1, FP2, FP3. Default: R"),
            OpenApiParameter(name="driver", location=OpenApiParameter.QUERY, required=False, type=str, description="3-letter driver code filter"),
            OpenApiParameter(name="limit", location=OpenApiParameter.QUERY, required=False, type=int, description="Maximum rows to return"),
        ],
        responses={200: SectorAnalysisResponseSerializer, 400: OpenApiResponse(description="Invalid parameters")},
    )
    def get(self, request, year, round_number):
        try:
            session_name = request.query_params.get("session", "R")
            driver = request.query_params.get("driver")
            limit_param = request.query_params.get("limit")

            limit = None
            if limit_param is not None and limit_param != "":
                try:
                    limit = int(limit_param)
                except (TypeError, ValueError):
                    return Response({"error": "limit must be an integer"}, status=400)

            normalized_driver = str(driver).upper() if driver else ""
            cache_key = f"analysis_sector:{year}:{round_number}:{session_name}:{normalized_driver}:{limit or ''}"
            task_key = cache_key

            def db_fetch():
                from ..services.persistence import get_persisted_sector_analysis
                persisted = get_persisted_sector_analysis(year, round_number, str(session_name).upper(), driver, limit)
                if persisted and persisted.get("data"):
                    payload = _ensure_payload_meta_checklist(persisted, ["laps"], [])
                    serializer = SectorAnalysisResponseSerializer(payload)
                    return serializer.data
                return None

            return nonblocking.handle_data_request(
                cache_key=cache_key,
                db_fetch_fn=db_fetch,
                task_fn=populate_sector_analysis,
                task_key=task_key,
                task_args=(year, round_number, session_name),
                task_kwargs={"driver": driver, "limit": limit},
            )
        except ValueError as exc:
            return Response({"error": str(exc)}, status=400)
        except Exception as exc:
            return Response(_error_payload("analysis.sector", str(exc), "ANALYSIS_SECTOR_ERROR"), status=500)


class AnalysisTelemetryAPIView(APIView):
    @extend_schema(
        summary="Get single-lap car telemetry",
        description=(
            "Streams car-data samples for one specific lap of one driver: speed (kph), throttle "
            "percentage, brake state, RPM, gear, and distance along the lap. Both driver and lap "
            "are required. Use limit_points and stride to downsample large payloads for charting, "
            "and sector_start / sector_end to zoom into a specific sector window (1-3) of the lap."
        ),
        parameters=[
            OpenApiParameter(name="session", location=OpenApiParameter.QUERY, required=False, type=str, description="R, Q, FP1, FP2, FP3"),
            OpenApiParameter(name="driver", location=OpenApiParameter.QUERY, required=True, type=str, description="3-letter driver code"),
            OpenApiParameter(name="lap", location=OpenApiParameter.QUERY, required=True, type=int, description="Lap number"),
            OpenApiParameter(name="limit_points", location=OpenApiParameter.QUERY, required=False, type=int, description="Maximum telemetry points"),
            OpenApiParameter(name="stride", location=OpenApiParameter.QUERY, required=False, type=int, description="Sample every N points"),
            OpenApiParameter(name="sector_start", location=OpenApiParameter.QUERY, required=False, type=int, description="Sector window start (1-3)"),
            OpenApiParameter(name="sector_end", location=OpenApiParameter.QUERY, required=False, type=int, description="Sector window end (1-3)"),
        ],
        responses={
            200: TelemetryAnalysisResponseSerializer,
            400: OpenApiResponse(description="Missing or invalid telemetry query parameters"),
        },
        examples=[
            OpenApiExample(
                "Telemetry Missing Driver",
                value={"error": "driver query parameter is required"},
                response_only=True,
                status_codes=["400"],
            )
        ],
    )
    def get(self, request, year, round_number):
        try:
            session_name = request.query_params.get("session", "R")
            driver = request.query_params.get("driver")
            lap_param = request.query_params.get("lap")
            limit_points_param = request.query_params.get("limit_points")
            stride_param = request.query_params.get("stride", "1")
            sector_start_param = request.query_params.get("sector_start")
            sector_end_param = request.query_params.get("sector_end")

            if not driver:
                return Response({"error": "driver query parameter is required"}, status=400)

            if lap_param is None or lap_param == "":
                return Response({"error": "lap query parameter is required"}, status=400)

            try:
                lap = int(lap_param)
            except (TypeError, ValueError):
                return Response({"error": "lap must be an integer"}, status=400)

            try:
                stride = int(stride_param)
            except (TypeError, ValueError):
                return Response({"error": "stride must be an integer"}, status=400)

            limit_points = None
            if limit_points_param is not None and limit_points_param != "":
                try:
                    limit_points = int(limit_points_param)
                except (TypeError, ValueError):
                    return Response({"error": "limit_points must be an integer"}, status=400)

            sector_start = None
            if sector_start_param is not None and sector_start_param != "":
                try:
                    sector_start = int(sector_start_param)
                except (TypeError, ValueError):
                    return Response({"error": "sector_start must be an integer"}, status=400)

            sector_end = None
            if sector_end_param is not None and sector_end_param != "":
                try:
                    sector_end = int(sector_end_param)
                except (TypeError, ValueError):
                    return Response({"error": "sector_end must be an integer"}, status=400)

            normalized_driver = str(driver).upper() if driver else ""
            cache_key = f"analysis_telemetry:{year}:{round_number}:{session_name}:{normalized_driver}:{lap}:{limit_points or ''}:{stride or ''}:{sector_start or ''}:{sector_end or ''}"
            task_key = cache_key

            def db_fetch():
                from ..services.persistence import get_persisted_lap_telemetry
                persisted = get_persisted_lap_telemetry(year, round_number, str(session_name).upper(), driver, lap)
                if persisted:
                    # Note: We need to properly run the extraction/filtering from the DB payload.
                    # This logic exists in `get_telemetry_snapshot` when a DB record exists.
                    # We will just let the view call the actual logic for formatting if DB exists.
                    # But actually `get_telemetry_snapshot` is already fast if it hits DB!
                    # Wait, if get_telemetry_snapshot hits DB, it takes <10ms. Let's just use it!
                    pass
                return None
                
            # If get_telemetry_snapshot hits the DB it is non-blocking. If it misses, we want to enqueue.
            # But get_telemetry_snapshot synchronously falls back to fastf1! 
            # So db_fetch needs to simulate ONLY the DB-hit part.
            def db_fetch():
                from ..services.analysis import get_persisted_lap_telemetry, _telemetry_rows_from_frame, _apply_sector_window
                from ..services.extraction import extract_telemetry
                persisted = get_persisted_lap_telemetry(year, round_number, str(session_name).upper(), driver, lap)
                if persisted:
                    points = extract_telemetry(persisted)
                    if points:
                        if stride > 1:
                            points = points[::stride]
                        if limit_points:
                            points = points[:limit_points]
                        readiness = _build_checklist(True, ["telemetry_snapshot_persisted"], [], None)
                        payload = {
                            "meta": {
                                "year": int(year),
                                "round": int(round_number),
                                "session": str(session_name).upper(),
                                "row_count": len(points),
                                "limit_max": 3000,
                                **readiness,
                            },
                            "filters_applied": {
                                "driver": normalized_driver,
                                "lap": int(lap),
                                "limit_points": limit_points,
                                "stride": stride,
                                "sector_start": sector_start,
                                "sector_end": sector_end,
                            },
                            "data": points,
                        }
                        payload = _ensure_payload_meta_checklist(payload, ["telemetry"], [])
                        serializer = TelemetryAnalysisResponseSerializer(payload)
                        return serializer.data
                return None

            return nonblocking.handle_data_request(
                cache_key=cache_key,
                db_fetch_fn=db_fetch,
                task_fn=populate_telemetry,
                task_key=task_key,
                task_args=(year, round_number, session_name),
                task_kwargs={
                    "driver": driver, "lap": lap, "limit_points": limit_points, 
                    "stride": stride, "sector_start": sector_start, "sector_end": sector_end
                },
            )
        except ValueError as exc:
            return Response({"error": str(exc)}, status=400)
        except Exception as exc:
            return Response(_error_payload("analysis.telemetry", str(exc), "ANALYSIS_TELEMETRY_ERROR"), status=500)


class AnalysisTelemetryOverlayAPIView(APIView):
    @extend_schema(
        summary="Compare telemetry of two drivers",
        description=(
            "Loads telemetry for driver_a and driver_b and returns separate traces aligned by "
            "distance so the frontend can render an overlay chart. Both driver codes are required; "
            "laps default to each driver's fastest lap when omitted. Sector windowing and "
            "downsampling work the same as the single-driver telemetry endpoint."
        ),
        parameters=[
            OpenApiParameter(name="session", location=OpenApiParameter.QUERY, required=False, type=str, description="R, Q, FP1, FP2, FP3"),
            OpenApiParameter(name="driver_a", location=OpenApiParameter.QUERY, required=True, type=str, description="First 3-letter driver code"),
            OpenApiParameter(name="driver_b", location=OpenApiParameter.QUERY, required=True, type=str, description="Second 3-letter driver code"),
            OpenApiParameter(name="lap_a", location=OpenApiParameter.QUERY, required=False, type=int, description="Lap number for driver_a"),
            OpenApiParameter(name="lap_b", location=OpenApiParameter.QUERY, required=False, type=int, description="Lap number for driver_b"),
            OpenApiParameter(name="limit_points", location=OpenApiParameter.QUERY, required=False, type=int, description="Maximum telemetry points per trace"),
            OpenApiParameter(name="stride", location=OpenApiParameter.QUERY, required=False, type=int, description="Sample every N points"),
            OpenApiParameter(name="sector_start", location=OpenApiParameter.QUERY, required=False, type=int, description="Sector window start (1-3)"),
            OpenApiParameter(name="sector_end", location=OpenApiParameter.QUERY, required=False, type=int, description="Sector window end (1-3)"),
        ],
        responses={
            200: TelemetryOverlayResponseSerializer,
            400: OpenApiResponse(description="Missing or invalid telemetry overlay query parameters"),
        },
        examples=[
            OpenApiExample(
                "Telemetry Overlay Missing Drivers",
                value={"error": "driver_a and driver_b query parameters are required"},
                response_only=True,
                status_codes=["400"],
            )
        ],
    )
    def get(self, request, year, round_number):
        try:
            session_name = request.query_params.get("session", "R")
            driver_a = request.query_params.get("driver_a")
            driver_b = request.query_params.get("driver_b")
            lap_a_param = request.query_params.get("lap_a")
            lap_b_param = request.query_params.get("lap_b")
            limit_points_param = request.query_params.get("limit_points")
            stride_param = request.query_params.get("stride", "1")
            sector_start_param = request.query_params.get("sector_start")
            sector_end_param = request.query_params.get("sector_end")

            if not driver_a or not driver_b:
                return Response({"error": "driver_a and driver_b query parameters are required"}, status=400)

            lap_a = None
            if lap_a_param is not None and lap_a_param != "":
                try:
                    lap_a = int(lap_a_param)
                except (TypeError, ValueError):
                    return Response({"error": "lap_a must be an integer"}, status=400)

            lap_b = None
            if lap_b_param is not None and lap_b_param != "":
                try:
                    lap_b = int(lap_b_param)
                except (TypeError, ValueError):
                    return Response({"error": "lap_b must be an integer"}, status=400)

            try:
                stride = int(stride_param)
            except (TypeError, ValueError):
                return Response({"error": "stride must be an integer"}, status=400)

            limit_points = None
            if limit_points_param is not None and limit_points_param != "":
                try:
                    limit_points = int(limit_points_param)
                except (TypeError, ValueError):
                    return Response({"error": "limit_points must be an integer"}, status=400)

            sector_start = None
            if sector_start_param is not None and sector_start_param != "":
                try:
                    sector_start = int(sector_start_param)
                except (TypeError, ValueError):
                    return Response({"error": "sector_start must be an integer"}, status=400)

            sector_end = None
            if sector_end_param is not None and sector_end_param != "":
                try:
                    sector_end = int(sector_end_param)
                except (TypeError, ValueError):
                    return Response({"error": "sector_end must be an integer"}, status=400)

            cache_key = f"analysis_telemetry_overlay:{year}:{round_number}:{session_name}:{driver_a}:{driver_b}:{lap_a or ''}:{lap_b or ''}:{limit_points or ''}:{stride or ''}:{sector_start or ''}:{sector_end or ''}"
            task_key = cache_key

            def db_fetch():
                # Telemetry overlay has no direct DB representation. It reads lap_telemetry for both drivers.
                return None

            return nonblocking.handle_data_request(
                cache_key=cache_key,
                db_fetch_fn=db_fetch,
                task_fn=populate_telemetry_overlay,
                task_key=task_key,
                task_args=(year, round_number, session_name),
                task_kwargs={
                    "driver_a": driver_a, "driver_b": driver_b, 
                    "lap_a": lap_a, "lap_b": lap_b, "limit_points": limit_points, 
                    "stride": stride, "sector_start": sector_start, "sector_end": sector_end
                },
            )
        except ValueError as exc:
            return Response({"error": str(exc)}, status=400)
        except Exception as exc:
            return Response(_error_payload("analysis.telemetry_overlay", str(exc), "ANALYSIS_TELEMETRY_OVERLAY_ERROR"), status=500)


class AnalysisTelemetrySummaryAPIView(APIView):
    @extend_schema(
        summary="Get telemetry summary for a lap",
        description=(
            "Returns high-level statistics computed from the telemetry of a single specified lap: "
            "maximum speed, number of braking zones detected, percentage of the lap spent on full "
            "throttle, and total sample count. Both driver and lap are required. Use "
            "sector_start / sector_end to restrict the summary to one part of the track."
        ),
        parameters=[
            OpenApiParameter(name="session", location=OpenApiParameter.QUERY, required=False, type=str, description="R, Q, FP1, FP2, FP3"),
            OpenApiParameter(name="driver", location=OpenApiParameter.QUERY, required=True, type=str, description="3-letter driver code"),
            OpenApiParameter(name="lap", location=OpenApiParameter.QUERY, required=True, type=int, description="Lap number"),
            OpenApiParameter(name="stride", location=OpenApiParameter.QUERY, required=False, type=int, description="Sample every N points"),
            OpenApiParameter(name="sector_start", location=OpenApiParameter.QUERY, required=False, type=int, description="Sector window start (1-3)"),
            OpenApiParameter(name="sector_end", location=OpenApiParameter.QUERY, required=False, type=int, description="Sector window end (1-3)"),
        ],
        responses={
            200: TelemetrySummaryResponseSerializer,
            400: OpenApiResponse(description="Missing or invalid telemetry summary query parameters"),
        },
        examples=[
            OpenApiExample(
                "Telemetry Summary Missing Driver",
                value={"error": "driver query parameter is required"},
                response_only=True,
                status_codes=["400"],
            )
        ],
    )
    def get(self, request, year, round_number):
        try:
            session_name = request.query_params.get("session", "R")
            driver = request.query_params.get("driver")
            lap_param = request.query_params.get("lap")
            stride_param = request.query_params.get("stride", "1")
            sector_start_param = request.query_params.get("sector_start")
            sector_end_param = request.query_params.get("sector_end")

            if not driver:
                return Response({"error": "driver query parameter is required"}, status=400)

            if lap_param is None or lap_param == "":
                return Response({"error": "lap query parameter is required"}, status=400)

            try:
                lap = int(lap_param)
            except (TypeError, ValueError):
                return Response({"error": "lap must be an integer"}, status=400)

            try:
                stride = int(stride_param)
            except (TypeError, ValueError):
                return Response({"error": "stride must be an integer"}, status=400)

            sector_start = None
            if sector_start_param is not None and sector_start_param != "":
                try:
                    sector_start = int(sector_start_param)
                except (TypeError, ValueError):
                    return Response({"error": "sector_start must be an integer"}, status=400)

            sector_end = None
            if sector_end_param is not None and sector_end_param != "":
                try:
                    sector_end = int(sector_end_param)
                except (TypeError, ValueError):
                    return Response({"error": "sector_end must be an integer"}, status=400)

            cache_key = f"analysis_telemetry_summary:{year}:{round_number}:{session_name}:{driver}:{lap}:{stride or ''}:{sector_start or ''}:{sector_end or ''}"
            task_key = cache_key

            def db_fetch():
                return None

            return nonblocking.handle_data_request(
                cache_key=cache_key,
                db_fetch_fn=db_fetch,
                task_fn=populate_telemetry_summary,
                task_key=task_key,
                task_args=(year, round_number, session_name),
                task_kwargs={
                    "driver": driver, "lap": lap, "stride": stride, 
                    "sector_start": sector_start, "sector_end": sector_end
                },
            )
        except ValueError as exc:
            return Response({"error": str(exc)}, status=400)
        except Exception as exc:
            return Response(_error_payload("analysis.telemetry_summary", str(exc), "ANALYSIS_TELEMETRY_SUMMARY_ERROR"), status=500)


# ============================================================================
# Unified Service Endpoints - Access all FastF1 data via modular extractors
# ============================================================================


class UnifiedFullSessionAPIView(APIView):
    """Query multiple data types from a session simultaneously."""

    @extend_schema(
        summary="Get multiple data types in one request",
        description=(
            "Accepts a comma-separated include parameter listing any combination of the six "
            "available data types: weather, pit_stops, incidents, positions, drs, track_status. "
            "The session is loaded once and shared across all extractors, making "
            "this far more efficient than calling each dedicated endpoint separately. Partial "
            "results are fully supported — if one data type fails the others are still returned, "
            "and the top-level can_proceed flag reflects whether at least one type succeeded."
        ),
        parameters=[
            OpenApiParameter(name="session", location=OpenApiParameter.QUERY, required=False, type=str, description="R, Q, FP1, FP2, FP3"),
            OpenApiParameter(name="include", location=OpenApiParameter.QUERY, required=True, type=str, description="Comma-separated: weather,pit_stops,incidents,positions,drs,track_status"),
            OpenApiParameter(name="driver", location=OpenApiParameter.QUERY, required=False, type=str, description="Optional driver filter"),
        ],
        responses={
            200: inline_serializer(
                name="UnifiedFullSessionResponse",
                fields={
                    "meta": drf_serializers.DictField(),
                    "data": drf_serializers.DictField(),
                },
            ),
            400: OpenApiResponse(description="Invalid include/session parameters"),
        },
        examples=[
            OpenApiExample(
                "Unified Partial Support",
                value={
                    "meta": {
                        "year": 2016,
                        "round": 3,
                        "session": "R",
                        "requested_types": ["weather", "incidents", "positions"],
                        "cache_stats": {"cached_sessions": 1, "hits": 0, "misses": 1, "hit_rate_percent": 0.0},
                        "can_proceed": True,
                        "available_data": ["positions"],
                        "unavailable_data": ["weather", "incidents"],
                        "message": "Partial support for 2016 Round 3 (R). Proceeding with: ['positions']. Unavailable: ['weather', 'incidents'].",
                        "warnings": [
                            "Partial support for 2016 Round 3 (R). Proceeding with: ['positions']. Unavailable: ['weather', 'incidents'].",
                            "weather: No weather data available for this session",
                            "incidents: No messages data available for this session",
                        ],
                    },
                    "data": {
                        "positions": {"meta": {"row_count": 24}, "filters_applied": {"driver": None, "limit": None}, "data": []},
                        "weather": {"error": "No weather data available for this session", "status": "failed"},
                        "incidents": {"error": "No messages data available for this session", "status": "failed"},
                    },
                },
                response_only=True,
                status_codes=["200"],
            ),
        ],
    )

    def get(self, request, year, round_number):
        request_start = time.time()
        logger.info("event=api_request endpoint=unified_full_session year=%s round=%s", year, round_number)
        try:
            session_name = request.query_params.get("session", "R").upper()
            include_param = request.query_params.get("include", "").strip()
            driver = request.query_params.get("driver")

            if not include_param:
                return Response(
                    {"error": "include parameter required (e.g., ?include=weather,pit_stops,incidents)"},
                    status=400,
                )

            # Parse include list
            include_types = [t.strip() for t in include_param.split(",") if t.strip()]
            invalid_types = [t for t in include_types if t not in EXTRACTORS_MAP]
            if invalid_types:
                return Response(
                    {
                        "error": f"Unknown data types: {invalid_types}. Valid: {list(EXTRACTORS_MAP.keys())}"
                    },
                    status=400,
                )

            # Build base metadata payload
            base_meta = {
                "year": year,
                "round": round_number,
                "session": session_name,
                "requested_types": include_types,
                "cache_stats": {"cached_sessions": 0, "hits": 0, "misses": 0, "hit_rate_percent": 0.0}, # Mocked or removed
                "can_proceed": False,
                "available_data": [],
                "unavailable_data": [],
                "message": None,
                "warnings": [],
            }

            task_keys = []
            for data_type in include_types:
                task_key = f"populate_{data_type}:{int(year)}:{int(round_number)}:{session_name}"
                if data_type == "weather":
                    TaskManager.enqueue_if_needed(task_key, populate_weather, year=int(year), round_number=int(round_number), session_type=session_name)
                elif data_type == "pit_stops":
                    TaskManager.enqueue_if_needed(task_key, populate_pit_stops, year=int(year), round_number=int(round_number), session_type=session_name)
                elif data_type == "incidents":
                    TaskManager.enqueue_if_needed(task_key, populate_incidents, year=int(year), round_number=int(round_number), session_type=session_name)
                elif data_type == "positions":
                    TaskManager.enqueue_if_needed(task_key, populate_positions, year=int(year), round_number=int(round_number), session_type=session_name)
                elif data_type == "drs":
                    TaskManager.enqueue_if_needed(task_key, populate_drs, year=int(year), round_number=int(round_number), session_type=session_name)
                elif data_type == "track_status":
                    TaskManager.enqueue_if_needed(task_key, populate_track_status, year=int(year), round_number=int(round_number), session_type=session_name)
                task_keys.append(task_key)

            return stream_unified_full_session_json(task_keys, include_types, base_meta)

        except ValueError as exc:
            return Response({"error": str(exc)}, status=400)
        except Exception as exc:
            return Response({"error": str(exc)}, status=500)


class UnifiedWeatherAPIView(APIView):
    """Extract weather data only."""

    @extend_schema(
        summary="Get session weather data",
        description=(
            "Returns time-series weather snapshots captured during the session: track temperature, "
            "air temperature, humidity, wind speed, wind direction, and a rainfall flag. Pass "
            "per_lap=true to align each snapshot to the closest lap number instead of raw "
            "timestamps. Useful for correlating tyre degradation or lap-time changes with "
            "ambient conditions."
        ),
        parameters=[
            OpenApiParameter(name="session", location=OpenApiParameter.QUERY, required=False, type=str, description="R, Q, FP1, FP2, FP3. Default: R"),
            OpenApiParameter(name="per_lap", location=OpenApiParameter.QUERY, required=False, type=bool, description="Align snapshots to lap numbers"),
        ],
        responses={200: WeatherResponseSerializer},
    )
    def get(self, request, year, round_number):
        request_start = time.time()
        logger.info("event=api_request endpoint=unified_weather year=%s round=%s", year, round_number)
        try:
            session_name = request.query_params.get("session", "R").upper()
            include_per_lap = request.query_params.get("per_lap", "false").lower() == "true"

            cache_key = f"weather:{year}:{round_number}:{session_name}"
            if include_per_lap:
                cache_key += ":per_lap"

            task_key = f"populate_weather:{year}:{round_number}:{session_name}"
            if include_per_lap:
                task_key += ":per_lap"

            def db_fetch_fn():
                # Only return DB hit if not per_lap (since DB only stores default extraction)
                if include_per_lap:
                    return None
                from ..models import WeatherData
                record = WeatherData.objects.filter(
                    year=int(year), round_number=int(round_number), session=session_name
                ).first()
                if record and "data" in record.payload:
                    # Reconstruct the response payload shape
                    return {
                        "meta": {
                            "year": year, "round": round_number, "session": session_name,
                            "row_count": len(record.payload["data"]), "can_proceed": True,
                        },
                        "filters_applied": {},
                        "data": record.payload["data"],
                    }
                return None

            return nonblocking.handle_data_request(
                cache_key=cache_key,
                db_fetch_fn=db_fetch_fn,
                task_fn=populate_weather,
                task_key=task_key,
                task_args=(year, round_number),
                task_kwargs={"session_type": session_name, "include_per_lap": include_per_lap},
                cache_ttl=None
            )
        except ValueError as exc:
            return Response({"error": str(exc)}, status=400)
        except Exception as exc:
            return Response({"error": str(exc)}, status=500)


class UnifiedPitStopsAPIView(APIView):
    """Extract pit stop strategy data only."""

    @extend_schema(
        summary="Get pit stop events",
        description=(
            "Returns one row per pit stop: driver, stop number, lap in, lap out, stop duration "
            "in seconds, the compound fitted before and after the stop, and an estimated time "
            "gain/loss. Primarily meaningful for Race sessions. Use the driver filter to isolate "
            "one team's strategy."
        ),
        parameters=[
            OpenApiParameter(name="session", location=OpenApiParameter.QUERY, required=False, type=str, description="R, Q, FP1, FP2, FP3. Default: R"),
            OpenApiParameter(name="limit", location=OpenApiParameter.QUERY, required=False, type=int, description="Maximum rows to return"),
        ],
        responses={200: PitStopResponseSerializer},
    )
    def get(self, request, year, round_number):
        request_start = time.time()
        logger.info("event=api_request endpoint=unified_pit_stops year=%s round=%s", year, round_number)
        try:
            session_name = request.query_params.get("session", "R").upper()
            limit_param = request.query_params.get("limit")

            limit = None
            if limit_param:
                try:
                    limit = int(limit_param)
                except ValueError:
                    return Response({"error": "limit must be an integer"}, status=400)

            cache_key = f"pit_stops:{year}:{round_number}:{session_name}"
            if limit:
                cache_key += f":limit:{limit}"

            task_key = f"populate_pit_stops:{year}:{round_number}:{session_name}"
            if limit:
                task_key += f":limit:{limit}"

            def db_fetch_fn():
                # DB only stores the full unstructured data, bypass DB cache if limit requested
                if limit is not None:
                    return None
                from ..models import PitStopData
                record = PitStopData.objects.filter(
                    year=int(year), round_number=int(round_number), session=session_name
                ).first()
                if record and "data" in record.payload:
                    return {
                        "meta": {
                            "year": year, "round": round_number, "session": session_name,
                            "row_count": len(record.payload["data"]), "can_proceed": True,
                        },
                        "filters_applied": {"driver": None, "limit": None},
                        "data": record.payload["data"],
                    }
                return None

            return nonblocking.handle_data_request(
                cache_key=cache_key,
                db_fetch_fn=db_fetch_fn,
                task_fn=populate_pit_stops,
                task_key=task_key,
                task_args=(year, round_number),
                task_kwargs={"session_type": session_name, "limit": limit},
                cache_ttl=None
            )
        except ValueError as exc:
            return Response({"error": str(exc)}, status=400)
        except Exception as exc:
            return Response({"error": str(exc)}, status=500)


class UnifiedIncidentsAPIView(APIView):
    """Extract incidents and messages."""

    @extend_schema(
        summary="Get race-control incidents",
        description=(
            "Parses the session race-control messages feed and returns structured incident rows: "
            "lap number, message type (e.g. SAFETY_CAR, COLLISION, PENALTY), drivers involved, "
            "the raw message text, a timestamp in seconds, and an impact classification. "
            "Race-control messages are only available for seasons where FastF1 carries this "
            "data stream; older seasons return can_proceed=false."
        ),
        parameters=[
            OpenApiParameter(name="session", location=OpenApiParameter.QUERY, required=False, type=str, description="R, Q, FP1, FP2, FP3. Default: R"),
            OpenApiParameter(name="limit", location=OpenApiParameter.QUERY, required=False, type=int, description="Maximum rows to return"),
            OpenApiParameter(name="radio", location=OpenApiParameter.QUERY, required=False, type=bool, description="Include team radio messages"),
        ],
        responses={200: IncidentResponseSerializer},
    )
    def get(self, request, year, round_number):
        request_start = time.time()
        logger.info("event=api_request endpoint=unified_incidents year=%s round=%s", year, round_number)
        try:
            session_name = request.query_params.get("session", "R").upper()
            include_radio = request.query_params.get("radio", "false").lower() == "true"
            limit_param = request.query_params.get("limit")

            limit = None
            if limit_param:
                try:
                    limit = int(limit_param)
                except ValueError:
                    return Response({"error": "limit must be an integer"}, status=400)

            cache_key = f"incidents:{year}:{round_number}:{session_name}"
            if include_radio:
                cache_key += ":radio"
            if limit:
                cache_key += f":limit:{limit}"

            task_key = f"populate_incidents:{year}:{round_number}:{session_name}"
            if include_radio:
                task_key += ":radio"
            if limit:
                task_key += f":limit:{limit}"

            def db_fetch_fn():
                # DB only stores the full unstructured data without limit. Radio might be excluded in default.
                if limit is not None or include_radio:
                    return None
                from ..models import IncidentData
                record = IncidentData.objects.filter(
                    year=int(year), round_number=int(round_number), session=session_name
                ).first()
                if record and "data" in record.payload:
                    return {
                        "meta": {
                            "year": year, "round": round_number, "session": session_name,
                            "row_count": len(record.payload["data"]), "can_proceed": True,
                        },
                        "filters_applied": {"driver": None, "limit": None},
                        "data": record.payload["data"],
                    }
                return None

            return nonblocking.handle_data_request(
                cache_key=cache_key,
                db_fetch_fn=db_fetch_fn,
                task_fn=populate_incidents,
                task_key=task_key,
                task_args=(year, round_number),
                task_kwargs={"session_type": session_name, "limit": limit, "include_radio": include_radio},
                cache_ttl=None
            )
        except ValueError as exc:
            return Response({"error": str(exc)}, status=400)
        except Exception as exc:
            return Response({"error": str(exc)}, status=500)


class UnifiedPositionsAPIView(APIView):
    """Extract position and gap data."""

    @extend_schema(
        summary="Get lap-by-lap position changes",
        description=(
            "Returns a row per driver per lap showing on-track position, the change in position "
            "versus the previous lap, gap to the leader, and gap to the car directly ahead. "
            "Each row also includes stint, track status, lap time in seconds, and fastest-lap "
            "flags (overall and per-lap-number). Particularly useful for animated race-progression "
            "charts and race-pace analysis."
        ),
        parameters=[
            OpenApiParameter(name="session", location=OpenApiParameter.QUERY, required=False, type=str, description="R, Q, FP1, FP2, FP3. Default: R"),
            OpenApiParameter(name="sample_interval", location=OpenApiParameter.QUERY, required=False, type=int, description="Sample every N laps (default 5)"),
        ],
        responses={200: PositionResponseSerializer},
    )
    def get(self, request, year, round_number):
        request_start = time.time()
        logger.info("event=api_request endpoint=unified_positions year=%s round=%s", year, round_number)
        try:
            session_name = request.query_params.get("session", "R").upper()
            sample_interval = request.query_params.get("sample_interval", "5")

            try:
                sample_interval = int(sample_interval)
            except ValueError:
                return Response({"error": "sample_interval must be an integer"}, status=400)

            cache_key = f"positions:{year}:{round_number}:{session_name}:interval:{sample_interval}"
            task_key = f"populate_positions:{year}:{round_number}:{session_name}:interval:{sample_interval}"

            def db_fetch_fn():
                # DB stores default (interval=5) or unstructured. Bypass DB cache if interval != 5.
                if sample_interval != 5:
                    return None
                from ..models import PositionData
                record = PositionData.objects.filter(
                    year=int(year), round_number=int(round_number), session=session_name
                ).first()
                if record and "data" in record.payload:
                    return {
                        "meta": {
                            "year": year, "round": round_number, "session": session_name,
                            "row_count": len(record.payload["data"]), "can_proceed": True,
                        },
                        "filters_applied": {"limit": None, "driver": None},
                        "data": record.payload["data"],
                    }
                return None

            return nonblocking.handle_data_request(
                cache_key=cache_key,
                db_fetch_fn=db_fetch_fn,
                task_fn=populate_positions,
                task_key=task_key,
                task_args=(year, round_number),
                task_kwargs={"session_type": session_name, "sample_interval": sample_interval},
                cache_ttl=None
            )
        except ValueError as exc:
            return Response({"error": str(exc)}, status=400)
        except Exception as exc:
            return Response({"error": str(exc)}, status=500)


class UnifiedDRSAPIView(APIView):
    """Extract DRS activation data."""

    @extend_schema(
        summary="Get DRS activation data",
        description=(
            "Returns per-driver per-lap DRS state: whether DRS was available on that lap "
            "(gap to the car ahead <=1 second at the detection point), whether it was actually "
            "activated, the gap behind in seconds, and a performance delta in milliseconds. "
            "Useful for visualising how much DRS influenced overtaking opportunities."
        ),
        parameters=[
            OpenApiParameter(name="session", location=OpenApiParameter.QUERY, required=False, type=str, description="R, Q, FP1, FP2, FP3. Default: R"),
            OpenApiParameter(name="driver", location=OpenApiParameter.QUERY, required=False, type=str, description="3-letter driver code filter"),
        ],
        responses={200: DRSResponseSerializer},
    )
    def get(self, request, year, round_number):
        request_start = time.time()
        logger.info("event=api_request endpoint=unified_drs year=%s round=%s", year, round_number)
        try:
            session_name = request.query_params.get("session", "R").upper()
            driver = request.query_params.get("driver")

            cache_key = f"drs:{year}:{round_number}:{session_name}"
            if driver:
                cache_key += f":driver:{driver}"

            task_key = f"populate_drs:{year}:{round_number}:{session_name}"
            if driver:
                task_key += f":driver:{driver}"

            def db_fetch_fn():
                # DB stores full un-filtered data. Bypass if driver filter applied for simplicity, 
                # or we could filter it in memory, but bypass is safer for now.
                if driver:
                    return None
                from ..models import DRSData
                record = DRSData.objects.filter(
                    year=int(year), round_number=int(round_number), session=session_name
                ).first()
                if record and "data" in record.payload:
                    return {
                        "meta": {
                            "year": year, "round": round_number, "session": session_name,
                            "row_count": len(record.payload["data"]), "can_proceed": True,
                        },
                        "filters_applied": {"driver": None, "limit": None},
                        "data": record.payload["data"],
                    }
                return None

            return nonblocking.handle_data_request(
                cache_key=cache_key,
                db_fetch_fn=db_fetch_fn,
                task_fn=populate_drs,
                task_key=task_key,
                task_args=(year, round_number),
                task_kwargs={"session_type": session_name, "driver": driver},
                cache_ttl=None
            )
        except ValueError as exc:
            return Response({"error": str(exc)}, status=400)
        except Exception as exc:
            return Response({"error": str(exc)}, status=500)


class UnifiedTrackStatusAPIView(APIView):
    """Extract track status timeline."""

    @extend_schema(
        summary="Get track status timeline",
        description=(
            "Returns the sequence of official track-status changes broadcast during the session. "
            "Each row includes the lap number, status code (GREEN, YELLOW, RED, SAFETY_CAR, VSC), "
            "how many laps that status persisted, the cause if available, and the affected track "
            "zone. Essential context for understanding lap-time anomalies caused by caution periods."
        ),
        parameters=[
            OpenApiParameter(name="session", location=OpenApiParameter.QUERY, required=False, type=str, description="R, Q, FP1, FP2, FP3. Default: R"),
        ],
        responses={200: TrackStatusResponseSerializer},
    )
    def get(self, request, year, round_number):
        try:
            session_name = request.query_params.get("session", "R").upper()

            cache_key = f"track_status:{year}:{round_number}:{session_name}"
            task_key = f"populate_track_status:{year}:{round_number}:{session_name}"

            def db_fetch_fn():
                from ..models import TrackStatusData
                record = TrackStatusData.objects.filter(
                    year=int(year), round_number=int(round_number), session=session_name
                ).first()
                if record and "data" in record.payload:
                    return {
                        "meta": {
                            "year": year, "round": round_number, "session": session_name,
                            "row_count": len(record.payload["data"]), "can_proceed": True,
                        },
                        "filters_applied": {"driver": None, "limit": None},
                        "data": record.payload["data"],
                    }
                return None

            return nonblocking.handle_data_request(
                cache_key=cache_key,
                db_fetch_fn=db_fetch_fn,
                task_fn=populate_track_status,
                task_key=task_key,
                task_args=(year, round_number),
                task_kwargs={"session_type": session_name},
                cache_ttl=None
            )
        except ValueError as exc:
            return Response({"error": str(exc)}, status=400)
        except Exception as exc:
            return Response({"error": str(exc)}, status=500)
