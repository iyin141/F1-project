"""
Driver views — thin HTTP layer.
Handles parsing request parameters, delegating to services, and wrapping responses.
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
import api.views as api_views
from api.drivers.services.career import get_driver_career
from api.drivers.services.season import get_driver_season

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
            standings = api_views.get_driver_standings(year)
            if isinstance(standings, dict):
                rows = standings.get("data", [])
                readiness = standings.get("meta", {}).get("readiness")
            else:
                rows = standings
                readiness = None

            serializer = DriverStandingSerializer(rows, many=True)
            return Response(
                {
                    "year": year,
                    "drivers": serializer.data,
                    "readiness": readiness
                    or build_readiness(
                        bool(rows),
                        ["driver_standings_api"] if rows else [],
                        [] if rows else ["driver_standings_api"],
                        None if rows else f"No driver standings data returned for {year}.",
                        [] if rows else [f"No driver standings data returned for {year}."]
                    ),
                }
            )
        except Exception as exc:
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
            # Validate simple 3-letter driver codes (reject too-short/too-long alphabetical codes)
            if original_identifier.isalpha() and len(original_identifier) != 3:
                message = f"Invalid driver code: {original_identifier}. Must be a 3-letter FIA code or a Jolpica driver id."
                logger.info(f"Invalid driver code: {original_identifier}")
                return Response(_build_empty_career_response(driver_code, False, message), status=200)

            # Use legacy-compatible service hook (allows tests to patch api.driver_views.DriverCareerService)
            import api.driver_views as _compat
            service = _compat.DriverCareerService()
            # For 3-letter alpha codes, use uppercase when calling into the service
            service_identifier = original_identifier.upper() if original_identifier.isalpha() and len(original_identifier) == 3 else original_identifier
            career_data = service.get_driver_career(service_identifier)

            has_data = bool(career_data.get("career"))

            if not has_data:
                message = career_data.get("message") or "No career data available for this driver"
                logger.info(f"No career data found for {driver_code}")
                return Response(
                    _build_empty_career_response(
                        driver_code,
                        False,
                        message,
                        driver_name=career_data.get("driver_name"),
                        nationality=career_data.get("nationality"),
                    ),
                    status=200,
                )

            serializer = DriverCareerResponseSerializer(career_data)

            # Enqueue background persistence
            from api.tasks import populate_driver_career
            task_key_code = original_identifier.upper() if len(original_identifier) == 3 else original_identifier
            TaskManager.enqueue_if_needed(
                task_key=f"driver_career:{task_key_code}",
                task_fn=populate_driver_career,
                driver_code=original_identifier,
            )

            return Response(
                {
                    **serializer.data,
                    "readiness": build_readiness(True, ["career"], [], None, []),
                }
            )

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
            # Validate simple 3-letter driver codes (reject too-short/too-long alphabetical codes)
            if original_identifier.isalpha() and len(original_identifier) != 3:
                message = f"Invalid driver code: {original_identifier}. Must be a 3-letter FIA code or a Jolpica driver id."
                logger.info(f"Invalid driver code: {original_identifier}")
                return Response(_build_empty_season_response(driver_code, year, False, message), status=200)
            # Use legacy-compatible service hook (allows tests to patch api.driver_views.DriverCareerService)
            import api.driver_views as _compat
            service = _compat.DriverCareerService()
            # For 3-letter alpha codes, use uppercase when calling into the service
            service_identifier = original_identifier.upper() if original_identifier.isalpha() and len(original_identifier) == 3 else original_identifier
            season_data = service.get_driver_season(service_identifier, year)

            has_races = bool(season_data.get("races"))

            if not has_races:
                message = season_data.get("message") or f"No season data available for {driver_code} in {year}"
                logger.info(f"No season data for {driver_code}/{year}")
                return Response(
                    _build_empty_season_response(
                        driver_code,
                        year,
                        False,
                        message,
                        driver_name=season_data.get("driver_name"),
                    ),
                    status=200,
                )

            serializer = DriverSeasonResponseSerializer(season_data)

            if not is_current_year(year):
                from api.tasks import populate_driver_season
                task_key_code = original_identifier.upper() if len(original_identifier) == 3 else original_identifier
                TaskManager.enqueue_if_needed(
                    task_key=f"driver_season:{task_key_code}:{year}",
                    task_fn=populate_driver_season,
                    driver_code=original_identifier,
                    year=int(year),
                )

            # Some legacy service responses include top-level fields such as
            # `constructor`, `final_position`, and `final_points`. Ensure these
            # are surfaced even if the serializer does not declare them so
            # unit tests and consumers relying on them continue to work.
            payload = {**serializer.data}
            for key in ("constructor", "final_position", "final_points"):
                if key in season_data:
                    payload[key] = season_data.get(key)

            payload["readiness"] = build_readiness(True, ["season_breakdown"], [], None, [])
            return Response(payload)

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
        examples=[
            OpenApiExample(
                "Drivers in 2025",
                value={
                    "year": 2025,
                    "count": 20,
                    "drivers": [
                        {
                            "driver_id": "max_verstappen",
                            "driver_code": "VER",
                            "driver_name": "Max Verstappen",
                            "nationality": "Dutch",
                            "number": 1,
                            "seasons": [2015, 2016, 2017, 2018, 2019, 2020, 2021, 2022, 2023, 2024, 2025],
                        },
                        {
                            "driver_id": "lewis_hamilton",
                            "driver_code": "HAM",
                            "driver_name": "Lewis Hamilton",
                            "nationality": "British",
                            "number": 44,
                            "seasons": [2007, 2008, 2009, 2010, 2011, 2012, 2013, 2014, 2015, 2016, 2017, 2018, 2019, 2020, 2021, 2022, 2023, 2024, 2025],
                        },
                    ],
                },
                response_only=True,
            )
        ],
    )
    def get(self, request):
        try:
            year_param = request.query_params.get("year")
            
            if not year_param:
                return Response(
                    {
                        "error": "Missing required parameter",
                        "message": "year query parameter is required",
                        "drivers": [],
                        "count": 0,
                    },
                    status=400,
                )

            try:
                year = int(year_param)
            except (ValueError, TypeError):
                return Response(
                    {
                        "error": "Invalid year",
                        "message": "year must be an integer",
                        "drivers": [],
                        "count": 0,
                    },
                    status=400,
                )

            # ── Sync drivers for this year before querying ──────────────────────
            try:
                from api.drivers.services.sync_service import DriverSyncService
                sync_service = DriverSyncService()
                logger.info(f"[SearchDrivers] Syncing drivers for {year}...")
                sync_service.sync_season_drivers(year)
                logger.info(f"[SearchDrivers] Sync complete for {year}")
            except Exception as sync_err:
                logger.warning(f"[SearchDrivers] Sync failed for {year}: {sync_err}. Continuing with existing DB data.")

            # ── Query DB for drivers (not using .values() — return full objects) ─
            from api.models.drivers import F1Driver
            drivers = F1Driver.objects.filter(
                seasons__contains=[year]
            ).order_by('family_name', 'given_name')

            results = [self._serialize(d) for d in drivers]

            return Response(
                {
                    "year": year,
                    "count": len(results),
                    "drivers": results,
                },
                status=200,
            )

        except Exception as exc:
            logger.exception(f"Error listing drivers for year={year_param}: {exc}")
            return Response(
                {
                    "error": "Request failed",
                    "message": str(exc),
                    "drivers": [],
                    "count": 0,
                },
                status=500,
            )

    def _serialize(self, driver_obj) -> dict:
        """Convert F1Driver model object to dict with all fields."""
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

    Search drivers by partial name or code. DB-only, no Jolpica fallback.
    If DB is empty, returns 503 with sync hint.
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
            OpenApiParameter(
                name="q",
                location=OpenApiParameter.QUERY,
                required=True,
                type=str,
                description="Search query (min 2 chars): partial name or driver code",
            ),
            OpenApiParameter(
                name="year",
                location=OpenApiParameter.QUERY,
                required=False,
                type=int,
                description="Optional year filter",
            ),
        ],
        responses={200: "DriverSearchByNameResponseSerializer", 503: "DriverSearchByNameResponseSerializer"},
        examples=[
            OpenApiExample(
                "Search for Ver (Verstappen) in 2025",
                value={
                    "query": "ver",
                    "year": 2025,
                    "count": 1,
                    "results": [
                        {
                            "driver_id": "max_verstappen",
                            "driver_code": "VER",
                            "driver_name": "Max Verstappen",
                            "nationality": "Dutch",
                            "number": 1,
                            "seasons": [2015, 2016, 2017, 2018, 2019, 2020, 2021, 2022, 2023, 2024, 2025],
                            "matches": {
                                "code": True,
                                "given_name": False,
                                "family_name": True,
                            },
                        }
                    ],
                    "message": None,
                },
                response_only=True,
            )
        ],
    )
    def get(self, request):
        try:
            query = request.query_params.get("q", "").strip()
            year_param = request.query_params.get("year")

            if len(query) < 2:
                return Response(
                    {
                        "error": "Query too short",
                        "message": "Search query must be at least 2 characters",
                        "results": [],
                        "count": 0,
                    },
                    status=400,
                )

            try:
                year = int(year_param) if year_param else None
            except (ValueError, TypeError):
                year = None

            from django.db.models import Q
            from api.models.drivers import F1Driver

            # Build base query
            q_filter = Q(
                given_name__icontains=query
            ) | Q(
                family_name__icontains=query
            ) | Q(
                code__iexact=query
            ) | Q(
                driver_id__icontains=query
            )

            drivers = F1Driver.objects.filter(q_filter)

            # Apply year filter if provided
            if year:
                drivers = drivers.filter(seasons__contains=[year])

            drivers = drivers.values('driver_id', 'code', 'given_name', 'family_name', 'nationality', 'number', 'seasons').order_by(
                'family_name', 'given_name'
            )

            results = []
            for d in drivers:
                driver_name = f"{d['given_name']} {d['family_name']}"
                matches = {
                    "code": (d['code'] or '').upper() == query.upper() if d['code'] else False,
                    "given_name": query.lower() in d['given_name'].lower(),
                    "family_name": query.lower() in d['family_name'].lower(),
                    "driver_id": query.lower() in d['driver_id'].lower() if d['driver_id'] else False,
                }
                results.append({
                    "driver_id": d['driver_id'],
                    "driver_code": d['code'],
                    "driver_name": driver_name,
                    "nationality": d['nationality'],
                    "number": d['number'],
                    "seasons": d['seasons'],
                    "matches": matches,
                })

            # ── DB-only mode: no Jolpica fallback ─────────────────────────────
            if not results:
                # Check if the table has ANY data at all
                db_has_data = F1Driver.objects.exists()

                if not db_has_data:
                    return Response(
                        {
                            "query": query,
                            "year": year,
                            "count": 0,
                            "results": [],
                            "message": "Driver database not yet synced. Call /api/drivers/search/?year={} first to populate.".format(year or 2025),
                        },
                        status=503,
                    )

                # DB has data but no match for this query
                return Response(
                    {
                        "query": query,
                        "year": year,
                        "count": 0,
                        "results": [],
                        "message": None,
                    },
                    status=200,
                )

            return Response(
                {
                    "query": query,
                    "year": year,
                    "count": len(results),
                    "results": results,
                    "message": None,
                },
                status=200,
            )

        except Exception as exc:
            logger.exception(f"Error searching drivers for query={query}: {exc}")
            return Response(
                {
                    "error": "Search failed",
                    "message": str(exc),
                    "results": [],
                    "count": 0,
                },
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
                year,
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


class SyncAllYearsAPIView(APIView):
    """
    POST /api/drivers/sync/all/

    Sync drivers for all seasons (1950–2025) from Jolpica into F1Driver model.
    One-time setup operation. Runs as a background Celery task with rate limiting.
    
    Returns: task_id (202) for background task
    """

    @extend_schema(
        summary="Sync all drivers (all seasons)",
        description=(
            "Start a background task to synchronize all drivers from Jolpica (1950–2025) "
            "into the F1Driver table. This is a one-time setup operation. Runs with 0.3s "
            "rate limiting to respect Jolpica's 4 req/sec burst limit. "
            "Returns 202 (Accepted) with task_id."
        ),
        responses={
            202: "DriverSyncResponseSerializer",
        },
    )
    def post(self, request):
        try:
            task_key = "sync_drivers_all"

            # Check if task already queued
            existing_task = TaskManager.get_by_key(task_key)
            if existing_task:
                logger.info(f"Full sync task already queued: {existing_task.task_id}")
                return Response(
                    {
                        "message": "Full driver sync already queued",
                        "task_id": existing_task.task_id,
                        "status": "queued",
                        "estimated_duration_minutes": 50,  # ~1950-2025 @ 0.3s/year
                    },
                    status=202,
                )

            # Enqueue full sync task
            from api.tasks import sync_all_drivers_task
            task_result = TaskManager.enqueue_if_needed(
                task_key,
                sync_all_drivers_task,
                1950,  # start year
                2025,  # end year
            )

            logger.info(f"Enqueued full sync task: {task_result.id if task_result else 'none'}")

            return Response(
                {
                    "message": "Full driver sync task enqueued (1950–2025)",
                    "task_id": task_result.id if task_result else None,
                    "status": "queued",
                    "estimated_duration_minutes": 50,
                },
                status=202,
            )

        except Exception as exc:
            logger.exception(f"Error enqueuing full driver sync: {exc}")
            return Response(
                {
                    "error": "Sync failed",
                    "message": str(exc),
                    "task_id": None,
                    "status": "failed",
                },
                status=500,
            )


class SyncChampionsAPIView(APIView):
    """
    POST /api/drivers/champions/sync/
    POST /api/drivers/champions/sync/{year}/

    Sync F1 champions from Jolpica into F1Champion table.
    Async operation via Celery.
    """

    def post(self, request, year=None):
        """Enqueue champion sync task."""
        from api.tasks import sync_champions_task
        from api.services.task_manager import TaskManager

        task_key = f"sync_champions:{year}" if year else "sync_champions"

        TaskManager.enqueue_if_needed(
            task_key,
            sync_champions_task,
            task_key,
            year,
        )

        return Response(
            {
                "task_key": task_key,
                "year": year,
                "message": f"Champion sync queued for {'all years' if not year else year}",
                "status": "queued",
            },
            status=202,
        )
