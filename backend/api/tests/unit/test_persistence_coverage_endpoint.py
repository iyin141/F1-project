from datetime import date

from django.test import TestCase
from django.utils import timezone

from api.models import DriverMetric, Race, RaceResult, SectorAggregate, StintData


class PersistenceCoverageEndpointTests(TestCase):
    def setUp(self):
        race = Race.objects.create(
            season=2024,
            round_number=1,
            race_name="Bahrain Grand Prix",
            circuit_name="Bahrain International Circuit",
            country="Bahrain",
            location="Sakhir",
            race_date=date(2024, 3, 2),
            status=Race.Status.COMPLETED,
            populated_at=timezone.now(),
        )

        RaceResult.objects.create(
            race=race,
            driver_code="VER",
            driver_number=1,
            driver_name="Max Verstappen",
            constructor_name="Red Bull Racing",
            finish_position=1,
            points=25,
        )
        StintData.objects.create(
            race=race,
            driver_code="VER",
            driver_number=1,
            stint_number=1,
            compound="SOFT",
            lap_start=1,
            lap_end=20,
            laps_in_stint=20,
            computed_at=timezone.now(),
        )
        DriverMetric.objects.create(
            race=race,
            season=2024,
            driver_code="VER",
            valid_lap_count=57,
            season_aggregate=False,
            formula_version="consistency_v1",
            computed_at=timezone.now(),
        )
        SectorAggregate.objects.create(
            race=race,
            driver_code="VER",
            driver_number=1,
            laps_count=57,
            computed_at=timezone.now(),
        )

    def test_persistence_coverage_endpoint_returns_db_first_flags(self):
        response = self.client.get("/api/coverage/persistence/2024/1/")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["race_count"], 1)
        self.assertEqual(payload["coverage"][0]["round"], 1)
        self.assertTrue(payload["coverage"][0]["db_first_flags"]["analysis_sector"])
        self.assertTrue(payload["coverage"][0]["db_first_flags"]["all_db_first_ready"])
        self.assertTrue(payload["readiness"]["can_proceed"])
        self.assertEqual(payload["readiness"]["available_data"], ["persistence_coverage"])

    def test_persistence_coverage_endpoint_returns_season_payload(self):
        response = self.client.get("/api/coverage/persistence/2024/")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["season"], 2024)
        self.assertEqual(payload["race_count"], 1)

    def test_persistence_coverage_endpoint_returns_message_when_empty(self):
        response = self.client.get("/api/coverage/persistence/2025/99/")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["race_count"], 0)
        self.assertFalse(payload["readiness"]["can_proceed"])
        self.assertIn("persistence_coverage", payload["readiness"]["unavailable_data"])
        self.assertTrue(payload["readiness"]["message"])