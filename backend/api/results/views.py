"""Views for results domain."""
import logging
from rest_framework.response import Response
from rest_framework.views import APIView
from drf_spectacular.utils import extend_schema, OpenApiResponse, OpenApiParameter, OpenApiExample
from drf_spectacular.types import OpenApiTypes

from api.common.readiness import build_readiness
from api.common.response import build_error_payload

from api.results.serializers import (
    QualifyingResultSerializer,
    PracticeResultSerializer,
)
from api.results.services.race import get_race_results
from api.results.services.qualifying import get_qualifying_results
from api.results.services.sprint import get_sprint_results, get_sprint_shootout_results
from api.results.services.practice import get_practice_session_results
from api.results.services.weekend import get_weekend_results

logger = logging.getLogger(__name__)


class RaceResultsAPIView(APIView):
    @extend_schema(
        summary="Get race & qualifying results",
        description=(
            "Returns the combined race classification and qualifying results for a single round. "
            "Data is read primarily from PostgreSQL. If either session is missing in the DB, it "
            "falls back to FastF1, triggering background persistence for the missing data."
        ),
        responses={200: OpenApiTypes.OBJECT, 404: OpenApiResponse(description="Results not found")},
    )
    def get(self, request, year, round_number):
        try:
            results_data = get_race_results(year, round_number)
            return Response(results_data)
        except ValueError as exc:
            return Response({"error": str(exc)}, status=400)
        except Exception as exc:
            return Response(build_error_payload("races.results", str(exc), "RACES_RESULTS_ERROR"), status=500)


class QualifyingResultsAPIView(APIView):
    @extend_schema(
        summary="Get qualifying results only",
        description=(
            "Loads the Qualifying session via FastF1 and returns each driver's Q1, Q2, and Q3 "
            "times along with their final grid position. For seasons or rounds where FastF1 "
            "does not carry qualifying data (e.g. very old seasons), can_proceed will be false "
            "and the data array will be empty rather than raising an error."
        ),
        responses={
            200: OpenApiTypes.OBJECT,
            400: OpenApiResponse(description="Invalid route parameters"),
        },
    )
    def get(self, request, year, round_number):
        try:
            qualifying = get_qualifying_results(year, round_number)
            if isinstance(qualifying, dict):
                qualifying_rows = qualifying.get("data", [])
                readiness = qualifying.get("meta", {}).get("readiness")
            else:
                qualifying_rows = qualifying
                readiness = None

            serializer = QualifyingResultSerializer(qualifying_rows, many=True)
            return Response(
                {
                    "year": year,
                    "round": round_number,
                    "qualifying": serializer.data,
                    "readiness": readiness
                    or build_readiness(
                        bool(qualifying_rows),
                        ["qualifying_results"] if qualifying_rows else [],
                        [] if qualifying_rows else ["qualifying_results"],
                        None if qualifying_rows else f"No qualifying data returned for {year} Round {round_number}.",
                        [] if qualifying_rows else [f"No qualifying data returned for {year} Round {round_number}."]
                    ),
                }
            )
        except ValueError as exc:
            return Response({"error": str(exc)}, status=400)
        except Exception as exc:
            return Response(build_error_payload("races.qualifying", str(exc), "RACES_QUALIFYING_ERROR"), status=500)


class SprintResultsAPIView(APIView):
    @extend_schema(
        summary="Get sprint race results",
        description=(
            "Loads the Sprint session via FastF1 and returns the sprint race results."
        ),
        responses={
            200: OpenApiTypes.OBJECT,
            400: OpenApiResponse(description="Invalid route parameters"),
        },
    )
    def get(self, request, year, round_number):
        try:
            sprint_data = get_sprint_results(year, round_number)
            return Response(sprint_data)
        except ValueError as exc:
            return Response({"error": str(exc)}, status=400)
        except Exception as exc:
            return Response(build_error_payload("races.sprint", str(exc), "RACES_SPRINT_ERROR"), status=500)


class SprintShootoutResultsAPIView(APIView):
    @extend_schema(
        summary="Get sprint shootout results",
        description=(
            "Loads the Sprint Shootout session via FastF1 and returns the shootout results."
        ),
        responses={
            200: OpenApiTypes.OBJECT,
            400: OpenApiResponse(description="Invalid route parameters"),
        },
    )
    def get(self, request, year, round_number):
        try:
            shootout_data = get_sprint_shootout_results(year, round_number)
            return Response(shootout_data)
        except ValueError as exc:
            return Response({"error": str(exc)}, status=400)
        except Exception as exc:
            return Response(build_error_payload("races.sprint_shootout", str(exc), "RACES_SPRINT_SHOOTOUT_ERROR"), status=500)


class PracticeSessionAPIView(APIView):
    @extend_schema(
        summary="Get practice session fastest laps",
        description=(
            "Returns the fastest-lap leaderboard for FP1, FP2, or FP3. The service prioritises "
            "lap-time data from the loaded session; if lap data is unavailable it falls back to "
            "the session results table (which carries best-lap information for older seasons). "
            "Passing an invalid session name such as FP4 returns a 400 immediately."
        ),
        parameters=[
            OpenApiParameter(name="session_name", location=OpenApiParameter.PATH, required=True, type=str, description="FP1, FP2, or FP3"),
        ],
        responses={
            200: OpenApiTypes.OBJECT,
            400: OpenApiResponse(description="Invalid route parameters"),
        },
    )
    def get(self, request, year, round_number, session_name):
        try:
            practice = get_practice_session_results(year, round_number, session_name)
            if isinstance(practice, dict):
                practice_rows = practice.get("data", [])
                readiness = practice.get("meta", {}).get("readiness")
            else:
                practice_rows = practice
                readiness = None

            serializer = PracticeResultSerializer(practice_rows, many=True)
            return Response(
                {
                    "year": year,
                    "round": round_number,
                    "session": str(session_name).upper(),
                    "practice": serializer.data,
                    "readiness": readiness
                    or build_readiness(
                        bool(practice_rows),
                        ["practice_results"] if practice_rows else [],
                        [] if practice_rows else ["practice_results"],
                        None if practice_rows else f"No practice data returned for {year} Round {round_number} ({str(session_name).upper()}).",
                        [] if practice_rows else [f"No practice data returned for {year} Round {round_number} ({str(session_name).upper()})."]
                    ),
                }
            )
        except ValueError as exc:
            return Response({"error": str(exc)}, status=400)
        except Exception as exc:
            return Response(build_error_payload("races.practice", str(exc), "RACES_PRACTICE_ERROR"), status=500)


class WeekendResultsAPIView(APIView):
    @extend_schema(
        summary="Get all session results for a race weekend",
        description=(
            "Returns results for every session held during the requested race weekend (Practice 1-3, "
            "Qualifying, Sprint Shootout, Sprint, and Race) combined into a single payload. "
            "It queries the schedule to determine the event format and gracefully handles missing "
            "sessions, ensuring that each underlying dataset triggers its own isolated DB caching "
            "and FastF1 persistence behavior."
        ),
        responses={
            200: OpenApiTypes.OBJECT,
            400: OpenApiResponse(description="Invalid route parameters"),
        },
    )
    def get(self, request, year, round_number):
        try:
            weekend_data = get_weekend_results(year, round_number)
            if not weekend_data:
                return Response(
                    {"error": f"No schedule data found for {year} Round {round_number}"}, 
                    status=404
                )
            
            # Use serializers if needed
            sessions = weekend_data["sessions"]
            for s_name in ["FP1", "FP2", "FP3"]:
                if s_name in sessions and "data" in sessions[s_name]:
                    sessions[s_name]["data"] = PracticeResultSerializer(sessions[s_name]["data"], many=True).data
            
            if "Q" in sessions and "data" in sessions["Q"]:
                sessions["Q"]["data"] = QualifyingResultSerializer(sessions["Q"]["data"], many=True).data
                
            return Response(weekend_data)
        except Exception as exc:
            return Response(build_error_payload("weekend.results", str(exc), "WEEKEND_RESULTS_ERROR"), status=500)
