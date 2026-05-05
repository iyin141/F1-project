from django.test import TestCase

from api.models import DriverLapAnalysis, RaceResultData, SeasonSchedule


class PersistenceCoverageEndpointTests(TestCase):
    def setUp(self):
        SeasonSchedule.objects.create(
            year=2024,
            payload={
                "races": [
                    {
                        "round": 1,
                        "name": "Bahrain Grand Prix",
                        "date": "2024-03-02",
                        "location": "Sakhir",
                        "country": "Bahrain",
                    }
                ]
            },
        )

        RaceResultData.objects.create(
            year=2024,
            round_number=1,
            session="R",
            payload={
                "results": [
                    {
                        "driver_code": "VER",
                        "driver_number": 1,
                        "driver_name": "Max Verstappen",
                        "team": "Red Bull Racing",
                        "position": 1,
                        "points": 25.0,
                        "status": "Finished",
                        "laps": 57,
                    }
                ]
            },
        )

        DriverLapAnalysis.objects.create(
            year=2024,
            round_number=1,
            session="R",
            driver_code="VER",
            payload={
                "stints": [{"stint_number": 1, "compound": "SOFT"}],
                "tyre_strategy": [{"stint_number": 1, "compound": "SOFT"}],
                "pace": {"laps_completed": 57, "session_median_lap_seconds": 95.5},
                "sectors": {"laps_count": 57, "theoretical_best_lap_seconds": 93.666},
            },
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



