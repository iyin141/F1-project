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


def _build_standard_response(year: int, round_number: int, session: str, data: any, can_proceed: bool, available_data: list, unavailable_data: list, message: str = None, limit_max: int = 2000, filters: dict = None):
    """Helper to build the strict standard response format."""
    return {
        "meta": {
            "year": int(year),
            "round": int(round_number),
            "session": session,
            "row_count": len(data) if isinstance(data, list) else 1,
            "limit_max": limit_max,
            "can_proceed": bool(can_proceed),
            "available_data": available_data,
            "unavailable_data": unavailable_data,
            "message": message,
            "warnings": [] if can_proceed else ([message] if message else []),
        },
        "filters_applied": filters or {
            "driver": None,
            "limit": None,
        },
        "data": data,
    }


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
        examples=[
            OpenApiExample(
                "Combined Results Example",
                value={
                    "meta": {
                        "year": 2024,
                        "round": 1,
                        "session": "R",
                        "row_count": 20,
                        "limit_max": 2000,
                        "can_proceed": True,
                        "available_data": ["race_results", "qualifying_results"],
                        "unavailable_data": [],
                        "message": None,
                        "warnings": []
                    },
                    "filters_applied": {
                        "driver": None,
                        "limit": None
                    },
                    "data": [
                        {
                            "position": 1,
                            "driver_number": 1,
                            "driver_name": "Max Verstappen",
                            "team": "Red Bull Racing",
                            "points": 26.0,
                            "status": "Finished",
                            "grid_position": 1,
                            "laps": 57,
                            "gap": "0.000",
                            "fastest_lap": "1:32.608",
                            "fastest_lap_of_race": True
                        }
                    ],
                    "qualifying": [
                        {
                            "position": 1,
                            "driver_number": 1,
                            "driver_name": "Max Verstappen",
                            "team": "Red Bull Racing",
                            "q1_time": "1:29.814",
                            "q2_time": "1:29.374",
                            "q3_time": "1:29.179",
                            "laps": 18
                        }
                    ]
                },
                response_only=True,
                status_codes=["200"],
            )
        ]
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
                    
                    # Safely unwrap if the cache contains the full published dict instead of raw arrays
                    if isinstance(r_data, dict):
                        r_data = r_data.get("data", {}).get("race", r_data.get("results", {}).get("race", r_data.get("data", r_data)))
                    if isinstance(q_data, dict):
                        q_data = q_data.get("data", q_data.get("qualifying", q_data))

                    combined_data = r_data
                    response_payload = _build_standard_response(
                        year=year,
                        round_number=round_number,
                        session="R",
                        data=combined_data,
                        can_proceed=True,
                        available_data=["race_results", "qualifying_results"],
                        unavailable_data=[]
                    )
                    response_payload["qualifying"] = q_data
                    return Response(response_payload)
                except Exception:
                    pass
        
        db_data = self._fetch_race_results_data(year, round_number)
        
        meta = db_data.get("meta", {}) if db_data else {}
        unavailable = meta.get("unavailable_data", []) if meta else ["race_results", "qualifying_results"]
        
        if "race_results" in unavailable:
            task_key = f"race_results:{year}:{round_number}"
            tasks_spawned = [task_key]
            TaskManager.enqueue_if_needed(task_key, populate_race_results, year, round_number, "R")
            
            if "qualifying_results" in unavailable:
                q_task = f"qualifying:{year}:{round_number}"
                TaskManager.enqueue_if_needed(q_task, populate_race_results, year, round_number, "Q")
                tasks_spawned.append(q_task)
                
            return streaming.stream_combined_task_results_json(tasks_spawned)
            
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

            combined_data = race_serialized
            response_payload = _build_standard_response(
                year=year, round_number=round_number, session="R",
                data=combined_data, can_proceed=can_proceed,
                available_data=available, unavailable_data=unavailable, message=message
            )
            response_payload["qualifying"] = qual_serialized
            return response_payload
        except Exception:
            return None


class QualifyingResultsAPIView(APIView):
    @extend_schema(
        summary="Get qualifying results only",
        description="Returns Q1, Q2, Q3 times. Uses SSE on cache miss.",
        responses={200: OpenApiTypes.OBJECT, 400: OpenApiResponse(description="Invalid route parameters")},
        examples=[
            OpenApiExample(
                "Qualifying Only Example",
                value={
                    "meta": {
                        "year": 2024,
                        "round": 1,
                        "session": "Q",
                        "row_count": 20,
                        "limit_max": 2000,
                        "can_proceed": True,
                        "available_data": ["qualifying_results"],
                        "unavailable_data": [],
                        "message": None,
                        "warnings": []
                    },
                    "filters_applied": {
                        "driver": None,
                        "limit": None
                    },
                    "data": [
                        {
                            "position": 1,
                            "driver_number": 1,
                            "driver_name": "Max Verstappen",
                            "team": "Red Bull Racing",
                            "q1_time": "1:29.814",
                            "q2_time": "1:29.374",
                            "q3_time": "1:29.179",
                            "laps": 18
                        }
                    ]
                },
                response_only=True,
                status_codes=["200"],
            )
        ]
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
            return _build_standard_response(
                year=year, round_number=round_number, session="Q",
                data=qual_serialized, can_proceed=True,
                available_data=["qualifying_results"], unavailable_data=[]
            )
        except Exception:
            return None


class SprintResultsAPIView(APIView):
    @extend_schema(
        summary="Get sprint race results",
        description="Loads the Sprint session via SSE on cache miss.",
        responses={200: OpenApiTypes.OBJECT, 400: OpenApiResponse(description="Invalid route parameters")},
        examples=[
            OpenApiExample(
                "Sprint Results Example",
                value={
                    "meta": {
                        "year": 2024,
                        "round": 5,
                        "session": "S",
                        "row_count": 20,
                        "limit_max": 2000,
                        "can_proceed": True,
                        "available_data": ["sprint_results"],
                        "unavailable_data": [],
                        "message": None,
                        "warnings": []
                    },
                    "filters_applied": {
                        "driver": None,
                        "limit": None
                    },
                    "data": [
                        {
                            "position": 1,
                            "driver_number": 1,
                            "driver_name": "Max Verstappen",
                            "team": "Red Bull Racing",
                            "points": 8.0,
                            "status": "Finished",
                            "grid_position": 1,
                            "laps": 19,
                            "gap": "0.000",
                            "fastest_lap": "1:30.415"
                        }
                    ]
                },
                response_only=True,
                status_codes=["200"],
            )
        ]
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
            return _build_standard_response(
                year=year, round_number=round_number, session="S",
                data=SprintResultSerializer(rows, many=True).data, can_proceed=True,
                available_data=["sprint_results"], unavailable_data=[]
            )
        except Exception:
            return None


class SprintShootoutResultsAPIView(APIView):
    @extend_schema(
        summary="Get sprint shootout results",
        description="Loads the Sprint Shootout session via SSE on cache miss.",
        responses={200: OpenApiTypes.OBJECT, 400: OpenApiResponse(description="Invalid route parameters")},
        examples=[
            OpenApiExample(
                "Sprint Shootout Results Example",
                value={
                    "meta": {
                        "year": 2024,
                        "round": 5,
                        "session": "SQ",
                        "row_count": 20,
                        "limit_max": 2000,
                        "can_proceed": True,
                        "available_data": ["sprint_shootout_results"],
                        "unavailable_data": [],
                        "message": None,
                        "warnings": []
                    },
                    "filters_applied": {
                        "driver": None,
                        "limit": None
                    },
                    "data": [
                        {
                            "position": 1,
                            "driver_number": 1,
                            "driver_name": "Max Verstappen",
                            "team": "Red Bull Racing",
                            "sq1_time": "1:28.194",
                            "sq2_time": "1:28.001",
                            "sq3_time": "1:27.641",
                            "laps": 14
                        }
                    ]
                },
                response_only=True,
                status_codes=["200"],
            )
        ]
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
            return _build_standard_response(
                year=year, round_number=round_number, session="SQ",
                data=SprintShootoutResultSerializer(rows, many=True).data, can_proceed=True,
                available_data=["sprint_shootout_results"], unavailable_data=[]
            )
        except Exception:
            return None


class PracticeSessionAPIView(APIView):
    @extend_schema(
        summary="Get practice session fastest laps",
        description="Returns the fastest-lap leaderboard via SSE on cache miss.",
        parameters=[OpenApiParameter(name="session_name", location=OpenApiParameter.PATH, required=True, type=str, description="FP1, FP2, or FP3")],
        responses={200: OpenApiTypes.OBJECT, 400: OpenApiResponse(description="Invalid route parameters")},
        examples=[
            OpenApiExample(
                "Practice Session Example",
                value={
                    "meta": {
                        "year": 2024,
                        "round": 1,
                        "session": "FP1",
                        "row_count": 20,
                        "limit_max": 2000,
                        "can_proceed": True,
                        "available_data": ["practice_results"],
                        "unavailable_data": [],
                        "message": None,
                        "warnings": []
                    },
                    "filters_applied": {
                        "driver": None,
                        "limit": None
                    },
                    "data": [
                        {
                            "position": 1,
                            "driver_number": 3,
                            "driver_name": "Daniel Ricciardo",
                            "team": "RB",
                            "lap_time": "1:32.869",
                            "gap": "0.000",
                            "laps": 23
                        }
                    ]
                },
                response_only=True,
                status_codes=["200"],
            )
        ]
    )
    def get(self, request, year, round_number, session_name):
        request.endpoint_type = "practice"
        session_name = session_name.upper()
        if session_name not in ["FP1", "FP2", "FP3"]:
            return Response({"error": "Invalid session name"}, status=400)
            
        task_key = f"practice_results:{year}:{round_number}:{session_name}"
        cache_key = f"practice_results:{year}:{round_number}:{session_name}"
        
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
            return _build_standard_response(
                year=year, round_number=round_number, session=session_name,
                data=PracticeResultSerializer(rows, many=True).data, can_proceed=True,
                available_data=["practice_results"], unavailable_data=[]
            )
        except Exception:
            return None
