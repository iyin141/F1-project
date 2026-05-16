"""
Constructor standings view — thin HTTP layer.

Handles: parse year → call service → return Response.
"""
from rest_framework.response import Response
from rest_framework.views import APIView
from drf_spectacular.utils import OpenApiExample, extend_schema

from api.common.readiness import build_readiness
from api.common.response import build_error_payload
from api.constructors.serializers import ConstructorSerializer, ConstructorStandingsResponseSerializer
from api.constructors.services import get_constructor_standings


class ConstructorStandingsAPIView(APIView):
    @extend_schema(
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
        try:
            standings = get_constructor_standings(year)
            if isinstance(standings, dict):
                rows = standings.get("data", [])
                readiness = standings.get("meta", {}).get("readiness")
            else:
                rows = standings
                readiness = None

            serializer = ConstructorSerializer(rows, many=True)
            return Response(
                {
                    "year": year,
                    "constructors": serializer.data,
                    "readiness": readiness
                    or build_readiness(
                        bool(rows),
                        ["constructor_standings_api"] if rows else [],
                        [] if rows else ["constructor_standings_api"],
                        None if rows else f"No constructor standings data returned for {year}.",
                        [] if rows else [f"No constructor standings data returned for {year}."]
                    ),
                }
            )
        except Exception as exc:
            return Response(build_error_payload("constructors.standings", str(exc), "CONSTRUCTORS_STANDINGS_ERROR"), status=500)
