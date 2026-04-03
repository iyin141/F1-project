from rest_framework.response import Response
from rest_framework.views import APIView

from .serializers import (
    ConstructorSerializer,
    DriverStandingSerializer,
    PracticeResultSerializer,
    QualifyingResultSerializer,
    RaceResultsSerializer,
    RaceSerializer,
)
from .services.constructors import get_constructor_standings
from .services.drivers import get_driver_standings
from .services.results import get_practice_session_results, get_qualifying_results, get_race_results
from .services.schedule import get_race_by_round, get_season_schedule


class SeasonScheduleAPIView(APIView):
    def get(self, request, year):
        try:
            schedule = get_season_schedule(year)
            serializer = RaceSerializer(schedule, many=True)
            return Response({"year": year, "races": serializer.data})
        except Exception as exc:
            return Response({"error": str(exc)}, status=500)


class RaceDetailAPIView(APIView):
    def get(self, request, year, round_number):
        try:
            race = get_race_by_round(year, round_number)
            if race is None:
                return Response({"error": "Race not found"}, status=404)
            serializer = RaceSerializer(race)
            return Response(serializer.data)
        except Exception as exc:
            return Response({"error": str(exc)}, status=500)


class DriverStandingsAPIView(APIView):
    def get(self, request, year):
        try:
            standings = get_driver_standings(year)
            serializer = DriverStandingSerializer(standings, many=True)
            return Response({"year": year, "drivers": serializer.data})
        except Exception as exc:
            return Response({"error": str(exc)}, status=500)


class ConstructorStandingsAPIView(APIView):
    def get(self, request, year):
        try:
            standings = get_constructor_standings(year)
            serializer = ConstructorSerializer(standings, many=True)
            return Response({"year": year, "constructors": serializer.data})
        except Exception as exc:
            return Response({"error": str(exc)}, status=500)


class RaceResultsAPIView(APIView):
    def get(self, request, year, round_number):
        try:
            results = get_race_results(year, round_number)
            serializer = RaceResultsSerializer(results)
            return Response({"year": year, "round": round_number, "results": serializer.data})
        except Exception as exc:
            return Response({"error": str(exc)}, status=500)


class QualifyingResultsAPIView(APIView):
    def get(self, request, year, round_number):
        try:
            qualifying = get_qualifying_results(year, round_number)
            serializer = QualifyingResultSerializer(qualifying, many=True)
            return Response({"year": year, "round": round_number, "qualifying": serializer.data})
        except Exception as exc:
            return Response({"error": str(exc)}, status=500)


class PracticeSessionAPIView(APIView):
    def get(self, request, year, round_number, session_name):
        try:
            practice = get_practice_session_results(year, round_number, session_name)
            serializer = PracticeResultSerializer(practice, many=True)
            return Response(
                {
                    "year": year,
                    "round": round_number,
                    "session": str(session_name).upper(),
                    "practice": serializer.data,
                }
            )
        except ValueError as exc:
            return Response({"error": str(exc)}, status=400)
        except Exception as exc:
            return Response({"error": str(exc)}, status=500)
