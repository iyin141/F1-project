"""Schedule domain views."""
import logging
from rest_framework.response import Response
from rest_framework.views import APIView
from drf_spectacular.utils import extend_schema, OpenApiResponse, OpenApiExample
from drf_spectacular.types import OpenApiTypes

from api.common.readiness import build_readiness
from api.common.response import build_error_payload
from api.schedule.services import get_season_schedule, get_race_by_round
from api.schedule.serializers import RaceSerializer

logger = logging.getLogger(__name__)


class SeasonScheduleAPIView(APIView):
    @extend_schema(
        summary="Get season race schedule",
        description=(
            "Returns the full calendar for a given F1 season as an ordered list of races. "
            "The service checks the local database first (for seasons that have been persisted) "
            "and falls back to a live FastF1 API call if no stored data is found. "
            "The round numbers in the response are the identifiers used by every other endpoint."
        ),
        responses={200: OpenApiTypes.OBJECT},
        examples=[
            OpenApiExample(
                "Season Schedule Example",
                value={
                    "year": 2024,
                    "races": [
                        {
                            "round": 1,
                            "name": "Bahrain Grand Prix",
                            "date": "2024-03-02",
                            "location": "Sakhir",
                            "country": "Bahrain",
                            "event_format": "standard",
                            "session1": "FP1", "session1_date_utc": "2024-02-29T11:30:00Z",
                            "session2": "FP2", "session2_date_utc": "2024-02-29T15:00:00Z",
                            "session3": "FP3", "session3_date_utc": "2024-03-01T12:30:00Z",
                            "session4": "Qualifying", "session4_date_utc": "2024-03-01T16:00:00Z",
                            "session5": "Race", "session5_date_utc": "2024-03-02T15:00:00Z"
                        }
                    ],
                    "readiness": {
                        "can_proceed": True,
                        "available_data": ["schedule"],
                        "unavailable_data": [],
                        "message": None,
                        "warnings": []
                    }
                },
                response_only=True,
                status_codes=["200"],
            )
        ]
    )
    def get(self, request, year):
        try:
            schedule = get_season_schedule(year)
            serializer = RaceSerializer(schedule, many=True)
            readiness = (
                build_readiness(True, ["schedule"], [], None, [])
                if schedule
                else build_readiness(
                    False,
                    [],
                    ["schedule"],
                    f"No race schedule data available for {year}.",
                    [f"No race schedule data available for {year}."]
                )
            )
            return Response(
                {
                    "year": year,
                    "races": serializer.data,
                    "readiness": readiness,
                }
            )
        except Exception as exc:
            return Response(build_error_payload("races.schedule", str(exc), "RACES_SCHEDULE_ERROR"), status=500)


class RaceDetailAPIView(APIView):
    @extend_schema(
        summary="Get single race detail",
        description=(
            "Returns name, date, location, and country for one race identified by season year "
            "and round number. Checks persisted DB data first; falls back to the live FastF1 "
            "schedule if the race has not been populated yet. Returns 404 when neither source "
            "can resolve the requested round."
        ),
        responses={200: OpenApiTypes.OBJECT, 404: OpenApiResponse(description="Race not found")},
        examples=[
            OpenApiExample(
                "Race Detail Example",
                value={
                    "round": 1,
                    "name": "Bahrain Grand Prix",
                    "date": "2024-03-02",
                    "location": "Sakhir",
                    "country": "Bahrain",
                    "event_format": "standard",
                    "session1": "FP1", "session1_date_utc": "2024-02-29T11:30:00Z",
                    "session2": "FP2", "session2_date_utc": "2024-02-29T15:00:00Z",
                    "session3": "FP3", "session3_date_utc": "2024-03-01T12:30:00Z",
                    "session4": "Qualifying", "session4_date_utc": "2024-03-01T16:00:00Z",
                    "session5": "Race", "session5_date_utc": "2024-03-02T15:00:00Z",
                    "readiness": {
                        "can_proceed": True,
                        "available_data": ["race_detail"],
                        "unavailable_data": [],
                        "message": None,
                        "warnings": []
                    }
                },
                response_only=True,
                status_codes=["200"],
            )
        ]
    )
    def get(self, request, year, round_number):
        try:
            race = get_race_by_round(year, round_number)
            if race is None:
                return Response(
                    {
                        "error": "Race not found",
                        "error_code": "RACES_DETAIL_NOT_FOUND",
                        "readiness": build_readiness(False, [], ["race_detail"], "Race not found", ["Race not found"]),
                    },
                    status=404,
                )
            serializer = RaceSerializer(race)
            return Response(
                {
                    **serializer.data,
                    "readiness": build_readiness(True, ["race_detail"], [], None, []),
                }
            )
        except Exception as exc:
            return Response(build_error_payload("races.detail", str(exc), "RACES_DETAIL_ERROR"), status=500)
