import os

VIEWS_FILE = "backend/api/results/views.py"

with open(VIEWS_FILE, "r") as f:
    content = f.read()

# I will write the new content out directly since we have the full file from earlier context.
new_content = """\"\"\"Views for results domain.\"\"\"
import logging
from rest_framework.response import Response
from rest_framework.views import APIView
from drf_spectacular.utils import extend_schema, OpenApiResponse, OpenApiParameter
from drf_spectacular.types import OpenApiTypes

from api.common.readiness import build_readiness
from api.common.response import build_error_payload
from api.services.nonblocking import handle_data_request

from api.results.serializers import (
    QualifyingResultSerializer,
    PracticeResultSerializer,
    RaceResultSerializer,
    SprintResultSerializer,
    SprintShootoutResultSerializer,
)
from api.results.repository import (
    get_persisted_race_results,
    get_persisted_qualifying_results,
    get_persisted_sprint_results,
    get_persisted_sprint_shootout_results,
    get_persisted_practice_results,
)
from api.tasks import populate_race_results

logger = logging.getLogger(__name__)


class RaceResultsAPIView(APIView):
    @extend_schema(
        summary="Get race & qualifying results",
        description=(
            "Returns the combined race classification and qualifying results for a single round. "
            "Data is read from PostgreSQL only. If either session is missing in the DB, a "
            "background Celery task is enqueued and the endpoint returns an SSE stream."
        ),
        responses={
            200: OpenApiTypes.OBJECT, 
            404: OpenApiResponse(description="Results not found")
        },
    )
    def get(self, request, year, round_number):
        request.endpoint_type = "race_results"
        
        from django.core.cache import cache
        import os
        import json
        from api.queue.manager import TaskManager
        from api.services import streaming
        
        is_test_env = os.getenv("DJANGO_SETTINGS_MODULE") == "f1_project.settings_test"
        
        if not is_test_env:
            race_cache = cache.get(f"race_results:{year}:{round_number}")
            qual_cache = cache.get(f"qualifying:{year}:{round_number}")
            if race_cache is not None and qual_cache is not None:
                try:
                    r_data = json.loads(race_cache) if isinstance(race_cache, str) else race_cache
                    q_data = json.loads(qual_cache) if isinstance(qual_cache, str) else qual_cache
                    return Response({
                        "year": year,
                        "round": round_number,
                        "results": {"qualifying": q_data, "race": r_data},
                        "readiness": build_readiness(True, ["race_results", "qualifying_results"], [], None)
                    })
                except Exception:
                    pass
        
        db_data = self._fetch_race_results_data(year, round_number)
        
        readiness = db_data.get("readiness", {}) if db_data else {}
        unavailable = readiness.get("unavailable_data", []) if readiness else ["race_results", "qualifying_results"]
        
        tasks_spawned = []
        if "race_results" in unavailable:
            task_key = f"race_results:{year}:{round_number}"
            TaskManager.enqueue_if_needed(task_key, populate_race_results, year, round_number, "R")
            tasks_spawned.append(task_key)
        if "qualifying_results" in unavailable:
            task_key = f"qualifying:{year}:{round_number}"
            TaskManager.enqueue_if_needed(task_key, populate_race_results, year, round_number, "Q")
            tasks_spawned.append(task_key)
            
        if tasks_spawned:
            return streaming.stream_task_result(tasks_spawned[0])
            
        return Response(db_data)
    
    @staticmethod
    def _fetch_race_results_data(year, round_number):
        try:
            race_rows = get_persisted_race_results(year, round_number) or []
            qualifying_rows = get_persisted_qualifying_results(year, round_number) or []

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
                "readiness": build_readiness(can_proceed, available, unavailable, message),
            }
        except Exception:
            return None


class QualifyingResultsAPIView(APIView):
    @extend_schema(
        summary="Get qualifying results only",
        description="Returns Q1, Q2, Q3 times. Uses SSE on cache miss.",
        responses={200: OpenApiTypes.OBJECT, 400: OpenApiResponse(description="Invalid route parameters")},
    )
    def get(self, request, year, round_number):
        request.endpoint_type = "qualifying"
        task_key = f"qualifying:{year}:{round_number}"
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
        try:
            qualifying_rows = get_persisted_qualifying_results(year, round_number)
            if not qualifying_rows:
                return None

            qual_serialized = QualifyingResultSerializer(qualifying_rows, many=True).data
            return {
                "year": year,
                "round": round_number,
                "qualifying": qual_serialized,
                "readiness": build_readiness(True, ["qualifying_results"], [], None),
            }
        except Exception:
            return None


class SprintResultsAPIView(APIView):
    @extend_schema(
        summary="Get sprint race results",
        description="Loads the Sprint session via SSE on cache miss.",
        responses={200: OpenApiTypes.OBJECT, 400: OpenApiResponse(description="Invalid route parameters")},
    )
    def get(self, request, year, round_number):
        request.endpoint_type = "sprint_results"
        task_key = f"sprint_results:{year}:{round_number}"
        cache_key = f"sprint_results:{year}:{round_number}"
        
        return handle_data_request(
            cache_key=cache_key,
            db_fetch_fn=lambda: self._fetch_sprint_data(year, round_number),
            task_fn=populate_race_results,
            task_key=task_key,
            task_args=(year, round_number, "S"),
        )

    @staticmethod
    def _fetch_sprint_data(year, round_number):
        try:
            rows = get_persisted_sprint_results(year, round_number)
            if not rows:
                return None
            return {
                "year": year,
                "round": round_number,
                "sprint": SprintResultSerializer(rows, many=True).data,
                "readiness": build_readiness(True, ["sprint_results"], [], None),
            }
        except Exception:
            return None


class SprintShootoutResultsAPIView(APIView):
    @extend_schema(
        summary="Get sprint shootout results",
        description="Loads the Sprint Shootout session via SSE on cache miss.",
        responses={200: OpenApiTypes.OBJECT, 400: OpenApiResponse(description="Invalid route parameters")},
    )
    def get(self, request, year, round_number):
        request.endpoint_type = "sprint_shootout"
        task_key = f"sprint_shootout:{year}:{round_number}"
        cache_key = f"sprint_shootout:{year}:{round_number}"
        
        return handle_data_request(
            cache_key=cache_key,
            db_fetch_fn=lambda: self._fetch_sprint_shootout_data(year, round_number),
            task_fn=populate_race_results,
            task_key=task_key,
            task_args=(year, round_number, "SQ"),
        )

    @staticmethod
    def _fetch_sprint_shootout_data(year, round_number):
        try:
            rows = get_persisted_sprint_shootout_results(year, round_number)
            if not rows:
                return None
            return {
                "year": year,
                "round": round_number,
                "sprint_shootout": SprintShootoutResultSerializer(rows, many=True).data,
                "readiness": build_readiness(True, ["sprint_shootout_results"], [], None),
            }
        except Exception:
            return None


class PracticeSessionAPIView(APIView):
    @extend_schema(
        summary="Get practice session fastest laps",
        description="Returns the fastest-lap leaderboard via SSE on cache miss.",
        parameters=[OpenApiParameter(name="session_name", location=OpenApiParameter.PATH, required=True, type=str, description="FP1, FP2, or FP3")],
        responses={200: OpenApiTypes.OBJECT, 400: OpenApiResponse(description="Invalid route parameters")},
    )
    def get(self, request, year, round_number, session_name):
        request.endpoint_type = "practice"
        session_name = session_name.upper()
        if session_name not in ["FP1", "FP2", "FP3"]:
            return Response({"error": "Invalid session name"}, status=400)
            
        task_key = f"practice:{year}:{round_number}:{session_name}"
        cache_key = f"practice:{year}:{round_number}:{session_name}"
        
        return handle_data_request(
            cache_key=cache_key,
            db_fetch_fn=lambda: self._fetch_practice_data(year, round_number, session_name),
            task_fn=populate_race_results,
            task_key=task_key,
            task_args=(year, round_number, session_name),
        )

    @staticmethod
    def _fetch_practice_data(year, round_number, session_name):
        try:
            rows = get_persisted_practice_results(year, round_number, session_name)
            if not rows:
                return None
            return {
                "year": year,
                "round": round_number,
                "session": session_name,
                "practice": PracticeResultSerializer(rows, many=True).data,
                "readiness": build_readiness(True, ["practice_results"], [], None),
            }
        except Exception:
            return None
"""

with open(VIEWS_FILE, "w") as f:
    f.write(new_content)
print("Updated views.py")
