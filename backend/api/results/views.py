"""Views for results domain."""
import logging
from rest_framework.response import Response
from rest_framework.views import APIView
from drf_spectacular.utils import extend_schema, OpenApiResponse, OpenApiParameter, OpenApiExample
from drf_spectacular.types import OpenApiTypes

from api.common.readiness import build_readiness
from api.common.response import build_error_payload
from api.services.nonblocking import handle_data_request

from api.results.serializers import (
    QualifyingResultSerializer,
    PracticeResultSerializer,
)
from api.results.serializers import (
    RaceResultSerializer,
    SprintResultSerializer,
    SprintShootoutResultSerializer,
)
from api.results.repository import (
    get_persisted_race_results,
    get_persisted_qualifying_results,
)
from api.results.services.weekend import get_weekend_results
import api.views as api_views
from api.tasks import populate_race_results

logger = logging.getLogger(__name__)


class RaceResultsAPIView(APIView):
    @extend_schema(
        summary="Get race & qualifying results",
        description=(
            "Returns the combined race classification and qualifying results for a single round. "
            "Data is read from PostgreSQL only. If either session is missing in the DB, a "
            "background Celery task is enqueued and the endpoint returns 202 Accepted. "
            "Poll /api/tasks/{task_id}/status/ and retry when the task completes."
        ),
        responses={
            200: OpenApiTypes.OBJECT, 
            202: OpenApiTypes.OBJECT,
            404: OpenApiResponse(description="Results not found")
        },
    )
    def get(self, request, year, round_number):
        request.endpoint_type = "race_results"
        task_key = f"populate_race_results:{year}:{round_number}"
        cache_key = f"race_results:{year}:{round_number}"
        
        return handle_data_request(
            cache_key=cache_key,
            db_fetch_fn=lambda: self._fetch_race_results_data(year, round_number),
            task_fn=populate_race_results,
            task_key=task_key,
            task_args=(year, round_number, "R"),
        )
    
    @staticmethod
    def _fetch_race_results_data(year, round_number):
        """Fetch race & qualifying results from the DB only — no FastF1, no service calls.

        Returns None when either dataset is not yet persisted so the nonblocking
        helper proceeds to enqueue the Celery task.
        """
        try:
            race_rows = get_persisted_race_results(year, round_number)
            if race_rows is None:
                return None

            qualifying_rows = get_persisted_qualifying_results(year, round_number)
            if qualifying_rows is None:
                return None

            race_serialized = RaceResultSerializer(race_rows, many=True).data
            qual_serialized = QualifyingResultSerializer(qualifying_rows, many=True).data

            can_proceed = bool(race_rows or qualifying_rows)
            available = (["race_results"] if race_rows else []) + (["qualifying_results"] if qualifying_rows else [])
            unavailable = (["qualifying_results"] if not qualifying_rows else []) + (["race_results"] if not race_rows else [])
            message = None
            if not can_proceed:
                message = f"No results persisted for {year} Round {round_number}."
            elif not qualifying_rows:
                message = f"Qualifying data not yet available for {year} Round {round_number}."

            return {
                "year": year,
                "round": round_number,
                "results": {"qualifying": qual_serialized, "race": race_serialized},
                "readiness": build_readiness(
                    can_proceed,
                    available,
                    unavailable,
                    message,
                ),
            }
        except Exception:
            return None



class QualifyingResultsAPIView(APIView):
    @extend_schema(
        summary="Get qualifying results only",
        description=(
            "Returns each driver's Q1, Q2, and Q3 times along with their final grid position. "
            "Data is read from PostgreSQL only. If the session is not yet persisted the endpoint "
            "returns 202 Accepted and enqueues a background task. For rounds where qualifying "
            "data is persisted but empty, can_proceed will be false."
        ),
        responses={
            200: OpenApiTypes.OBJECT,
            202: OpenApiTypes.OBJECT,
            400: OpenApiResponse(description="Invalid route parameters"),
        },
    )
    def get(self, request, year, round_number):
        request.endpoint_type = "qualifying"
        task_key = f"populate_qualifying:{year}:{round_number}"
        cache_key = f"qualifying:{year}:{round_number}"
        
        return handle_data_request(
            cache_key=cache_key,
            db_fetch_fn=lambda: self._fetch_qualifying_data(year, round_number),
            task_fn=populate_race_results,
            task_key=task_key,
            task_args=(year, round_number, "Q"),
        )
    
    @staticmethod
    def _fetch_qualifying_data(year, round_number):
        """Fetch qualifying results from the DB only — no FastF1, no service calls.

        Returns None when the session is not yet persisted so the nonblocking
        helper proceeds to enqueue the Celery task.
        """
        try:
            qualifying_rows = get_persisted_qualifying_results(year, round_number)
            if qualifying_rows is None:
                return None

            qual_serialized = QualifyingResultSerializer(qualifying_rows, many=True).data
            can_proceed = bool(qualifying_rows)
            message = (
                f"Qualifying data not yet available for {year} Round {round_number}."
                if not qualifying_rows
                else None
            )

            return {
                "year": year,
                "round": round_number,
                "qualifying": qual_serialized,
                "readiness": build_readiness(
                    can_proceed,
                    ["qualifying_results"] if qualifying_rows else [],
                    [] if qualifying_rows else ["qualifying_results"],
                    message,
                ),
            }
        except Exception:
            return None



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
            sprint_data = api_views.get_sprint_results(year, round_number)

            # Re-serialize persisted or live rows through canonical serializer
            if isinstance(sprint_data, dict):
                rows = sprint_data.get("data", [])
                readiness = sprint_data.get("meta", {}).get("readiness")

                sprint_serialized = SprintResultSerializer(rows, many=True).data

                payload = {
                    "year": year,
                    "round": round_number,
                    "sprint": sprint_serialized,
                }
                if readiness is not None:
                    payload["readiness"] = readiness
                return Response(payload)

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
            shootout_data = api_views.get_sprint_shootout_results(year, round_number)

            # Re-serialize persisted or live rows through canonical serializer
            if isinstance(shootout_data, dict):
                rows = shootout_data.get("data", [])
                readiness = shootout_data.get("meta", {}).get("readiness")

                shootout_serialized = SprintShootoutResultSerializer(rows, many=True).data

                payload = {
                    "year": year,
                    "round": round_number,
                    "sprint_shootout": shootout_serialized,
                }
                if readiness is not None:
                    payload["readiness"] = readiness
                return Response(payload)

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
            practice = api_views.get_practice_session_results(year, round_number, session_name)
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

            # Sprint sessions: ensure canonical serializer shapes
            if "S" in sessions and "data" in sessions["S"]:
                sessions["S"]["data"] = SprintResultSerializer(sessions["S"]["data"], many=True).data
            if "SQ" in sessions and "data" in sessions["SQ"]:
                sessions["SQ"]["data"] = SprintShootoutResultSerializer(sessions["SQ"]["data"], many=True).data
                
            return Response(weekend_data)
        except Exception as exc:
            return Response(build_error_payload("weekend.results", str(exc), "WEEKEND_RESULTS_ERROR"), status=500)
