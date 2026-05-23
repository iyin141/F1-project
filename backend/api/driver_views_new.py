from rest_framework.views import APIView
from rest_framework.response import Response
from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiResponse
import logging

from api.serializers import DriverCareerResponseSerializer, DriverSeasonResponseSerializer
from api.services.driver_career_service import DriverCareerService

logger = logging.getLogger(__name__)


def _build_checklist(can_proceed, available_data=None, unavailable_data=None, message=None, warnings=None):
    """
    Build readiness checklist matching the pattern from views.py.
    Always provides can_proceed, available_data, unavailable_data, message, warnings.
    """
    if available_data is None:
        available_data = []
    if unavailable_data is None:
        unavailable_data = []
    if warnings is None:
        warnings = [] if can_proceed else ([message] if message else [])
    return {
        "can_proceed": bool(can_proceed),
        "available_data": list(available_data),
        "unavailable_data": list(unavailable_data),
        "message": message,
        "warnings": list(warnings),
    }


def _build_empty_career_response(driver_code, can_proceed=False, message=None, driver_name=None, nationality=None):
    """Build empty career response with readiness."""
    return {
        "driver_code": driver_code,
        "driver_name": driver_name,
        "nationality": nationality,
        "career": [],
        "career_totals": {
            "championships": 0,
            "wins": 0,
            "podiums": 0,
            "poles": 0,
            "fastest_laps": 0,
            "races_entered": 0,
            "dnfs": 0,
            "total_points": 0,
        },
        "readiness": _build_checklist(
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
        "year": year,
        "constructor": None,
        "final_position": None,
        "final_points": None,
        "races": [],
        "readiness": _build_checklist(
            can_proceed,
            [],
            [] if can_proceed else ["season_breakdown"],
            message,
            [] if can_proceed else ([message] if message else []),
        ),
    }


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
        request.endpoint_type = "career"
        try:
            # Validate driver code format
            if not driver_code or len(driver_code) != 3:
                message = f"Invalid driver code: {driver_code}. Must be 3 letters."
                logger.info(f"Invalid driver code: {driver_code}")
                return Response(_build_empty_career_response(driver_code, False, message), status=200)

            driver_code = driver_code.upper()
            service = DriverCareerService()
            career_data = service.get_driver_career(driver_code)

            # Check if we have any data
            has_data = bool(career_data.get("career"))

            if not has_data:
                message = "No career data available for this driver"
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

            # Serialize and return data with readiness
            serializer = DriverCareerResponseSerializer(career_data)
            return Response(
                {
                    **serializer.data,
                    "readiness": _build_checklist(True, ["career"], [], None, []),
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
        request.endpoint_type = "career"
        try:
            # Validate driver code format
            if not driver_code or len(driver_code) != 3:
                message = f"Invalid driver code: {driver_code}. Must be 3 letters."
                logger.info(f"Invalid driver code: {driver_code}")
                return Response(_build_empty_season_response(driver_code, year, False, message), status=200)

            # Validate year bounds
            if not isinstance(year, int) or year < 1950 or year > 2100:
                message = f"Invalid year: {year}. Must be between 1950 and 2100."
                logger.info(f"Invalid year: {year}")
                return Response(_build_empty_season_response(driver_code, year, False, message), status=200)

            driver_code = driver_code.upper()
            service = DriverCareerService()
            season_data = service.get_driver_season(driver_code, year)

            # Check if we have any race data
            has_races = bool(season_data.get("races"))

            if not has_races:
                message = f"No season data available for {driver_code} in {year}"
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

            # Serialize and return data with readiness
            serializer = DriverSeasonResponseSerializer(season_data)
            return Response(
                {
                    **serializer.data,
                    "readiness": _build_checklist(True, ["season_breakdown"], [], None, []),
                }
            )

        except ValueError as exc:
            logger.warning(f"ValueError fetching season for {driver_code}/{year}: {exc}")
            message = str(exc)
            return Response(_build_empty_season_response(driver_code, year, False, message), status=200)

        except Exception as exc:
            logger.exception(f"Unexpected error fetching season for {driver_code}/{year}: {exc}")
            message = f"Internal error: {str(exc)}"
            return Response(_build_empty_season_response(driver_code, year, False, message), status=500)
