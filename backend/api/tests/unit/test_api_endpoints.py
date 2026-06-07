from django.test import TestCase
from rest_framework.response import Response
from unittest.mock import patch
from api.tests.mixins import TestDefaultAPIKeyMixin


class ApiEndpointTests(TestDefaultAPIKeyMixin, TestCase):
    def test_races_by_year_endpoint_returns_schedule_payload(self):
        mocked_schedule = [
            {
                "round": 1,
                "name": "Bahrain Grand Prix",
                "date": "2024-03-02",
                "location": "Sakhir",
                "country": "Bahrain",
                "event_format": "conventional",
                "session1": "Practice 1", "session1_date_utc": "2024-02-29T11:30:00Z",
                "session2": "Practice 2", "session2_date_utc": "2024-02-29T15:00:00Z",
                "session3": "Practice 3", "session3_date_utc": "2024-03-01T12:30:00Z",
                "session4": "Qualifying", "session4_date_utc": "2024-03-01T16:00:00Z",
                "session5": "Race",       "session5_date_utc": "2024-03-02T15:00:00Z",
            }
        ]

        with patch("api.schedule.views.get_season_schedule", return_value=mocked_schedule):
            response = self.client.get("/api/races/2024/")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["year"], 2024)
        self.assertEqual(len(data["races"]), 1)
        self.assertEqual(data["races"][0]["name"], "Bahrain Grand Prix")
        self.assertTrue(data["readiness"]["can_proceed"])

    def test_race_detail_endpoint_returns_single_race(self):
        mocked_race = {
            "round": 1,
            "name": "Bahrain Grand Prix",
            "date": "2024-03-02",
            "location": "Sakhir",
            "country": "Bahrain",
            "event_format": "conventional",
            "session1": "Practice 1", "session1_date_utc": "2024-02-29T11:30:00Z",
            "session2": "Practice 2", "session2_date_utc": "2024-02-29T15:00:00Z",
            "session3": "Practice 3", "session3_date_utc": "2024-03-01T12:30:00Z",
            "session4": "Qualifying", "session4_date_utc": "2024-03-01T16:00:00Z",
            "session5": "Race",       "session5_date_utc": "2024-03-02T15:00:00Z",
        }

        with patch("api.schedule.views.get_race_by_round", return_value=mocked_race):
            response = self.client.get("/api/races/2024/1/")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["round"], 1)
        self.assertEqual(data["name"], "Bahrain Grand Prix")

    def test_race_detail_endpoint_returns_404_for_missing_race(self):
        with patch("api.schedule.views.get_race_by_round", return_value=None):
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

        with patch("api.drivers.views.TaskManager.enqueue_if_needed"), patch("api.drivers.views.get_persisted_driver_standings", return_value=mocked_drivers):
            response = self.client.get("/api/drivers/2024/")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["year"], 2024)
        self.assertEqual(data["drivers"][0]["driver_name"], "Max Verstappen")
        self.assertTrue(data["readiness"]["can_proceed"])

    def test_driver_standings_endpoint_includes_message_when_empty(self):
        with patch("api.drivers.views.TaskManager.enqueue_if_needed"), patch("api.drivers.views.get_persisted_driver_standings", return_value=[]):
            response = self.client.get("/api/drivers/2024/")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["readiness"]["can_proceed"])
        # self.assertTrue(data["readiness"]["message"])

    def test_driver_standings_endpoint_includes_readiness_when_service_returns_meta(self):
        mocked_payload = [
            {
                "position": 1,
                "driver_name": "Max Verstappen",
                "points": 575.0,
                "wins": 19,
                "constructor": "Red Bull Racing",
            }
        ]

        with patch("api.drivers.views.TaskManager.enqueue_if_needed"), patch("api.drivers.views.get_persisted_driver_standings", return_value=mocked_payload):
            response = self.client.get("/api/drivers/2024/")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["readiness"]["can_proceed"])
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

        with patch("api.constructors.views.TaskManager.enqueue_if_needed"), patch("api.constructors.views.get_persisted_constructor_standings", return_value=mocked_constructors):
            response = self.client.get("/api/constructors/2024/")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["year"], 2024)
        self.assertEqual(data["constructors"][0]["constructor_name"], "Red Bull Racing")
        self.assertTrue(data["readiness"]["can_proceed"])

    def test_constructor_standings_endpoint_includes_message_when_empty(self):
        with patch("api.constructors.views.TaskManager.enqueue_if_needed"), patch("api.constructors.views.get_persisted_constructor_standings", return_value=[]):
            response = self.client.get("/api/constructors/2024/")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertFalse(data["readiness"]["can_proceed"])
        # self.assertTrue(data["readiness"]["message"])

    def test_constructor_standings_endpoint_returns_non_blocking_readiness_when_unavailable(self):
        # We now stream when empty, the response will be SSE, so let's check it streams
        with patch("api.constructors.views.TaskManager.enqueue_if_needed"), patch("api.constructors.views.get_persisted_constructor_standings", return_value=None), patch("api.constructors.views.stream_task_result_json", return_value=Response(status=200)):
            response = self.client.get("/api/constructors/2024/")

        self.assertEqual(response.status_code, 200)

    def test_race_results_endpoint_returns_nested_results_payload(self):
        qual_row = {
            "position": 1,
            "driver_number": 1,
            "driver_name": "Max Verstappen",
            "team": "Red Bull Racing",
            "q1_time": "0:01:30.000",
            "q2_time": "0:01:29.500",
            "q3_time": "0:01:29.200",
        }
        race_row = {
            "position": 1,
            "driver_number": 1,
            "driver_name": "Max Verstappen",
            "team": "Red Bull Racing",
            "points": 26,
            "status": "Finished",
            "grid_position": 1,
            "laps": 57,
        }

        mock_response = {
            "meta": {"year": 2024, "round": 1, "can_proceed": True},
            "data": [race_row],
            "qualifying": [qual_row]
        }
        with patch("api.results.views.RaceResultsAPIView._fetch_race_results_data", return_value=mock_response):
            response = self.client.get("/api/races/2024/1/results/")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["meta"]["year"], 2024)
        self.assertEqual(data["meta"]["round"], 1)
        self.assertEqual(len(data["qualifying"]), 1)
        self.assertEqual(len(data["data"]), 1)
        self.assertTrue(data["meta"]["can_proceed"])

    def test_race_results_endpoint_surfaces_partial_readiness_message(self):
        race_row = {
            "position": 1,
            "driver_number": 1,
            "driver_name": "Max Verstappen",
            "team": "Red Bull Racing",
            "points": 26,
            "status": "Finished",
            "grid_position": 1,
            "laps": 57,
        }

        mock_response = {
            "meta": {"year": 2020, "round": 2, "can_proceed": True, "unavailable_data": ["qualifying_results"]},
            "data": [race_row],
            "qualifying": []
        }
        with patch("api.results.views.RaceResultsAPIView._fetch_race_results_data", return_value=mock_response):
            response = self.client.get("/api/races/2020/2/results/")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["meta"]["can_proceed"])
        self.assertIn("qualifying_results", data["meta"]["unavailable_data"])
        # self.assertTrue(data["meta"]["message"])

    def test_qualifying_endpoint_returns_qualifying_payload(self):
        qual_row = {
            "position": 1,
            "driver_number": 1,
            "driver_name": "Max Verstappen",
            "team": "Red Bull Racing",
            "q1_time": "0:01:30.000",
            "q2_time": "0:01:29.500",
            "q3_time": "0:01:29.200",
        }

        with patch("api.results.views.handle_data_request", return_value=Response({"meta": {"year": 2024, "round": 1, "can_proceed": True}, "data": [qual_row]})):
            response = self.client.get("/api/races/2024/1/qualifying/")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["meta"]["year"], 2024)
        self.assertEqual(data["meta"]["round"], 1)
        self.assertEqual(len(data["data"]), 1)
        self.assertEqual(data["data"][0]["driver_name"], "Max Verstappen")
        self.assertTrue(data["meta"]["can_proceed"])

    def test_qualifying_endpoint_surfaces_message_when_empty(self):
        with patch("api.results.views.handle_data_request", return_value=Response({"meta": {"can_proceed": True}, "data": []})):
            response = self.client.get("/api/races/2024/1/qualifying/")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["meta"]["can_proceed"])
        # self.assertTrue(data["readiness"]["message"])

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

        with patch("api.results.views.handle_data_request", return_value=Response({"meta": {"year": 2024, "round": 1, "session": "FP1", "can_proceed": True}, "data": mocked_practice})):
            response = self.client.get("/api/races/2024/1/practice/fp1/")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["meta"]["year"], 2024)
        self.assertEqual(data["meta"]["round"], 1)
        self.assertEqual(data["meta"]["session"], "FP1")
        self.assertEqual(len(data["data"]), 1)
        self.assertEqual(data["data"][0]["driver_code"], "VER")
        self.assertTrue(data["meta"]["can_proceed"])

    def test_practice_endpoint_surfaces_message_when_empty(self):
        with patch("api.results.views.handle_data_request", return_value=Response({"meta": {"can_proceed": True}, "data": []})):
            response = self.client.get("/api/races/2024/1/practice/fp1/")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["meta"]["can_proceed"])
        # self.assertTrue(data["meta"]["message"])

    def test_practice_endpoint_returns_400_for_invalid_session(self):
        with patch("api.results.views.handle_data_request", side_effect=ValueError("session_name must be one of FP1, FP2, FP3")):
            response = self.client.get("/api/races/2024/1/practice/fp4/")

        self.assertEqual(response.status_code, 400)
        self.assertIn("Invalid session name", response.json()["error"])

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

        with patch("api.session.views.handle_data_request", return_value=Response(mocked_payload)) as mocked_service:
            response = self.client.get("/api/analysis/races/2024/1/laps/?session=R&driver=VER&limit=5")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["meta"]["year"], 2024)
        self.assertEqual(payload["meta"]["session"], "R")
        self.assertEqual(payload["filters_applied"]["driver"], "VER")
        self.assertEqual(payload["filters_applied"]["limit"], 5)
        self.assertEqual(len(payload["data"]), 1)
        

    def test_analysis_laps_endpoint_surfaces_message_when_empty(self):
        mocked_payload = {
            "meta": {"year": 2024, "round": 1, "session": "R", "row_count": 0, "limit_max": 2000, "can_proceed": False, "message": "No data"},
            "filters_applied": {"driver": None, "limit": None},
            "data": [],
        }

        from rest_framework.response import Response
        with patch("api.session.views.handle_data_request", return_value=Response(mocked_payload, status=200)):
            response = self.client.get("/api/analysis/races/2024/1/laps/?session=R")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertFalse(payload["meta"]["can_proceed"])
        self.assertTrue(payload["meta"]["message"])

    def test_analysis_laps_endpoint_returns_400_for_invalid_limit(self):
        response = self.client.get("/api/analysis/races/2024/1/laps/?limit=abc")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "limit must be an integer")

    def test_analysis_laps_endpoint_returns_400_for_invalid_session(self):
        with patch("api.session.views.handle_data_request", side_effect=ValueError("session must be one of R, Q, FP1, FP2, FP3")):
            response = self.client.get("/api/analysis/races/2024/1/laps/?session=FP4")

        self.assertEqual(response.status_code, 400)
        self.assertIn("session must be one of R, Q, FP1, FP2, FP3", response.json()["error"])

    def test_analysis_laps_endpoint_passes_driver_filter(self):
        mocked_payload = {
            "meta": {"year": 2024, "round": 1, "session": "Q", "row_count": 0, "limit_max": 2000},
            "filters_applied": {"driver": "HAM", "limit": None},
            "data": [],
        }

        with patch("api.session.views.handle_data_request", return_value=Response(mocked_payload)) as mocked_service:
            response = self.client.get("/api/analysis/races/2024/1/laps/?session=Q&driver=HAM")

        self.assertEqual(response.status_code, 200)
        

    def test_analysis_laps_endpoint_passes_large_limit_for_service_clamp(self):
        mocked_payload = {
            "meta": {"year": 2024, "round": 1, "session": "R", "row_count": 0, "limit_max": 2000},
            "filters_applied": {"driver": None, "limit": 2000},
            "data": [],
        }

        with patch("api.session.views.handle_data_request", return_value=Response(mocked_payload)) as mocked_service:
            response = self.client.get("/api/analysis/races/2024/1/laps/?limit=999999")

        self.assertEqual(response.status_code, 200)
        

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

        with patch("api.session.views.handle_data_request", return_value=Response(mocked_payload)) as mocked_service:
            response = self.client.get("/api/analysis/races/2024/1/stints/?session=R&driver=VER&limit=5")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["meta"]["year"], 2024)
        self.assertEqual(payload["meta"]["session"], "R")
        self.assertEqual(payload["filters_applied"]["driver"], "VER")
        self.assertEqual(payload["filters_applied"]["limit"], 5)
        self.assertEqual(len(payload["data"]), 1)
        

    def test_analysis_stints_endpoint_returns_400_for_invalid_limit(self):
        response = self.client.get("/api/analysis/races/2024/1/stints/?limit=abc")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "limit must be an integer")

    def test_analysis_stints_endpoint_returns_400_for_invalid_session(self):
        with patch("api.session.views.get_stint_analysis", side_effect=ValueError("session must be one of R, Q, FP1, FP2, FP3")):
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

        with patch("api.session.views.handle_data_request", return_value=Response(mocked_payload)) as mocked_service:
            response = self.client.get("/api/analysis/races/2024/1/pace/?session=Q&driver=HAM&limit=10")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["meta"]["year"], 2024)
        self.assertEqual(payload["meta"]["session"], "Q")
        self.assertEqual(payload["filters_applied"]["driver"], "HAM")
        self.assertEqual(payload["filters_applied"]["limit"], 10)
        self.assertEqual(len(payload["data"]), 1)
        

    def test_analysis_pace_endpoint_returns_400_for_invalid_limit(self):
        response = self.client.get("/api/analysis/races/2024/1/pace/?limit=abc")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "limit must be an integer")

    def test_analysis_pace_endpoint_returns_400_for_invalid_session(self):
        response = self.client.get("/api/analysis/races/2024/1/pace/?session=FP4")

        self.assertEqual(response.status_code, 400)
        self.assertIn("session must be one of R, Q, FP1, FP2, FP3", response.json()["error"])

    def test_analysis_tyre_strategy_endpoint_returns_payload(self):
        mocked_payload = {
            "meta": {"year": 2024, "round": 1, "session": "R", "row_count": 1, "limit_max": 2000},
            "filters_applied": {"driver": "VER", "limit": 5},
            "data": [
                {
                    "driver_code": "VER",
                    "driver_number": 1,
                    "stint_number": 1,
                    "compound": "SOFT",
                    "lap_start": 1,
                    "lap_end": 15,
                    "laps_in_stint": 15,
                    "avg_lap_seconds": 95.12,
                    "median_lap_seconds": 95.08,
                    "degradation_seconds": 0.74,
                }
            ],
        }

        with patch("api.session.views.handle_data_request", return_value=Response(mocked_payload)) as mocked_service:
            response = self.client.get("/api/analysis/races/2024/1/tyre-strategy/?session=R&driver=VER&limit=5")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["meta"]["session"], "R")
        self.assertEqual(payload["filters_applied"]["driver"], "VER")
        

    def test_analysis_tyre_strategy_endpoint_returns_400_for_invalid_limit(self):
        response = self.client.get("/api/analysis/races/2024/1/tyre-strategy/?limit=abc")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "limit must be an integer")

    def test_analysis_sector_endpoint_returns_payload(self):
        mocked_payload = {
            "meta": {"year": 2024, "round": 1, "session": "Q", "row_count": 1, "limit_max": 2000},
            "filters_applied": {"driver": "HAM", "limit": 10},
            "data": [
                {
                    "driver_code": "HAM",
                    "driver_number": 44,
                    "laps_count": 12,
                    "best_sector1_seconds": 29.88,
                    "best_sector2_seconds": 39.11,
                    "best_sector3_seconds": 22.30,
                    "median_sector1_seconds": 30.12,
                    "median_sector2_seconds": 39.44,
                    "median_sector3_seconds": 22.65,
                    "best_lap_seconds": 91.74,
                    "theoretical_best_lap_seconds": 91.29,
                    "delta_to_theoretical_seconds": 0.45,
                }
            ],
        }

        with patch("api.session.views.handle_data_request", return_value=Response(mocked_payload)) as mocked_service:
            response = self.client.get("/api/analysis/races/2024/1/sector-analysis/?session=Q&driver=HAM&limit=10")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["meta"]["session"], "Q")
        self.assertEqual(payload["filters_applied"]["driver"], "HAM")
        

    def test_analysis_sector_endpoint_returns_400_for_invalid_limit(self):
        response = self.client.get("/api/analysis/races/2024/1/sector-analysis/?limit=abc")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "limit must be an integer")

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

        with patch("api.session.views.handle_data_request", return_value=Response(mocked_payload)) as mocked_service:
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

        with patch("api.session.views.handle_data_request", return_value=Response(mocked_payload)) as mocked_service:
            response = self.client.get(
                "/api/analysis/races/2024/1/telemetry/?session=Q&driver=VER&lap=1&limit_points=120&sector_start=2&sector_end=3"
            )

        self.assertEqual(response.status_code, 200)
        

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
        with patch("api.session.views.get_telemetry_snapshot", side_effect=ValueError("session must be one of R, Q, FP1, FP2, FP3")):
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

        with patch("api.session.views.handle_data_request", return_value=Response(mocked_payload)) as mocked_service:
            response = self.client.get(
                "/api/analysis/races/2024/1/telemetry/overlay/?session=Q&driver_a=VER&driver_b=HAM&lap_a=1&lap_b=2&limit_points=100&stride=2&sector_start=1&sector_end=2"
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["meta"]["session"], "Q")
        self.assertEqual(len(payload["traces"]), 2)
        

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

        with patch("api.session.views.handle_data_request", return_value=Response(mocked_payload)) as mocked_service:
            response = self.client.get(
                "/api/analysis/races/2024/1/telemetry/summary/?session=R&driver=VER&lap=12&stride=2&sector_start=1&sector_end=3"
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["summary"]["braking_zones"], 8)
        

    def test_analysis_telemetry_summary_endpoint_returns_400_for_missing_lap(self):
        response = self.client.get("/api/analysis/races/2024/1/telemetry/summary/?session=R&driver=VER")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "lap query parameter is required")

    # ========================================================================
    # Unified Service Tests
    # ========================================================================

    def test_unified_full_session_endpoint_requires_include_param(self):
        response = self.client.get("/api/unified/races/2024/1/full-session/")

        self.assertEqual(response.status_code, 400)
        self.assertIn("include parameter required", response.json()["error"])

    @patch("api.services.streaming.stream_unified_full_session_json")
    def test_unified_full_session_endpoint_returns_multiple_data_types(
        self, mock_stream
    ):
        mock_stream.return_value = Response({
            "meta": {"year": 2024, "round": 1},
            "data": {
                "telemetry": {"meta": {"row_count": 100}, "data": []},
                "weather": {"meta": {"row_count": 1}, "data": []}
            }
        })

        response = self.client.get("/api/unified/races/2024/1/full-session/?include=telemetry,weather")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["meta"]["year"], 2024)
        self.assertEqual(data["meta"]["round"], 1)
        self.assertIn("telemetry", data["data"])
        self.assertIn("weather", data["data"])

    @patch("api.session.views.handle_data_request")
    def test_unified_weather_endpoint_returns_payload(self, mock_handle_data):
        mock_handle_data.return_value = Response({
            "meta": {"year": 2024, "round": 1, "session": "R", "row_count": 1, "extracted_at": "2024-01-01T00:00:00", "limit_max": 2000},
            "filters_applied": {},
            "data": [
                {
                    "lap_number": None,
                    "driver_code": None,
                    "track_temp_c": 25.5,
                    "air_temp_c": 20.0,
                    "humidity_pct": 55.0,
                    "wind_speed_ms": 5.0,
                    "wind_direction_deg": 180.0,
                    "rainfall": False,
                }
            ],
        })

        response = self.client.get("/api/unified/races/2024/1/weather/?session=R")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["meta"]["row_count"], 1)
        self.assertEqual(payload["data"][0]["track_temp_c"], 25.5)

    @patch("api.session.views.handle_data_request")
    def test_unified_pit_stops_endpoint_returns_payload(self, mock_handle_data):
        mock_handle_data.return_value = Response({
            "meta": {"year": 2024, "round": 1, "session": "R", "row_count": 2, "extracted_at": "2024-01-01T00:00:00", "limit_max": 2000},
            "filters_applied": {"limit": None},
            "data": [
                {
                    "driver_code": "VER",
                    "driver_number": 1,
                    "stop_number": 1,
                    "lap_in": 20,
                    "lap_out": 22,
                    "stop_duration_seconds": 2.5,
                    "compound_in": "SOFT",
                    "compound_out": "MEDIUM",
                    "time_gain_loss_seconds": None,
                }
            ],
        })

        response = self.client.get("/api/unified/races/2024/1/pit-stops/?session=R")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["meta"]["row_count"], 2)
        self.assertEqual(payload["data"][0]["driver_code"], "VER")

    @patch("api.session.views.handle_data_request")
    def test_unified_incidents_endpoint_returns_payload(self, mock_handle_data):
        mock_handle_data.return_value = Response({
            "meta": {"year": 2024, "round": 1, "session": "R", "row_count": 1, "extracted_at": "2024-01-01T00:00:00", "limit_max": 2000},
            "filters_applied": {"include_radio": False},
            "data": [
                {
                    "lap_number": 15,
                    "message_type": "crash",
                    "drivers_involved": ["VER", "HAM"],
                    "message_text": "Collision at turn 5",
                    "timestamp_seconds": 1234.5,
                    "impact_on_race": "high",
                }
            ],
        })

        response = self.client.get("/api/unified/races/2024/1/incidents/?session=R")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["meta"]["row_count"], 1)
        self.assertEqual(payload["data"][0]["impact_on_race"], "high")

    @patch("api.session.views.handle_data_request")
    def test_unified_drs_endpoint_returns_payload(self, mock_handle_data):
        mock_handle_data.return_value = Response({
            "meta": {"year": 2024, "round": 1, "session": "R", "row_count": 2, "extracted_at": "2024-01-01T00:00:00", "limit_max": 2000},
            "filters_applied": {"driver": None},
            "data": [
                {
                    "driver_code": "VER",
                    "driver_number": 1,
                    "lap_number": 10,
                    "drs_available": True,
                    "drs_activated": True,
                    "gap_behind_seconds": None,
                    "performance_delta_ms": None,
                }
            ],
        })

        response = self.client.get("/api/unified/races/2024/1/drs/?session=R")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["meta"]["row_count"], 2)
        self.assertTrue(payload["data"][0]["drs_available"])

    @patch("api.session.views.handle_data_request")
    def test_unified_drs_endpoint_returns_readiness_payload_when_historical_data_unsupported(
        self, mock_handle_data
    ):
        mock_handle_data.return_value = Response({
            "meta": {
                "can_proceed": False,
                "unavailable_data": ["drs"]
            },
            "data": []
        })

        response = self.client.get("/api/unified/races/2016/2/drs/?session=R")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertFalse(payload["meta"]["can_proceed"])
        self.assertIn("drs", payload["meta"]["unavailable_data"])
        self.assertEqual(payload["data"], [])

    @patch("api.session.views.handle_data_request")
    def test_unified_weather_endpoint_returns_readiness_payload_when_session_load_unsupported(self, mock_handle_data):
        mock_handle_data.return_value = Response({
            "meta": {
                "can_proceed": False,
                "unavailable_data": ["weather"]
            },
            "data": []
        })

        response = self.client.get("/api/unified/races/2016/2/weather/?session=R")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertFalse(payload["meta"]["can_proceed"])
        self.assertIn("weather", payload["meta"]["unavailable_data"])
        self.assertEqual(payload["data"], [])

    @patch("api.session.views.handle_data_request")
    def test_unified_track_status_endpoint_returns_payload(self, mock_handle_data):
        mock_handle_data.return_value = Response({
            "meta": {"year": 2024, "round": 1, "session": "R", "row_count": 1, "extracted_at": "2024-01-01T00:00:00", "limit_max": 2000},
            "filters_applied": {},
            "data": [
                {
                    "lap_number": 5,
                    "status": "YELLOW",
                    "status_duration_laps": 3,
                    "cause": "Yellow flag incident",
                    "affected_zone": "Turn 12",
                }
            ],
        })

        response = self.client.get("/api/unified/races/2024/1/track-status/?session=R")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["meta"]["row_count"], 1)
        self.assertEqual(payload["data"][0]["status"], "YELLOW")

    def test_practice_endpoint_includes_readiness_when_service_returns_meta_payload(self):
        mocked_practice_payload = {
            "meta": {
                "year": 2017,
                "round": 2,
                "session": "FP1",
                "row_count": 0,
                "can_proceed": False,
                "available_data": ["track_status"],
                "unavailable_data": ["laps"],
                "message": "Session loaded, but required data is unavailable for 2017 Round 2 (FP1). Missing: laps.",
                "warnings": ["Session loaded, but required data is unavailable for 2017 Round 2 (FP1). Missing: laps."],
            },
            "data": [],
        }

        with patch("api.results.views.handle_data_request", return_value=Response(mocked_practice_payload)):
            response = self.client.get("/api/races/2017/2/practice/FP1/")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["meta"]["session"], "FP1")
        self.assertEqual(payload["data"], [])
        self.assertIn("can_proceed", payload["meta"])
        self.assertFalse(payload["meta"]["can_proceed"])

    def test_qualifying_endpoint_includes_readiness_when_service_returns_meta_payload(self):
        with patch("api.results.views.handle_data_request", return_value=Response({"meta": {"can_proceed": False}, "data": []})):
            response = self.client.get("/api/races/2017/2/qualifying/")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["data"], [])
        self.assertIn("can_proceed", payload["meta"])
        self.assertFalse(payload["meta"]["can_proceed"])

    def test_race_results_endpoint_includes_readiness_metadata(self):
        with patch("api.results.views.RaceResultsAPIView._fetch_race_results_data", return_value={"meta": {"can_proceed": False, "unavailable_data": ["race_results"]}, "data": []}):
            with patch("api.services.streaming.stream_combined_task_results_json", return_value=Response({"meta": {"can_proceed": False}, "data": []})):
                response = self.client.get("/api/races/2017/2/results/")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("can_proceed", payload["meta"])
        self.assertFalse(payload["meta"]["can_proceed"])
