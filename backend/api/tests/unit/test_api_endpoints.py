from django.test import TestCase
from unittest.mock import patch


class ApiEndpointTests(TestCase):
    def test_races_by_year_endpoint_returns_schedule_payload(self):
        mocked_schedule = [
            {
                "round": 1,
                "name": "Bahrain Grand Prix",
                "date": "2024-03-02",
                "location": "Sakhir",
                "country": "Bahrain",
            }
        ]

        with patch("api.views.get_season_schedule", return_value=mocked_schedule):
            response = self.client.get("/races/2024/")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["year"], 2024)
        self.assertEqual(len(data["races"]), 1)
        self.assertEqual(data["races"][0]["name"], "Bahrain Grand Prix")

    def test_race_detail_endpoint_returns_single_race(self):
        mocked_race = {
            "round": 1,
            "name": "Bahrain Grand Prix",
            "date": "2024-03-02",
            "location": "Sakhir",
            "country": "Bahrain",
        }

        with patch("api.views.get_race_by_round", return_value=mocked_race):
            response = self.client.get("/races/2024/1/")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["round"], 1)
        self.assertEqual(data["name"], "Bahrain Grand Prix")

    def test_race_detail_endpoint_returns_404_for_missing_race(self):
        with patch("api.views.get_race_by_round", return_value=None):
            response = self.client.get("/races/2024/99/")

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["error"], "Race not found")

    def test_driver_standings_endpoint_returns_expected_shape(self):
        mocked_drivers = [
            {
                "position": 1,
                "driver_name": "Max Verstappen",
                "points": 575.0,
                "wins": 19,
                "constructor": "Red Bull Racing",
            }
        ]

        with patch("api.views.get_driver_standings", return_value=mocked_drivers):
            response = self.client.get("/drivers/2024/")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["year"], 2024)
        self.assertEqual(data["drivers"][0]["driver_name"], "Max Verstappen")

    def test_constructor_standings_endpoint_returns_expected_shape(self):
        mocked_constructors = [
            {
                "position": 1,
                "constructor_name": "Red Bull Racing",
                "points": 860.0,
                "wins": 21,
            }
        ]

        with patch("api.views.get_constructor_standings", return_value=mocked_constructors):
            response = self.client.get("/constructors/2024/")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["year"], 2024)
        self.assertEqual(data["constructors"][0]["constructor_name"], "Red Bull Racing")

    def test_race_results_endpoint_returns_nested_results_payload(self):
        mocked_results = {
            "qualifying": [
                {
                    "position": 1,
                    "driver_number": 1,
                    "driver_name": "Max Verstappen",
                    "team": "Red Bull Racing",
                    "q1_time": "0:01:30.000",
                    "q2_time": "0:01:29.500",
                    "q3_time": "0:01:29.200",
                }
            ],
            "race": [
                {
                    "position": 1,
                    "driver_number": 1,
                    "driver_name": "Max Verstappen",
                    "team": "Red Bull Racing",
                    "points": 26,
                    "status": "Finished",
                    "grid_position": 1,
                    "laps": 57,
                }
            ],
        }

        with patch("api.views.get_race_results", return_value=mocked_results):
            response = self.client.get("/races/2024/1/results/")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["year"], 2024)
        self.assertEqual(data["round"], 1)
        self.assertEqual(len(data["results"]["qualifying"]), 1)
        self.assertEqual(len(data["results"]["race"]), 1)

    def test_qualifying_endpoint_returns_qualifying_payload(self):
        mocked_qualifying = [
            {
                "position": 1,
                "driver_number": 1,
                "driver_name": "Max Verstappen",
                "team": "Red Bull Racing",
                "q1_time": "0:01:30.000",
                "q2_time": "0:01:29.500",
                "q3_time": "0:01:29.200",
            }
        ]

        with patch("api.views.get_qualifying_results", return_value=mocked_qualifying):
            response = self.client.get("/races/2024/1/qualifying/")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["year"], 2024)
        self.assertEqual(data["round"], 1)
        self.assertEqual(len(data["qualifying"]), 1)
        self.assertEqual(data["qualifying"][0]["driver_name"], "Max Verstappen")

    def test_practice_endpoint_returns_practice_payload(self):
        mocked_practice = [
            {
                "position": 1,
                "driver_code": "VER",
                "team": "Red Bull Racing",
                "lap_time": "0:01:31.000",
                "lap_number": 12,
            }
        ]

        with patch("api.views.get_practice_session_results", return_value=mocked_practice):
            response = self.client.get("/races/2024/1/practice/fp1/")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["year"], 2024)
        self.assertEqual(data["round"], 1)
        self.assertEqual(data["session"], "FP1")
        self.assertEqual(len(data["practice"]), 1)
        self.assertEqual(data["practice"][0]["driver_code"], "VER")

    def test_practice_endpoint_returns_400_for_invalid_session(self):
        with patch("api.views.get_practice_session_results", side_effect=ValueError("session_name must be one of FP1, FP2, FP3")):
            response = self.client.get("/races/2024/1/practice/fp4/")

        self.assertEqual(response.status_code, 400)
        self.assertIn("session_name must be one of FP1, FP2, FP3", response.json()["error"])
