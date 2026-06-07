import logging
from rest_framework.views import APIView
from rest_framework.response import Response
from drf_spectacular.utils import extend_schema, OpenApiResponse, OpenApiParameter, OpenApiExample
from drf_spectacular.types import OpenApiTypes
from api.common.readiness import build_readiness
from api.common.response import build_error_payload
from api.queue.manager import TaskManager
from api.services.streaming import stream_task_result_json
from api.tasks import populate_constructor_standings
from api.constructors.serializers import ConstructorStandingsResponseSerializer, ConstructorSerializer
from api.services.persistence import get_persisted_constructor_standings

logger = logging.getLogger(__name__)

class ConstructorStandingsAPIView(APIView):
    @extend_schema(
        operation_id="constructors_standings_retrieve",
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
        request.endpoint_type = "standings"
        try:
            persisted = get_persisted_constructor_standings(year)
            if persisted is not None:
                serializer = ConstructorSerializer(persisted, many=True)
                return Response(
                    {
                        "year": year,
                        "constructors": serializer.data,
                        "readiness": build_readiness(True, ["constructor_standings_persisted"], []),
                    }
                )

            task_key = f"constructor_standings:{year}"
            TaskManager.enqueue_if_needed(
                task_key=task_key,
                task_fn=populate_constructor_standings,
                year=int(year),
            )
            return stream_task_result_json(task_key)
        except Exception as exc:
            logger.exception("Constructor standings error")
            return Response(build_error_payload("constructors.standings", str(exc), "CONSTRUCTORS_STANDINGS_ERROR"), status=500)

