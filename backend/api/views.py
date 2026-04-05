from rest_framework.response import Response
from rest_framework.views import APIView

from .serializers import (
    ConstructorSerializer,
    DriverStandingSerializer,
    LapAnalysisResponseSerializer,
    PaceAnalysisResponseSerializer,
    PracticeResultSerializer,
    QualifyingResultSerializer,
    RaceResultsSerializer,
    RaceSerializer,
    StintAnalysisResponseSerializer,
    SectorAnalysisResponseSerializer,
    TelemetryAnalysisResponseSerializer,
    TelemetryOverlayResponseSerializer,
    TelemetrySummaryResponseSerializer,
    TyreStrategyResponseSerializer,
    WeatherResponseSerializer,
    PitStopResponseSerializer,
    IncidentResponseSerializer,
    PositionResponseSerializer,
    DRSResponseSerializer,
    TrackStatusResponseSerializer,
)
from .services.analysis import (
    get_lap_analysis,
    get_pace_analysis,
    get_sector_analysis,
    get_stint_analysis,
    get_telemetry_overlay,
    get_telemetry_snapshot,
    get_telemetry_summary,
    get_tyre_strategy_analysis,
)
from .services.unified_service import SessionManager, TelemetryExtractor, WeatherExtractor, PitStopExtractor, IncidentExtractor, PositionExtractor, DRSExtractor, TrackStatusExtractor, EXTRACTORS_MAP
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


class AnalysisLapsAPIView(APIView):
    def get(self, request, year, round_number):
        try:
            session_name = request.query_params.get("session", "R")
            driver = request.query_params.get("driver")
            limit_param = request.query_params.get("limit")

            limit = None
            if limit_param is not None and limit_param != "":
                try:
                    limit = int(limit_param)
                except (TypeError, ValueError):
                    return Response({"error": "limit must be an integer"}, status=400)

            analysis_payload = get_lap_analysis(
                year=year,
                round_number=round_number,
                session=session_name,
                driver=driver,
                limit=limit,
            )
            serializer = LapAnalysisResponseSerializer(analysis_payload)
            return Response(serializer.data)
        except ValueError as exc:
            return Response({"error": str(exc)}, status=400)
        except Exception as exc:
            return Response({"error": str(exc)}, status=500)


class AnalysisStintsAPIView(APIView):
    def get(self, request, year, round_number):
        try:
            session_name = request.query_params.get("session", "R")
            driver = request.query_params.get("driver")
            limit_param = request.query_params.get("limit")

            limit = None
            if limit_param is not None and limit_param != "":
                try:
                    limit = int(limit_param)
                except (TypeError, ValueError):
                    return Response({"error": "limit must be an integer"}, status=400)

            analysis_payload = get_stint_analysis(
                year=year,
                round_number=round_number,
                session=session_name,
                driver=driver,
                limit=limit,
            )
            serializer = StintAnalysisResponseSerializer(analysis_payload)
            return Response(serializer.data)
        except ValueError as exc:
            return Response({"error": str(exc)}, status=400)
        except Exception as exc:
            return Response({"error": str(exc)}, status=500)


class AnalysisPaceAPIView(APIView):
    def get(self, request, year, round_number):
        try:
            session_name = request.query_params.get("session", "R")
            driver = request.query_params.get("driver")
            limit_param = request.query_params.get("limit")

            limit = None
            if limit_param is not None and limit_param != "":
                try:
                    limit = int(limit_param)
                except (TypeError, ValueError):
                    return Response({"error": "limit must be an integer"}, status=400)

            analysis_payload = get_pace_analysis(
                year=year,
                round_number=round_number,
                session=session_name,
                driver=driver,
                limit=limit,
            )
            serializer = PaceAnalysisResponseSerializer(analysis_payload)
            return Response(serializer.data)
        except ValueError as exc:
            return Response({"error": str(exc)}, status=400)
        except Exception as exc:
            return Response({"error": str(exc)}, status=500)


class AnalysisTyreStrategyAPIView(APIView):
    def get(self, request, year, round_number):
        try:
            session_name = request.query_params.get("session", "R")
            driver = request.query_params.get("driver")
            limit_param = request.query_params.get("limit")

            limit = None
            if limit_param is not None and limit_param != "":
                try:
                    limit = int(limit_param)
                except (TypeError, ValueError):
                    return Response({"error": "limit must be an integer"}, status=400)

            analysis_payload = get_tyre_strategy_analysis(
                year=year,
                round_number=round_number,
                session=session_name,
                driver=driver,
                limit=limit,
            )
            serializer = TyreStrategyResponseSerializer(analysis_payload)
            return Response(serializer.data)
        except ValueError as exc:
            return Response({"error": str(exc)}, status=400)
        except Exception as exc:
            return Response({"error": str(exc)}, status=500)


class AnalysisSectorAPIView(APIView):
    def get(self, request, year, round_number):
        try:
            session_name = request.query_params.get("session", "R")
            driver = request.query_params.get("driver")
            limit_param = request.query_params.get("limit")

            limit = None
            if limit_param is not None and limit_param != "":
                try:
                    limit = int(limit_param)
                except (TypeError, ValueError):
                    return Response({"error": "limit must be an integer"}, status=400)

            analysis_payload = get_sector_analysis(
                year=year,
                round_number=round_number,
                session=session_name,
                driver=driver,
                limit=limit,
            )
            serializer = SectorAnalysisResponseSerializer(analysis_payload)
            return Response(serializer.data)
        except ValueError as exc:
            return Response({"error": str(exc)}, status=400)
        except Exception as exc:
            return Response({"error": str(exc)}, status=500)


class AnalysisTelemetryAPIView(APIView):
    def get(self, request, year, round_number):
        try:
            session_name = request.query_params.get("session", "R")
            driver = request.query_params.get("driver")
            lap_param = request.query_params.get("lap")
            limit_points_param = request.query_params.get("limit_points")
            stride_param = request.query_params.get("stride", "1")
            sector_start_param = request.query_params.get("sector_start")
            sector_end_param = request.query_params.get("sector_end")

            if not driver:
                return Response({"error": "driver query parameter is required"}, status=400)

            if lap_param is None or lap_param == "":
                return Response({"error": "lap query parameter is required"}, status=400)

            try:
                lap = int(lap_param)
            except (TypeError, ValueError):
                return Response({"error": "lap must be an integer"}, status=400)

            try:
                stride = int(stride_param)
            except (TypeError, ValueError):
                return Response({"error": "stride must be an integer"}, status=400)

            limit_points = None
            if limit_points_param is not None and limit_points_param != "":
                try:
                    limit_points = int(limit_points_param)
                except (TypeError, ValueError):
                    return Response({"error": "limit_points must be an integer"}, status=400)

            sector_start = None
            if sector_start_param is not None and sector_start_param != "":
                try:
                    sector_start = int(sector_start_param)
                except (TypeError, ValueError):
                    return Response({"error": "sector_start must be an integer"}, status=400)

            sector_end = None
            if sector_end_param is not None and sector_end_param != "":
                try:
                    sector_end = int(sector_end_param)
                except (TypeError, ValueError):
                    return Response({"error": "sector_end must be an integer"}, status=400)

            analysis_payload = get_telemetry_snapshot(
                year=year,
                round_number=round_number,
                session=session_name,
                driver=driver,
                lap=lap,
                limit_points=limit_points,
                stride=stride,
                sector_start=sector_start,
                sector_end=sector_end,
            )
            serializer = TelemetryAnalysisResponseSerializer(analysis_payload)
            return Response(serializer.data)
        except ValueError as exc:
            return Response({"error": str(exc)}, status=400)
        except Exception as exc:
            return Response({"error": str(exc)}, status=500)


class AnalysisTelemetryOverlayAPIView(APIView):
    def get(self, request, year, round_number):
        try:
            session_name = request.query_params.get("session", "R")
            driver_a = request.query_params.get("driver_a")
            driver_b = request.query_params.get("driver_b")
            lap_a_param = request.query_params.get("lap_a")
            lap_b_param = request.query_params.get("lap_b")
            limit_points_param = request.query_params.get("limit_points")
            stride_param = request.query_params.get("stride", "1")
            sector_start_param = request.query_params.get("sector_start")
            sector_end_param = request.query_params.get("sector_end")

            if not driver_a or not driver_b:
                return Response({"error": "driver_a and driver_b query parameters are required"}, status=400)

            lap_a = None
            if lap_a_param is not None and lap_a_param != "":
                try:
                    lap_a = int(lap_a_param)
                except (TypeError, ValueError):
                    return Response({"error": "lap_a must be an integer"}, status=400)

            lap_b = None
            if lap_b_param is not None and lap_b_param != "":
                try:
                    lap_b = int(lap_b_param)
                except (TypeError, ValueError):
                    return Response({"error": "lap_b must be an integer"}, status=400)

            try:
                stride = int(stride_param)
            except (TypeError, ValueError):
                return Response({"error": "stride must be an integer"}, status=400)

            limit_points = None
            if limit_points_param is not None and limit_points_param != "":
                try:
                    limit_points = int(limit_points_param)
                except (TypeError, ValueError):
                    return Response({"error": "limit_points must be an integer"}, status=400)

            sector_start = None
            if sector_start_param is not None and sector_start_param != "":
                try:
                    sector_start = int(sector_start_param)
                except (TypeError, ValueError):
                    return Response({"error": "sector_start must be an integer"}, status=400)

            sector_end = None
            if sector_end_param is not None and sector_end_param != "":
                try:
                    sector_end = int(sector_end_param)
                except (TypeError, ValueError):
                    return Response({"error": "sector_end must be an integer"}, status=400)

            analysis_payload = get_telemetry_overlay(
                year=year,
                round_number=round_number,
                session=session_name,
                driver_a=driver_a,
                driver_b=driver_b,
                lap_a=lap_a,
                lap_b=lap_b,
                limit_points=limit_points,
                stride=stride,
                sector_start=sector_start,
                sector_end=sector_end,
            )
            serializer = TelemetryOverlayResponseSerializer(analysis_payload)
            return Response(serializer.data)
        except ValueError as exc:
            return Response({"error": str(exc)}, status=400)
        except Exception as exc:
            return Response({"error": str(exc)}, status=500)


class AnalysisTelemetrySummaryAPIView(APIView):
    def get(self, request, year, round_number):
        try:
            session_name = request.query_params.get("session", "R")
            driver = request.query_params.get("driver")
            lap_param = request.query_params.get("lap")
            stride_param = request.query_params.get("stride", "1")
            sector_start_param = request.query_params.get("sector_start")
            sector_end_param = request.query_params.get("sector_end")

            if not driver:
                return Response({"error": "driver query parameter is required"}, status=400)

            if lap_param is None or lap_param == "":
                return Response({"error": "lap query parameter is required"}, status=400)

            try:
                lap = int(lap_param)
            except (TypeError, ValueError):
                return Response({"error": "lap must be an integer"}, status=400)

            try:
                stride = int(stride_param)
            except (TypeError, ValueError):
                return Response({"error": "stride must be an integer"}, status=400)

            sector_start = None
            if sector_start_param is not None and sector_start_param != "":
                try:
                    sector_start = int(sector_start_param)
                except (TypeError, ValueError):
                    return Response({"error": "sector_start must be an integer"}, status=400)

            sector_end = None
            if sector_end_param is not None and sector_end_param != "":
                try:
                    sector_end = int(sector_end_param)
                except (TypeError, ValueError):
                    return Response({"error": "sector_end must be an integer"}, status=400)

            analysis_payload = get_telemetry_summary(
                year=year,
                round_number=round_number,
                session=session_name,
                driver=driver,
                lap=lap,
                stride=stride,
                sector_start=sector_start,
                sector_end=sector_end,
            )
            serializer = TelemetrySummaryResponseSerializer(analysis_payload)
            return Response(serializer.data)
        except ValueError as exc:
            return Response({"error": str(exc)}, status=400)
        except Exception as exc:
            return Response({"error": str(exc)}, status=500)


# ============================================================================
# Unified Service Endpoints - Access all FastF1 data via modular extractors
# ============================================================================


class UnifiedFullSessionAPIView(APIView):
    """Query multiple data types from a session simultaneously."""

    def get(self, request, year, round_number):
        try:
            session_name = request.query_params.get("session", "R").upper()
            include_param = request.query_params.get("include", "").strip()
            driver = request.query_params.get("driver")

            if not include_param:
                return Response(
                    {"error": "include parameter required (e.g., ?include=telemetry,weather,pit_stops)"},
                    status=400,
                )

            # Parse include list
            include_types = [t.strip() for t in include_param.split(",") if t.strip()]
            invalid_types = [t for t in include_types if t not in EXTRACTORS_MAP]
            if invalid_types:
                return Response(
                    {
                        "error": f"Unknown data types: {invalid_types}. Valid: {list(EXTRACTORS_MAP.keys())}"
                    },
                    status=400,
                )

            # Load session once, reuse for all extractors
            session = SessionManager.get_session(year, round_number, session_name)

            # Extract each requested data type
            extracted_data = {}
            for data_type in include_types:
                try:
                    extractor_class = EXTRACTORS_MAP[data_type]
                    extractor = extractor_class(session, year, round_number, session_name, driver=driver)
                    extracted_data[data_type] = extractor.extract()
                except Exception as e:
                    extracted_data[data_type] = {"error": str(e), "status": "failed"}

            # Build response
            response_data = {
                "meta": {
                    "year": year,
                    "round": round_number,
                    "session": session_name,
                    "requested_types": include_types,
                    "cache_stats": SessionManager.get_cache_stats(),
                },
                "data": extracted_data,
            }

            return Response(response_data)
        except ValueError as exc:
            return Response({"error": str(exc)}, status=400)
        except Exception as exc:
            return Response({"error": str(exc)}, status=500)


class UnifiedWeatherAPIView(APIView):
    """Extract weather data only."""

    def get(self, request, year, round_number):
        try:
            session_name = request.query_params.get("session", "R").upper()
            include_per_lap = request.query_params.get("per_lap", "false").lower() == "true"

            session = SessionManager.get_session(year, round_number, session_name)
            extractor = WeatherExtractor(session, year, round_number, session_name)
            data = extractor.extract(include_per_lap=include_per_lap)

            serializer = WeatherResponseSerializer(data)
            return Response(serializer.data)
        except ValueError as exc:
            return Response({"error": str(exc)}, status=400)
        except Exception as exc:
            return Response({"error": str(exc)}, status=500)


class UnifiedPitStopsAPIView(APIView):
    """Extract pit stop strategy data only."""

    def get(self, request, year, round_number):
        try:
            session_name = request.query_params.get("session", "R").upper()
            limit_param = request.query_params.get("limit")

            limit = None
            if limit_param:
                try:
                    limit = int(limit_param)
                except ValueError:
                    return Response({"error": "limit must be an integer"}, status=400)

            session = SessionManager.get_session(year, round_number, session_name)
            extractor = PitStopExtractor(session, year, round_number, session_name, limit=limit)
            data = extractor.extract()

            serializer = PitStopResponseSerializer(data)
            return Response(serializer.data)
        except ValueError as exc:
            return Response({"error": str(exc)}, status=400)
        except Exception as exc:
            return Response({"error": str(exc)}, status=500)


class UnifiedIncidentsAPIView(APIView):
    """Extract incidents and messages."""

    def get(self, request, year, round_number):
        try:
            session_name = request.query_params.get("session", "R").upper()
            include_radio = request.query_params.get("radio", "false").lower() == "true"
            limit_param = request.query_params.get("limit")

            limit = None
            if limit_param:
                try:
                    limit = int(limit_param)
                except ValueError:
                    return Response({"error": "limit must be an integer"}, status=400)

            session = SessionManager.get_session(year, round_number, session_name)
            extractor = IncidentExtractor(session, year, round_number, session_name, limit=limit)
            data = extractor.extract(include_radio=include_radio)

            serializer = IncidentResponseSerializer(data)
            return Response(serializer.data)
        except ValueError as exc:
            return Response({"error": str(exc)}, status=400)
        except Exception as exc:
            return Response({"error": str(exc)}, status=500)


class UnifiedPositionsAPIView(APIView):
    """Extract position and gap data."""

    def get(self, request, year, round_number):
        try:
            session_name = request.query_params.get("session", "R").upper()
            sample_interval = request.query_params.get("sample_interval", "5")

            try:
                sample_interval = int(sample_interval)
            except ValueError:
                return Response({"error": "sample_interval must be an integer"}, status=400)

            session = SessionManager.get_session(year, round_number, session_name)
            extractor = PositionExtractor(session, year, round_number, session_name)
            data = extractor.extract(sample_interval=sample_interval)

            serializer = PositionResponseSerializer(data)
            return Response(serializer.data)
        except ValueError as exc:
            return Response({"error": str(exc)}, status=400)
        except Exception as exc:
            return Response({"error": str(exc)}, status=500)


class UnifiedDRSAPIView(APIView):
    """Extract DRS activation data."""

    def get(self, request, year, round_number):
        try:
            session_name = request.query_params.get("session", "R").upper()
            driver = request.query_params.get("driver")

            session = SessionManager.get_session(year, round_number, session_name)
            extractor = DRSExtractor(session, year, round_number, session_name, driver=driver)
            data = extractor.extract()

            serializer = DRSResponseSerializer(data)
            return Response(serializer.data)
        except ValueError as exc:
            return Response({"error": str(exc)}, status=400)
        except Exception as exc:
            return Response({"error": str(exc)}, status=500)


class UnifiedTrackStatusAPIView(APIView):
    """Extract track status timeline."""

    def get(self, request, year, round_number):
        try:
            session_name = request.query_params.get("session", "R").upper()

            session = SessionManager.get_session(year, round_number, session_name)
            extractor = TrackStatusExtractor(session, year, round_number, session_name)
            data = extractor.extract()

            serializer = TrackStatusResponseSerializer(data)
            return Response(serializer.data)
        except ValueError as exc:
            return Response({"error": str(exc)}, status=400)
        except Exception as exc:
            return Response({"error": str(exc)}, status=500)
