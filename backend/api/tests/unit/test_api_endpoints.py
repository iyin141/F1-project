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
            response = self.client.get("/api/races/2024/")

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
            response = self.client.get("/api/races/2024/1/")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["round"], 1)
        self.assertEqual(data["name"], "Bahrain Grand Prix")

    def test_race_detail_endpoint_returns_404_for_missing_race(self):
        with patch("api.views.get_race_by_round", return_value=None):
            response = self.client.get("/api/races/2024/99/")

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
            response = self.client.get("/api/drivers/2024/")

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
            response = self.client.get("/api/constructors/2024/")

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
            response = self.client.get("/api/races/2024/1/results/")

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
            response = self.client.get("/api/races/2024/1/qualifying/")

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
            response = self.client.get("/api/races/2024/1/practice/fp1/")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["year"], 2024)
        self.assertEqual(data["round"], 1)
        self.assertEqual(data["session"], "FP1")
        self.assertEqual(len(data["practice"]), 1)
        self.assertEqual(data["practice"][0]["driver_code"], "VER")

    def test_practice_endpoint_returns_400_for_invalid_session(self):
        with patch("api.views.get_practice_session_results", side_effect=ValueError("session_name must be one of FP1, FP2, FP3")):
            response = self.client.get("/api/races/2024/1/practice/fp4/")

        self.assertEqual(response.status_code, 400)
        self.assertIn("session_name must be one of FP1, FP2, FP3", response.json()["error"])

    def test_analysis_laps_endpoint_returns_payload(self):
        mocked_payload = {
            "meta": {
                "year": 2024,
                "round": 1,
                "session": "R",
                "row_count": 1,
                "limit_max": 2000,
            },
            "filters_applied": {
                "driver": "VER",
                "limit": 5,
            },
            "data": [
                {
                    "driver_code": "VER",
                    "lap_number": 1,
                    "lap_time": "0:01:31.000",
                    "sector1": "0:00:30.000",
                    "sector2": "0:00:30.500",
                    "sector3": "0:00:30.500",
                    "compound": "SOFT",
                    "stint": 1,
                    "is_personal_best": True,
                }
            ],
        }

        with patch("api.views.get_lap_analysis", return_value=mocked_payload) as mocked_service:
            response = self.client.get("/api/analysis/races/2024/1/laps/?session=R&driver=VER&limit=5")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["meta"]["year"], 2024)
        self.assertEqual(payload["meta"]["session"], "R")
        self.assertEqual(payload["filters_applied"]["driver"], "VER")
        self.assertEqual(payload["filters_applied"]["limit"], 5)
        self.assertEqual(len(payload["data"]), 1)
        mocked_service.assert_called_once_with(year=2024, round_number=1, session="R", driver="VER", limit=5)

    def test_analysis_laps_endpoint_returns_400_for_invalid_limit(self):
        response = self.client.get("/api/analysis/races/2024/1/laps/?limit=abc")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "limit must be an integer")

    def test_analysis_laps_endpoint_returns_400_for_invalid_session(self):
        with patch("api.views.get_lap_analysis", side_effect=ValueError("session must be one of R, Q, FP1, FP2, FP3")):
            response = self.client.get("/api/analysis/races/2024/1/laps/?session=FP4")

        self.assertEqual(response.status_code, 400)
        self.assertIn("session must be one of R, Q, FP1, FP2, FP3", response.json()["error"])

    def test_analysis_laps_endpoint_passes_driver_filter(self):
        mocked_payload = {
            "meta": {"year": 2024, "round": 1, "session": "Q", "row_count": 0, "limit_max": 2000},
            "filters_applied": {"driver": "HAM", "limit": None},
            "data": [],
        }

        with patch("api.views.get_lap_analysis", return_value=mocked_payload) as mocked_service:
            response = self.client.get("/api/analysis/races/2024/1/laps/?session=Q&driver=HAM")

        self.assertEqual(response.status_code, 200)
        mocked_service.assert_called_once_with(year=2024, round_number=1, session="Q", driver="HAM", limit=None)

    def test_analysis_laps_endpoint_passes_large_limit_for_service_clamp(self):
        mocked_payload = {
            "meta": {"year": 2024, "round": 1, "session": "R", "row_count": 0, "limit_max": 2000},
            "filters_applied": {"driver": None, "limit": 2000},
            "data": [],
        }

        with patch("api.views.get_lap_analysis", return_value=mocked_payload) as mocked_service:
            response = self.client.get("/api/analysis/races/2024/1/laps/?limit=999999")

        self.assertEqual(response.status_code, 200)
        mocked_service.assert_called_once_with(year=2024, round_number=1, session="R", driver=None, limit=999999)

    def test_analysis_stints_endpoint_returns_payload(self):
        mocked_payload = {
            "meta": {
                "year": 2024,
                "round": 1,
                "session": "R",
                "row_count": 1,
                "limit_max": 2000,
            },
            "filters_applied": {
                "driver": "VER",
                "limit": 5,
            },
            "data": [
                {
                    "driver_code": "VER",
                    "driver_number": 1,
                    "stint_number": 1,
                    "compound": "SOFT",
                    "lap_start": 1,
                    "lap_end": 15,
                    "total_laps": 15,
                    "median_lap_seconds": 95.234,
                    "min_lap_seconds": 94.789,
                    "max_lap_seconds": 96.012,
                }
            ],
        }

        with patch("api.views.get_stint_analysis", return_value=mocked_payload) as mocked_service:
            response = self.client.get("/api/analysis/races/2024/1/stints/?session=R&driver=VER&limit=5")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["meta"]["year"], 2024)
        self.assertEqual(payload["meta"]["session"], "R")
        self.assertEqual(payload["filters_applied"]["driver"], "VER")
        self.assertEqual(payload["filters_applied"]["limit"], 5)
        self.assertEqual(len(payload["data"]), 1)
        mocked_service.assert_called_once_with(year=2024, round_number=1, session="R", driver="VER", limit=5)

    def test_analysis_stints_endpoint_returns_400_for_invalid_limit(self):
        response = self.client.get("/api/analysis/races/2024/1/stints/?limit=abc")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "limit must be an integer")

    def test_analysis_stints_endpoint_returns_400_for_invalid_session(self):
        with patch("api.views.get_stint_analysis", side_effect=ValueError("session must be one of R, Q, FP1, FP2, FP3")):
            response = self.client.get("/api/analysis/races/2024/1/stints/?session=FP4")

        self.assertEqual(response.status_code, 400)
        self.assertIn("session must be one of R, Q, FP1, FP2, FP3", response.json()["error"])

    def test_analysis_pace_endpoint_returns_payload(self):
        mocked_payload = {
            "meta": {
                "year": 2024,
                "round": 1,
                "session": "Q",
                "row_count": 1,
                "limit_max": 2000,
            },
            "filters_applied": {
                "driver": "HAM",
                "limit": 10,
            },
            "data": [
                {
                    "driver_code": "HAM",
                    "driver_number": 44,
                    "laps_completed": 12,
                    "session_median_lap_seconds": 91.772,
                    "session_best_lap_seconds": 90.992,
                    "consistency_stddev_seconds": 0.321,
                    "pace_improvement_seconds": 0.456,
                }
            ],
        }

        with patch("api.views.get_pace_analysis", return_value=mocked_payload) as mocked_service:
            response = self.client.get("/api/analysis/races/2024/1/pace/?session=Q&driver=HAM&limit=10")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["meta"]["year"], 2024)
        self.assertEqual(payload["meta"]["session"], "Q")
        self.assertEqual(payload["filters_applied"]["driver"], "HAM")
        self.assertEqual(payload["filters_applied"]["limit"], 10)
        self.assertEqual(len(payload["data"]), 1)
        mocked_service.assert_called_once_with(year=2024, round_number=1, session="Q", driver="HAM", limit=10)

    def test_analysis_pace_endpoint_returns_400_for_invalid_limit(self):
        response = self.client.get("/api/analysis/races/2024/1/pace/?limit=abc")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "limit must be an integer")

    def test_analysis_pace_endpoint_returns_400_for_invalid_session(self):
        with patch("api.views.get_pace_analysis", side_effect=ValueError("session must be one of R, Q, FP1, FP2, FP3")):
            response = self.client.get("/api/analysis/races/2024/1/pace/?session=FP4")

        self.assertEqual(response.status_code, 400)
        self.assertIn("session must be one of R, Q, FP1, FP2, FP3", response.json()["error"])

    def test_analysis_telemetry_endpoint_returns_payload(self):
        mocked_payload = {
            "meta": {
                "year": 2024,
                "round": 1,
                "session": "R",
                "row_count": 2,
                "limit_max": 3000,
            },
            "filters_applied": {
                "driver": "VER",
                "lap": 12,
                "limit_points": 500,
                "stride": 2,
            },
            "data": [
                {
                    "time_seconds": 0.0,
                    "distance_m": 0.0,
                    "speed_kph": 278.5,
                    "throttle_pct": 100.0,
                    "brake": False,
                    "rpm": 12450,
                    "gear": 8,
                },
                {
                    "time_seconds": 0.1,
                    "distance_m": 14.6,
                    "speed_kph": 279.2,
                    "throttle_pct": 100.0,
                    "brake": False,
                    "rpm": 12510,
                    "gear": 8,
                },
            ],
        }

        with patch("api.views.get_telemetry_snapshot", return_value=mocked_payload) as mocked_service:
            response = self.client.get(
                "/api/analysis/races/2024/1/telemetry/?session=R&driver=VER&lap=12&limit_points=500&stride=2"
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["meta"]["year"], 2024)
        self.assertEqual(payload["meta"]["session"], "R")
        self.assertEqual(payload["filters_applied"]["driver"], "VER")
        self.assertEqual(payload["filters_applied"]["lap"], 12)
        self.assertEqual(payload["filters_applied"]["limit_points"], 500)
        self.assertEqual(payload["filters_applied"]["stride"], 2)
        self.assertEqual(len(payload["data"]), 2)
        mocked_service.assert_called_once_with(
            year=2024,
            round_number=1,
            session="R",
            driver="VER",
            lap=12,
            limit_points=500,
            stride=2,
            sector_start=None,
            sector_end=None,
        )

    def test_analysis_telemetry_endpoint_passes_sector_window(self):
        mocked_payload = {
            "meta": {
                "year": 2024,
                "round": 1,
                "session": "Q",
                "row_count": 1,
                "limit_max": 3000,
            },
            "filters_applied": {
                "driver": "VER",
                "lap": 1,
                "limit_points": 120,
                "stride": 1,
                "sector_start": 2,
                "sector_end": 3,
            },
            "data": [
                {
                    "time_seconds": 1.2,
                    "distance_m": 2050.0,
                    "speed_kph": 298.2,
                    "throttle_pct": 100.0,
                    "brake": False,
                    "rpm": 12500,
                    "gear": 8,
                }
            ],
        }

        with patch("api.views.get_telemetry_snapshot", return_value=mocked_payload) as mocked_service:
            response = self.client.get(
                "/api/analysis/races/2024/1/telemetry/?session=Q&driver=VER&lap=1&limit_points=120&sector_start=2&sector_end=3"
            )

        self.assertEqual(response.status_code, 200)
        mocked_service.assert_called_once_with(
            year=2024,
            round_number=1,
            session="Q",
            driver="VER",
            lap=1,
            limit_points=120,
            stride=1,
            sector_start=2,
            sector_end=3,
        )

    def test_analysis_telemetry_endpoint_returns_400_for_missing_driver(self):
        response = self.client.get("/api/analysis/races/2024/1/telemetry/?session=R&lap=12")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "driver query parameter is required")

    def test_analysis_telemetry_endpoint_returns_400_for_missing_lap(self):
        response = self.client.get("/api/analysis/races/2024/1/telemetry/?session=R&driver=VER")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "lap query parameter is required")

    def test_analysis_telemetry_endpoint_returns_400_for_invalid_limit_points(self):
        response = self.client.get("/api/analysis/races/2024/1/telemetry/?session=R&driver=VER&lap=12&limit_points=abc")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "limit_points must be an integer")

    def test_analysis_telemetry_endpoint_returns_400_for_invalid_stride(self):
        response = self.client.get("/api/analysis/races/2024/1/telemetry/?session=R&driver=VER&lap=12&stride=abc")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "stride must be an integer")

    def test_analysis_telemetry_endpoint_returns_400_for_invalid_session(self):
        with patch("api.views.get_telemetry_snapshot", side_effect=ValueError("session must be one of R, Q, FP1, FP2, FP3")):
            response = self.client.get("/api/analysis/races/2024/1/telemetry/?session=FP4&driver=VER&lap=12")

        self.assertEqual(response.status_code, 400)
        self.assertIn("session must be one of R, Q, FP1, FP2, FP3", response.json()["error"])

    def test_analysis_telemetry_overlay_endpoint_returns_payload(self):
        mocked_payload = {
            "meta": {
                "year": 2024,
                "round": 1,
                "session": "Q",
                "row_count": 4,
                "limit_max": 3000,
            },
            "filters_applied": {
                "driver_a": "VER",
                "driver_b": "HAM",
                "lap_a": 1,
                "lap_b": 2,
                "limit_points": 100,
                "stride": 2,
                "sector_start": 1,
                "sector_end": 2,
            },
            "traces": [
                {
                    "driver": "VER",
                    "lap": 1,
                    "data": [
                        {
                            "time_seconds": 0.0,
                            "distance_m": 0.0,
                            "speed_kph": 280.0,
                            "throttle_pct": 100.0,
                            "brake": False,
                            "rpm": 12400,
                            "gear": 8,
                        }
                    ],
                },
                {
                    "driver": "HAM",
                    "lap": 2,
                    "data": [
                        {
                            "time_seconds": 0.0,
                            "distance_m": 0.0,
                            "speed_kph": 276.0,
                            "throttle_pct": 99.0,
                            "brake": False,
                            "rpm": 12300,
                            "gear": 8,
                        }
                    ],
                },
            ],
        }

        with patch("api.views.get_telemetry_overlay", return_value=mocked_payload) as mocked_service:
            response = self.client.get(
                "/api/analysis/races/2024/1/telemetry/overlay/?session=Q&driver_a=VER&driver_b=HAM&lap_a=1&lap_b=2&limit_points=100&stride=2&sector_start=1&sector_end=2"
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["meta"]["session"], "Q")
        self.assertEqual(len(payload["traces"]), 2)
        mocked_service.assert_called_once_with(
            year=2024,
            round_number=1,
            session="Q",
            driver_a="VER",
            driver_b="HAM",
            lap_a=1,
            lap_b=2,
            limit_points=100,
            stride=2,
            sector_start=1,
            sector_end=2,
        )

    def test_analysis_telemetry_overlay_endpoint_returns_400_for_missing_drivers(self):
        response = self.client.get("/api/analysis/races/2024/1/telemetry/overlay/?session=Q&driver_a=VER")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "driver_a and driver_b query parameters are required")

    def test_analysis_telemetry_summary_endpoint_returns_payload(self):
        mocked_payload = {
            "meta": {
                "year": 2024,
                "round": 1,
                "session": "R",
                "row_count": 120,
                "limit_max": 3000,
            },
            "filters_applied": {
                "driver": "VER",
                "lap": 12,
                "stride": 2,
                "sector_start": 1,
                "sector_end": 3,
            },
            "summary": {
                "max_speed_kph": 325.21,
                "braking_zones": 8,
                "throttle_on_percentage": 61.3,
                "samples": 120,
            },
        }

        with patch("api.views.get_telemetry_summary", return_value=mocked_payload) as mocked_service:
            response = self.client.get(
                "/api/analysis/races/2024/1/telemetry/summary/?session=R&driver=VER&lap=12&stride=2&sector_start=1&sector_end=3"
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["summary"]["braking_zones"], 8)
        mocked_service.assert_called_once_with(
            year=2024,
            round_number=1,
            session="R",
            driver="VER",
            lap=12,
            stride=2,
            sector_start=1,
            sector_end=3,
        )

    def test_analysis_telemetry_summary_endpoint_returns_400_for_missing_lap(self):
        response = self.client.get("/api/analysis/races/2024/1/telemetry/summary/?session=R&driver=VER")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "lap query parameter is required")
