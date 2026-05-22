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
            if not driver_code or len(driver_code) != 3:
                message = f"Invalid driver code: {driver_code}. Must be 3 letters."
                logger.info(f"Invalid driver code: {driver_code}")
                return Response(_build_empty_career_response(driver_code, False, message), status=200)

            driver_code = driver_code.upper()
            # Use legacy-compatible service hook (allows tests to patch api.driver_views.DriverCareerService)
            import api.driver_views as _compat
            service = _compat.DriverCareerService()
            career_data = service.get_driver_career(driver_code)

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
            TaskManager.enqueue_if_needed(
                task_key=f"driver_career:{driver_code}",
                task_fn=populate_driver_career,
                driver_code=driver_code,
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
            if not driver_code or len(driver_code) != 3:
                message = f"Invalid driver code: {driver_code}. Must be 3 letters."
                logger.info(f"Invalid driver code: {driver_code}")
                return Response(_build_empty_season_response(driver_code, year, False, message), status=200)

            if not isinstance(year, int) or year < 1950 or year > 2100:
                message = f"Invalid year: {year}. Must be between 1950 and 2100."
                logger.info(f"Invalid year: {year}")
                return Response(_build_empty_season_response(driver_code, year, False, message), status=200)

            driver_code = driver_code.upper()
            # Use legacy-compatible service hook (allows tests to patch api.driver_views.DriverCareerService)
            import api.driver_views as _compat
            service = _compat.DriverCareerService()
            season_data = service.get_driver_season(driver_code, year)

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
                TaskManager.enqueue_if_needed(
                    task_key=f"driver_season:{driver_code}:{year}",
                    task_fn=populate_driver_season,
                    driver_code=driver_code,
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
