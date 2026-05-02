import os
import unittest

from django.test import TestCase

from api.services.constructors import get_constructor_standings
from api.services.drivers import get_driver_standings
from api.services.results import get_practice_session_results, get_qualifying_results, get_race_results
from api.services.schedule import get_season_schedule


RUN_INTEGRATION_TESTS = os.getenv("RUN_INTEGRATION_TESTS") == "1"


@unittest.skipUnless(RUN_INTEGRATION_TESTS, "Set RUN_INTEGRATION_TESTS=1 to run live API integration tests")
class LiveServiceIntegrationTests(TestCase):
    def test_live_schedule_service_returns_non_empty_list(self):
        data = get_season_schedule(2024)

        self.assertIsInstance(data, list)
        self.assertGreater(len(data), 0)
        self.assertIn("name", data[0])
        self.assertIn("round", data[0])

    def test_live_driver_standings_returns_non_empty_list(self):
        data = get_driver_standings(2024)

        self.assertIsInstance(data, dict)
        self.assertIn("meta", data)
        self.assertIn("data", data)
        self.assertTrue(data["meta"]["readiness"]["can_proceed"])
        self.assertGreater(len(data["data"]), 0)
        self.assertIn("driver_name", data["data"][0])
        self.assertIn("points", data["data"][0])

    def test_live_constructor_standings_returns_non_empty_list(self):
        data = get_constructor_standings(2024)

        self.assertIsInstance(data, dict)
        self.assertIn("meta", data)
        self.assertIn("data", data)
        self.assertTrue(data["meta"]["readiness"]["can_proceed"])
        self.assertGreater(len(data["data"]), 0)
        self.assertIn("constructor_name", data["data"][0])
        self.assertIn("points", data["data"][0])

    def test_live_race_results_returns_qualifying_and_race_keys(self):
        data = get_race_results(2024, 1)

        self.assertIsInstance(data, dict)
        self.assertIn("qualifying", data)
        self.assertIn("race", data)
        self.assertGreater(len(data["qualifying"]), 0)
        self.assertGreater(len(data["race"]), 0)

    def test_live_qualifying_service_returns_non_empty_list(self):
        data = get_qualifying_results(2024, 1)

        self.assertIsInstance(data, dict)
        self.assertIn("meta", data)
        self.assertIn("data", data)
        self.assertTrue(data["meta"]["readiness"]["can_proceed"])
        self.assertGreater(len(data["data"]), 0)
        self.assertIn("driver_name", data["data"][0])
        self.assertIn("q1_time", data["data"][0])

    def test_live_practice_service_returns_non_empty_list(self):
        data = get_practice_session_results(2024, 1, "FP1")

        self.assertIsInstance(data, dict)
        self.assertIn("meta", data)
        self.assertIn("data", data)
        self.assertTrue(data["meta"]["readiness"]["can_proceed"])
        self.assertGreater(len(data["data"]), 0)
        self.assertIn("driver_code", data["data"][0])
        self.assertIn("lap_time", data["data"][0])

    def test_live_qualifying_endpoint_returns_payload(self):
        response = self.client.get("/api/races/2024/1/qualifying/")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["year"], 2024)
        self.assertEqual(payload["round"], 1)
        self.assertIn("qualifying", payload)
        self.assertGreater(len(payload["qualifying"]), 0)

    def test_live_practice_endpoint_returns_payload(self):
        response = self.client.get("/api/races/2024/1/practice/fp1/")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["year"], 2024)
        self.assertEqual(payload["round"], 1)
        self.assertEqual(payload["session"], "FP1")
        self.assertIn("practice", payload)
        self.assertGreater(len(payload["practice"]), 0)

    def test_live_practice_endpoint_returns_400_for_invalid_session(self):
        response = self.client.get("/api/races/2024/1/practice/fp4/")

        self.assertEqual(response.status_code, 400)
        payload = response.json()
        self.assertIn("error", payload)
