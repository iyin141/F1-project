"""
Driver views — thin HTTP layer.
Handles parsing request parameters, delegating to services, and wrapping responses.
# TODO: MOVE -> backend/api/sync_functions  # sync endpoints will call extracted sync functions
"""
import logging
from rest_framework.response import Response
from rest_framework.views import APIView
from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiExample

from api.common.readiness import build_readiness
from api.common.response import build_error_payload
from api.queue.manager import TaskManager
from api.common.utils import is_current_year

from api.drivers.serializers import (
    DriverStandingsResponseSerializer,
    DriverCareerResponseSerializer,
    DriverSeasonResponseSerializer,
    DriverStandingSerializer,
)
from api.services.streaming import stream_task_result_json
from api.tasks import populate_standings
from api.drivers.repository import get_persisted_driver_standings

logger = logging.getLogger(__name__)

def _build_empty_career_response(driver_code, can_proceed=False, message=None, driver_name=None, nationality=None):
    """Build empty career response with readiness."""
    return {
        "driver_code": driver_code,
        "driver_name": driver_name,
        "nationality": nationality,
        "career": [],
        "career_totals": {
            "total_wins": 0,
            "total_podiums": 0,
            "championships": 0,
        },
        "readiness": build_readiness(
            can_proceed,
            [],
            [] if can_proceed else ["career"],
            message,
            [] if can_proceed else ([message] if message else []),
        ),
    }

def _build_empty_season_response(driver_code, year, can_proceed=False, message=None, driver_name=None):
    """Build empty season response with readiness."""
    return {
        "driver_code": driver_code,
        "driver_name": driver_name,
        "constructor": None,
        "final_position": None,
        "final_points": None,
        "year": year,
        "total_races": 0,
        "sprint_weekends": 0,
        "races": [],
        "readiness": build_readiness(
            can_proceed,
            [],
            [] if can_proceed else ["season_breakdown"],
            message,
            [] if can_proceed else ([message] if message else []),
        ),
    }

class DriverStandingsAPIView(APIView):
    @extend_schema(
        summary="Get driver championship standings",
        description=(
            "Returns the current or historical F1 driver standings for a given year. "
            "Data is served from a persisted PostgreSQL cache if available. If the year "
            "is not found in the DB, the service fetches it live from Ergast/Jolpica "
            "and triggers an async Celery task (`populate_standings`) to persist it "
            "for future requests."
        ),
        responses={200: DriverStandingsResponseSerializer},
        examples=[
            OpenApiExample(
                "Driver Standings Example",
                value={
                    "year": 2021,
                    "drivers": [
                        {
                            "position": 1,
                            "driver_name": "Max Verstappen",
                            "points": 395.5,
                            "wins": 10,
                            "constructor": "Red Bull",
                        }
                    ],
                    "readiness": {
                        "can_proceed": True,
                        "available_data": ["driver_standings_api"],
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
            persisted = get_persisted_driver_standings(year)
            if persisted is not None:
                serializer = DriverStandingSerializer(persisted, many=True)
                return Response(
                    {
                        "year": year,
                        "drivers": serializer.data,
                        "readiness": build_readiness(True, ["driver_standings_persisted"], []),
                    }
                )

            task_key = f"standings:{year}"
            TaskManager.enqueue_if_needed(
                task_key=task_key,
                task_fn=populate_standings,
                year=int(year),
            )
            return stream_task_result_json(task_key)
        except Exception as exc:
            logger.exception("Driver standings error")
            return Response(build_error_payload("drivers.standings", str(exc), "DRIVER_STANDINGS_ERROR"), status=500)

class DriverCareerAPIView(APIView):
    """
    GET /api/drivers/{driver_code}/career/

    Returns full career summary for a driver across all seasons.
    DB-first: reads from persisted DriverSeasonSummary.
    Falls back to Jolpica for seasons not yet in DB.
    """

    @extend_schema(
        summary="Get driver career history",
        description=(
            "Returns a complete career summary for a driver: all seasons with position, points, "
            "wins, podiums, poles, fastest laps, and DNFs. The service checks persisted "
            "DriverSeasonSummary rows first; for any missing seasons it queries Jolpica "
            "driverStandings endpoint. Returns empty career with can_proceed=false when "
            "neither source has data for this driver code."
        ),
        parameters=[
            OpenApiParameter(
                name="driver_code",
                location=OpenApiParameter.PATH,
                required=True,
                type=str,
                description="3-letter driver code (e.g. VER, HAM, LEC)",
            ),
        ],
        responses={200: DriverCareerResponseSerializer},
    )
    def get(self, request, driver_code):
        """Fetch driver career summary."""
        try:
            if not driver_code:
                message = f"Invalid driver code: {driver_code}. Must be provided."
                logger.info(f"Invalid driver code: {driver_code}")
                return Response(_build_empty_career_response(driver_code, False, message), status=200)

            original_identifier = driver_code
            if original_identifier.isalpha() and len(original_identifier) != 3:
                from api.drivers.repository import resolve_driver_metadata
                metadata = resolve_driver_metadata(original_identifier)
                resolved = metadata.get("driver_id") if metadata else None
                if not resolved:
                    from api.drivers.jolpica_client import get_season_driver_map
                    from django.utils import timezone
                    try:
                        season_map_check = get_season_driver_map(timezone.now().year)
                        ident = original_identifier.strip().lower()
                        found = any(ident in (v.get('name') or '').lower().split() or ident == k.lower() for k, v in season_map_check.items())
                    except Exception:
                        found = False

                    if not found:
                        message = f"Invalid driver code: {original_identifier}. Must be a 3-letter FIA code or a Jolpica driver id."
                        logger.info(f"Invalid driver code: {original_identifier}")
                        return Response(_build_empty_career_response(driver_code, False, message), status=200)

            from api.drivers.repository import get_persisted_driver_career
            persisted = get_persisted_driver_career(original_identifier)
            if persisted is not None:
                return Response({
                    **persisted,
                    "readiness": build_readiness(True, ["career"], [], None, []),
                })

            from api.tasks import populate_driver_career
            task_key_code = original_identifier.upper() if original_identifier.isalpha() and len(original_identifier) == 3 else original_identifier
            task_key = f"driver_career:{task_key_code}"
            TaskManager.enqueue_if_needed(
                task_key=task_key,
                task_fn=populate_driver_career,
                driver_code=original_identifier,
            )
            return stream_task_result_json(task_key)

        except ValueError as exc:
            logger.warning(f"ValueError fetching career for {driver_code}: {exc}")
            message = str(exc)
            return Response(_build_empty_career_response(driver_code, False, message), status=200)
        except Exception as exc:
            logger.exception(f"Unexpected error fetching career for {driver_code}: {exc}")
            message = f"Internal error: {str(exc)}"
            return Response(_build_empty_career_response(driver_code, False, message), status=500)


class DriverSeasonAPIView(APIView):
    """
    GET /api/drivers/{driver_code}/{year}/

    Returns race-by-race breakdown for one driver across a full season.
    DB-first for completed rounds.
    FastF1 fallback for rounds not yet persisted.
    """

    @extend_schema(
        summary="Get driver season breakdown",
        description=(
            "Returns race-by-race results for one driver in a specific season: grid position, "
            "finish position, points, fastest lap flag, and status. The service queries "
            "persisted RaceResult rows first. Returns empty races with can_proceed=false when "
            "the season has no schedule or the driver did not compete."
        ),
        parameters=[
            OpenApiParameter(
                name="driver_code",
                location=OpenApiParameter.PATH,
                required=True,
                type=str,
                description="3-letter driver code (e.g. VER, HAM, LEC)",
            ),
            OpenApiParameter(
                name="year",
                location=OpenApiParameter.PATH,
                required=True,
                type=int,
                description="Season year (1950 onwards)",
            ),
        ],
        responses={200: DriverSeasonResponseSerializer},
    )
    def get(self, request, driver_code, year):
        """Fetch driver season breakdown."""
        try:
            if not driver_code:
                message = f"Invalid driver code: {driver_code}. Must be provided."
                logger.info(f"Invalid driver code: {driver_code}")
                return Response(_build_empty_season_response(driver_code, year, False, message), status=200)

            if not isinstance(year, int) or year < 1950 or year > 2100:
                message = f"Invalid year: {year}. Must be between 1950 and 2100."
                logger.info(f"Invalid year: {year}")
                return Response(_build_empty_season_response(driver_code, year, False, message), status=200)

            original_identifier = driver_code
            if original_identifier.isalpha() and len(original_identifier) != 3:
                from api.drivers.repository import resolve_driver_metadata
                metadata = resolve_driver_metadata(original_identifier, year)
                resolved = metadata.get("driver_id") if metadata else None
                if not resolved:
                    from api.drivers.jolpica_client import get_season_driver_map
                    try:
                        season_map_check = get_season_driver_map(year)
                        ident = original_identifier.strip().lower()
                        found = any(ident in (v.get('name') or '').lower().split() or ident == k.lower() for k, v in season_map_check.items())
                    except Exception:
                        found = False

                    if not found:
                        message = f"Invalid driver code: {original_identifier}. Must be a 3-letter FIA code or a Jolpica driver id."
                        logger.info(f"Invalid driver code: {original_identifier}")
                        return Response(_build_empty_season_response(driver_code, year, False, message), status=200)

            from api.drivers.repository import get_persisted_driver_season_breakdown
            persisted = get_persisted_driver_season_breakdown(original_identifier, year)
            if persisted is not None:
                return Response({
                    **persisted,
                    "readiness": build_readiness(True, ["season_breakdown"], [], None, []),
                })

            from api.tasks import populate_driver_season
            task_key_code = original_identifier.upper() if original_identifier.isalpha() and len(original_identifier) == 3 else original_identifier
            task_key = f"driver_season:{task_key_code}:{year}"
            TaskManager.enqueue_if_needed(
                task_key=task_key,
                task_fn=populate_driver_season,
                driver_code=original_identifier,
                year=int(year),
            )
            return stream_task_result_json(task_key)

        except ValueError as exc:
            logger.warning(f"ValueError fetching season for {driver_code}/{year}: {exc}")
            message = str(exc)
            return Response(_build_empty_season_response(driver_code, year, False, message), status=200)
        except Exception as exc:
            logger.exception(f"Unexpected error fetching season for {driver_code}/{year}: {exc}")
            message = f"Internal error: {str(exc)}"
            return Response(_build_empty_season_response(driver_code, year, False, message), status=500)


# =========================================================================
# Phase 8: Driver Search & Sync API Views
# =========================================================================

class SearchDriversAPIView(APIView):
    """
    GET /api/drivers/search/?year=<year>

    Returns list of drivers active in a given year.
    This endpoint is self-populating — it syncs drivers from Jolpica before returning.
    """

    @extend_schema(
        summary="List drivers for a season",
        description="Returns all drivers who competed in a given F1 season. Automatically syncs with Jolpica if DB is empty.",
        parameters=[
            OpenApiParameter(
                name="year",
                location=OpenApiParameter.QUERY,
                required=True,
                type=int,
                description="F1 season year (e.g., 2025)",
            ),
        ],
        responses={200: "DriverListResponseSerializer"},
    )
    def get(self, request):
        try:
            year_param = request.query_params.get("year")
            
            if not year_param:
                return Response(
                    {"error": "Missing required parameter", "message": "year query parameter is required", "drivers": [], "count": 0},
                    status=400,
                )

            try:
                year = int(year_param)
            except (ValueError, TypeError):
                return Response(
                    {"error": "Invalid year", "message": "year must be an integer", "drivers": [], "count": 0},
                    status=400,
                )

            # Query DB for drivers (not using .values() — return full objects)
            from api.models.drivers import F1Driver
            drivers = F1Driver.objects.filter(seasons__contains=[year]).order_by('family_name', 'given_name')
            
            if drivers.exists():
                results = [self._serialize(d) for d in drivers]
                return Response({"year": year, "count": len(results), "drivers": results}, status=200)

            # Enqueue sync task and return stream if empty
            import uuid
            from api.tasks import sync_drivers_task
            unique_id = uuid.uuid4().hex[:8]
            task_key = f"sync_drivers:{year}:{unique_id}"
            TaskManager.enqueue_if_needed(task_key, sync_drivers_task, year=year)
            return stream_task_result_json(task_key)

        except Exception as exc:
            logger.exception(f"Error listing drivers for year={year_param}: {exc}")
            return Response(
                {"error": "Request failed", "message": str(exc), "drivers": [], "count": 0},
                status=500,
            )

    def _serialize(self, driver_obj) -> dict:
        return {
            "driver_id": driver_obj.driver_id or None,
            "driver_code": driver_obj.code or None,
            "driver_name": f"{driver_obj.given_name or ''} {driver_obj.family_name or ''}".strip(),
            "nationality": driver_obj.nationality or None,
            "number": driver_obj.number or None,
            "seasons": driver_obj.seasons or [],
        }


class SearchDriverByNameAPIView(APIView):
    """
    GET /api/drivers/search-by-name/?q=<query>&year=<year>

    Search drivers by partial name or code. Async via PubSub.
    """

    @extend_schema(
        summary="Search drivers by name or code",
        description=(
            "Search drivers by partial name (given or family name) or driver code. "
            "Searches DB only — does not call Jolpica. If DB is empty, returns 503 with hint to call /api/drivers/search/?year=<year> first. "
            "Minimum query length is 2 characters. "
            "Optional year filter narrows results to drivers who competed in that season."
        ),
        parameters=[
            OpenApiParameter(name="q", location=OpenApiParameter.QUERY, required=True, type=str, description="Search query"),
            OpenApiParameter(name="year", location=OpenApiParameter.QUERY, required=False, type=int, description="Optional year filter"),
        ],
        responses={200: "DriverSearchByNameResponseSerializer", 503: "DriverSearchByNameResponseSerializer"},
    )
    def get(self, request):
        try:
            query = request.query_params.get("q", "").strip()
            year_param = request.query_params.get("year")

            if len(query) < 2:
                return Response(
                    {"error": "Query too short", "message": "Search query must be at least 2 characters", "results": [], "count": 0},
                    status=400,
                )

            try:
                year = int(year_param) if year_param else None
            except (ValueError, TypeError):
                year = None

            # Enqueue search task
            import uuid
            from api.tasks import search_drivers_by_name_task
            unique_id = uuid.uuid4().hex[:8]
            task_key = f"search_drivers_by_name:{query}:{year or 'all'}:{unique_id}"
            TaskManager.enqueue_if_needed(task_key, search_drivers_by_name_task, query=query, year=year)
            return stream_task_result_json(task_key)

        except Exception as exc:
            logger.exception(f"Error searching drivers for query={query}: {exc}")
            return Response(
                {"error": "Search failed", "message": str(exc), "results": [], "count": 0},
                status=500,
            )


class SyncSingleYearAPIView(APIView):
    """
    POST /api/drivers/sync/<int:year>/

    Sync drivers for a single season from Jolpica into F1Driver model.
    Can be run on-demand or as a one-time setup step.
    
    Returns: task_id (202) or sync result (200)
    """

    @extend_schema(
        summary="Sync drivers for a single season",
        description=(
            "Synchronize drivers for a specific season from Jolpica into the F1Driver table. "
            "If already queued, returns existing task ID. Returns 202 (Accepted) with task_id "
            "if queued, or 200 (OK) with sync result if completed synchronously."
        ),
        parameters=[
            OpenApiParameter(
                name="year",
                location=OpenApiParameter.PATH,
                required=True,
                type=int,
                description="Season year (e.g., 2025)",
            ),
        ],
        responses={
            200: "DriverSyncResponseSerializer",
            202: "DriverSyncResponseSerializer",
        },
    )
    def post(self, request, year):
        try:
            year = int(year)

            if year < 1950 or year > 2100:
                return Response(
                    {
                        "error": "Invalid year",
                        "message": f"Year must be between 1950 and 2100, got {year}",
                        "task_id": None,
                        "status": "failed",
                    },
                    status=400,
                )

            task_key = f"sync_drivers:{year}"

            # Check if task already queued
            existing_task = TaskManager.get_by_key(task_key)
            if existing_task:
                logger.info(f"Sync task already queued for {year}: {existing_task.task_id}")
                return Response(
                    {
                        "year": year,
                        "message": f"Sync already queued for {year}",
                        "task_id": existing_task.task_id,
                        "status": "queued",
                    },
                    status=202,
                )

            # Enqueue sync task
            from api.tasks import sync_drivers_task
            task_result = TaskManager.enqueue_if_needed(
                task_key,
                sync_drivers_task,
                year=year,
            )

            logger.info(f"Enqueued sync task for {year}: {task_result.id if task_result else 'none'}")

            return Response(
                {
                    "year": year,
                    "message": f"Sync task enqueued for {year}",
                    "task_id": task_result.id if task_result else None,
                    "status": "queued",
                },
                status=202,
            )

        except ValueError as exc:
            logger.warning(f"ValueError syncing {year}: {exc}")
            return Response(
                {
                    "error": "Invalid input",
                    "message": str(exc),
                    "task_id": None,
                    "status": "failed",
                },
                status=400,
            )

        except Exception as exc:
            logger.exception(f"Exception syncing {year}: {exc}")
            return Response(
                {
                    "error": "Sync failed",
                    "message": str(exc),
                    "task_id": None,
                    "status": "failed",
                },
                status=500,
            )
