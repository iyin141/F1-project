from django.test import TestCase

from api.services.store import (
    store_driver_standings,
    store_constructor_standings,
    store_season_schedule,
)
from api.serializers import DriverStandingSerializer, ConstructorSerializer, RaceSerializer


class StoreSerializerAlignmentTest(TestCase):
    def test_driver_standings_serialization(self):
        standings = [
            {
                "position": 1,
                "driver_name": "Lewis Hamilton",
                "points": 25.0,
                "wins": 1,
                "constructor": "Mercedes",
            }
        ]

        record = store_driver_standings(2024, standings)
        self.assertEqual(record.payload.get("standings"), DriverStandingSerializer(standings, many=True).data)

    def test_constructor_standings_serialization(self):
        standings = [
            {"position": 1, "constructor_name": "Mercedes", "points": 613.5, "wins": 12}
        ]

        record = store_constructor_standings(2024, standings)
        self.assertEqual(record.payload.get("standings"), ConstructorSerializer(standings, many=True).data)

    def test_season_schedule_serialization(self):
        races = [
            {"round": 1, "name": "Test GP", "date": None, "location": "Testville", "country": "Testland"}
        ]

        record = store_season_schedule(2024, races)
        self.assertEqual(record.payload.get("races"), RaceSerializer(races, many=True).data)
