import logging
import time
import json
from django.core.cache import cache
from django.utils import timezone
from rest_framework.views import APIView
from rest_framework.response import Response
from drf_spectacular.utils import extend_schema, OpenApiResponse, OpenApiParameter, OpenApiExample, inline_serializer
from drf_spectacular.types import OpenApiTypes
from rest_framework import serializers as drf_serializers
from api.common.readiness import build_readiness
from api.common.response import build_error_payload
from api.services.nonblocking import handle_data_request
from api.session.serializers import *
from api.services.persistence import *
from api.tasks import *
from api.models import TaskRecord, DriverLapAnalysis, WeatherData, PitStopData, IncidentData, PositionData, DRSData, TrackStatusData
from api.services.unified_service import EXTRACTORS_MAP, SessionManager
from api.services import streaming
from api.queue.manager import TaskManager
from api.core import _ensure_payload_meta_checklist
from api.services.analysis import (
    get_lap_analysis,
    get_stint_analysis,
    get_pace_analysis,
    get_sector_analysis,
)
logger = logging.getLogger(__name__)

class AnalysisLapsAPIView(APIView):

    @extend_schema(operation_id='analysis_laps_retrieve', summary='Get lap-by-lap analysis', description='Returns one row per valid lap containing the driver, lap number, total lap time, all three sector times, tyre compound, stint number, and a personal-best flag. Laps with no recorded LapTime are excluded. Supports all five session types (R, Q, FP1-FP3). Use the driver filter to narrow to one driver and limit to cap the result set.', parameters=[OpenApiParameter(name='session', location=OpenApiParameter.QUERY, required=False, type=str, description='R, Q, S, SQ, FP1, FP2, FP3'), OpenApiParameter(name='driver', location=OpenApiParameter.QUERY, required=False, type=str, description='3-letter driver code'), OpenApiParameter(name='limit', location=OpenApiParameter.QUERY, required=False, type=int, description='Maximum rows to return')], responses={200: LapAnalysisResponseSerializer, 400: OpenApiResponse(description='Invalid query parameters')}, examples=[OpenApiExample('Readiness Proceed', value={'meta': {'year': 2020, 'round': 2, 'session': 'R', 'row_count': 5, 'limit_max': 2000, 'can_proceed': True, 'available_data': ['laps', 'track_status'], 'unavailable_data': [], 'message': None, 'warnings': []}, 'filters_applied': {'driver': None, 'limit': 5}, 'data': [{'driver_code': 'VER', 'lap_number': 1, 'lap_time': '0 days 00:01:37.123000', 'sector1': '0 days 00:00:31.100000', 'sector2': '0 days 00:00:33.000000', 'sector3': '0 days 00:00:33.023000', 'compound': 'MEDIUM', 'stint': 1, 'is_personal_best': False}]}, response_only=True, status_codes=['200']), OpenApiExample('Readiness Partial Unsupported', value={'meta': {'year': 2016, 'round': 3, 'session': 'R', 'row_count': 0, 'limit_max': 2000, 'can_proceed': False, 'available_data': ['track_status'], 'unavailable_data': ['laps'], 'message': 'Session loaded, but required data is unavailable for 2016 Round 3 (R). Missing: laps.', 'warnings': ['Session loaded, but required data is unavailable for 2016 Round 3 (R). Missing: laps.']}, 'filters_applied': {'driver': None, 'limit': 5}, 'data': []}, response_only=True, status_codes=['200'])])
    def get(self, request, year, round_number):
        request.endpoint_type = 'laps'
        session_name = request.query_params.get('session', 'R')
        driver = request.query_params.get('driver')
        limit_param = request.query_params.get('limit')
        limit = None
        if limit_param is not None and limit_param != '':
            try:
                limit = int(limit_param)
            except (TypeError, ValueError):
                return Response({'error': 'limit must be an integer'}, status=400)
        task_key = f'populate_laps:{year}:{round_number}:{session_name}'
        cache_key = f'laps:{year}:{round_number}:{session_name}'
        if driver:
            cache_key += f':driver:{driver}'
            task_key += f':driver:{driver}'
        if limit:
            cache_key += f':limit:{limit}'
            task_key += f':limit:{limit}'
        try:
            return handle_data_request(cache_key=cache_key, db_fetch_fn=lambda: self._fetch_laps_data(year, round_number, session_name, driver, limit), task_fn=populate_laps, task_key=task_key, task_args=(year, round_number, session_name), task_kwargs={'driver': driver, 'limit': limit})
        except ValueError as e:
            return Response({'error': str(e)}, status=400)

    @staticmethod
    def _fetch_laps_data(year, round_number, session_name, driver, limit):
        try:
            analysis_payload = get_lap_analysis(year=year, round_number=round_number, session=session_name, driver=driver, limit=limit)
            if isinstance(analysis_payload, dict) and 'data' in analysis_payload:
                try:
                    analysis_payload['data'] = LapAnalysisRowSerializer(analysis_payload['data'], many=True).data
                except Exception:
                    pass
            return _ensure_payload_meta_checklist(analysis_payload, ['laps'], [])
        except Exception:
            return None

class AnalysisStintsAPIView(APIView):

    @extend_schema(operation_id='analysis_stints_retrieve', summary='Get stint-level analysis', description='Groups consecutive laps on the same tyre compound into stints and returns per-stint statistics: compound name, start/end lap, and median/min/max lap time. For Race sessions the service reads pre-computed StintData rows from the database, bypassing a live FastF1 call entirely. Useful for visualising tyre degradation and strategy comparison across drivers.', parameters=[OpenApiParameter(name='session', location=OpenApiParameter.QUERY, required=False, type=str, description='R, Q, S, SQ, FP1, FP2, FP3. Default: R'), OpenApiParameter(name='driver', location=OpenApiParameter.QUERY, required=False, type=str, description='3-letter driver code filter'), OpenApiParameter(name='limit', location=OpenApiParameter.QUERY, required=False, type=int, description='Maximum rows to return')], responses={200: StintAnalysisResponseSerializer, 400: OpenApiResponse(description='Invalid parameters')})
    def get(self, request, year, round_number):
        request.endpoint_type = 'stints'
        session_name = request.query_params.get('session', 'R')
        driver = request.query_params.get('driver')
        limit_param = request.query_params.get('limit')
        limit = None
        if limit_param is not None and limit_param != '':
            try:
                limit = int(limit_param)
            except (TypeError, ValueError):
                return Response({'error': 'limit must be an integer'}, status=400)
        task_key = f'populate_stints:{year}:{round_number}:{session_name}'
        cache_key = f'stints:{year}:{round_number}:{session_name}'
        if driver:
            cache_key += f':driver:{driver}'
            task_key += f':driver:{driver}'
        if limit:
            cache_key += f':limit:{limit}'
            task_key += f':limit:{limit}'
        try:
            return handle_data_request(cache_key=cache_key, db_fetch_fn=lambda: self._fetch_stints_data(year, round_number, session_name, driver, limit), task_fn=populate_stint_analysis, task_key=task_key, task_args=(year, round_number, session_name), task_kwargs={'driver': driver, 'limit': limit})
        except ValueError as e:
            return Response({'error': str(e)}, status=400)

    @staticmethod
    def _fetch_stints_data(year, round_number, session_name, driver, limit):
        try:
            analysis_payload = get_stint_analysis(year=year, round_number=round_number, session=session_name, driver=driver, limit=limit)
            if isinstance(analysis_payload, dict) and 'data' in analysis_payload:
                try:
                    analysis_payload['data'] = StintAnalysisRowSerializer(analysis_payload['data'], many=True).data
                except Exception:
                    logger.warning('Failed to release lock or clear cache')
            return _ensure_payload_meta_checklist(analysis_payload, ['laps'], [])
        except Exception:
            return None

class AnalysisPaceAPIView(APIView):

    @extend_schema(operation_id='analysis_pace_retrieve', summary='Get driver pace analysis', description='Aggregates lap times per driver to expose median pace, best lap, and consistency (standard deviation). For Race sessions the service reads pre-computed DriverMetric rows from the database before falling back to a live FastF1 computation, making it fast for recently populated seasons. Ideal for building a pace-comparison chart across the entire grid.', parameters=[OpenApiParameter(name='session', location=OpenApiParameter.QUERY, required=False, type=str, description='R, Q, S, SQ, FP1, FP2, FP3. Default: R'), OpenApiParameter(name='driver', location=OpenApiParameter.QUERY, required=False, type=str, description='3-letter driver code filter'), OpenApiParameter(name='limit', location=OpenApiParameter.QUERY, required=False, type=int, description='Maximum rows to return')], responses={200: PaceAnalysisResponseSerializer, 400: OpenApiResponse(description='Invalid parameters')})
    def get(self, request, year, round_number):
        request.endpoint_type = 'pace'
        session_name = request.query_params.get('session', 'R')
        driver = request.query_params.get('driver')
        limit_param = request.query_params.get('limit')
        limit = None
        if limit_param is not None and limit_param != '':
            try:
                limit = int(limit_param)
            except (TypeError, ValueError):
                return Response({'error': 'limit must be an integer'}, status=400)
        task_key = f'populate_pace:{year}:{round_number}:{session_name}'
        cache_key = f'pace:{year}:{round_number}:{session_name}'
        if driver:
            cache_key += f':driver:{driver}'
            task_key += f':driver:{driver}'
        if limit:
            cache_key += f':limit:{limit}'
            task_key += f':limit:{limit}'
        try:
            return handle_data_request(cache_key=cache_key, db_fetch_fn=lambda: self._fetch_pace_data(year, round_number, session_name, driver, limit), task_fn=populate_pace_analysis, task_key=task_key, task_args=(year, round_number, session_name), task_kwargs={'driver': driver, 'limit': limit})
        except ValueError as e:
            return Response({'error': str(e)}, status=400)

    @staticmethod
    def _fetch_pace_data(year, round_number, session_name, driver, limit):
        try:
            analysis_payload = get_pace_analysis(year=year, round_number=round_number, session=session_name, driver=driver, limit=limit)
            if isinstance(analysis_payload, dict) and 'data' in analysis_payload:
                try:
                    analysis_payload['data'] = PaceAnalysisRowSerializer(analysis_payload['data'], many=True).data
                except Exception:
                    logger.warning('Failed to release lock or clear cache')
            return _ensure_payload_meta_checklist(analysis_payload, ['laps'], [])
        except Exception:
            return None

class AnalysisTyreStrategyAPIView(APIView):

    @extend_schema(operation_id='analysis_tyre_strategy_retrieve', summary='Get tyre strategy analysis', description='Extends the stint view with tyre-strategy-specific fields: average lap time per stint, median lap time, and per-lap degradation in seconds. Sourced from persisted StintData for Race sessions and computed live from FastF1 otherwise. Ideal for building tyre-strategy timeline charts that show compound changes and pace impact across the race.', parameters=[OpenApiParameter(name='session', location=OpenApiParameter.QUERY, required=False, type=str, description='R, Q, S, SQ, FP1, FP2, FP3. Default: R'), OpenApiParameter(name='driver', location=OpenApiParameter.QUERY, required=False, type=str, description='3-letter driver code filter'), OpenApiParameter(name='limit', location=OpenApiParameter.QUERY, required=False, type=int, description='Maximum rows to return')], responses={200: TyreStrategyResponseSerializer, 400: OpenApiResponse(description='Invalid parameters')})
    def get(self, request, year, round_number):
        request.endpoint_type = 'tyre_strategy'
        session_name = request.query_params.get('session', 'R')
        driver = request.query_params.get('driver')
        limit_param = request.query_params.get('limit')
        limit = None
        if limit_param is not None and limit_param != '':
            try:
                limit = int(limit_param)
            except (TypeError, ValueError):
                return Response({'error': 'limit must be an integer'}, status=400)
        task_key = f'populate_tyre_strategy:{year}:{round_number}:{session_name}'
        cache_key = f'tyre_strategy:{year}:{round_number}:{session_name}'
        if driver:
            cache_key += f':driver:{driver}'
            task_key += f':driver:{driver}'
        if limit:
            cache_key += f':limit:{limit}'
            task_key += f':limit:{limit}'
        try:
            return handle_data_request(cache_key=cache_key, db_fetch_fn=lambda: self._fetch_tyre_strategy_data(year, round_number, session_name, driver, limit), task_fn=populate_tyre_strategy, task_key=task_key, task_args=(year, round_number, session_name), task_kwargs={'driver': driver, 'limit': limit})
        except ValueError as e:
            return Response({'error': str(e)}, status=400)

    @staticmethod
    def _fetch_tyre_strategy_data(year, round_number, session_name, driver, limit):
        try:
            analysis_payload = get_tyre_strategy_analysis(year=year, round_number=round_number, session=session_name, driver=driver, limit=limit)
            if isinstance(analysis_payload, dict) and 'data' in analysis_payload:
                try:
                    analysis_payload['data'] = TyreStrategyRowSerializer(analysis_payload['data'], many=True).data
                except Exception:
                    logger.warning('Failed to release lock or clear cache')
            return _ensure_payload_meta_checklist(analysis_payload, ['laps'], [])
        except Exception:
            return None

class AnalysisSectorAPIView(APIView):

    @extend_schema(operation_id='analysis_sector_retrieve', summary='Get sector-time analysis', description="For each driver returns best and median times for Sectors 1, 2, and 3, alongside their best actual lap and the theoretical best lap (sum of each sector's individual best). The delta between actual best and theoretical best shows how close a driver came to perfecting their lap. Race-session results are served from persisted SectorAggregate rows when available.", parameters=[OpenApiParameter(name='session', location=OpenApiParameter.QUERY, required=False, type=str, description='R, Q, FP1, FP2, FP3. Default: R'), OpenApiParameter(name='driver', location=OpenApiParameter.QUERY, required=False, type=str, description='3-letter driver code filter'), OpenApiParameter(name='limit', location=OpenApiParameter.QUERY, required=False, type=int, description='Maximum rows to return')], responses={200: SectorAnalysisResponseSerializer, 400: OpenApiResponse(description='Invalid parameters')})
    def get(self, request, year, round_number):
        request.endpoint_type = 'sectors'
        session_name = request.query_params.get('session', 'R')
        driver = request.query_params.get('driver')
        limit_param = request.query_params.get('limit')
        limit = None
        if limit_param is not None and limit_param != '':
            try:
                limit = int(limit_param)
            except (TypeError, ValueError):
                return Response({'error': 'limit must be an integer'}, status=400)
        task_key = f'populate_sector:{year}:{round_number}:{session_name}'
        cache_key = f'sector:{year}:{round_number}:{session_name}'
        if driver:
            cache_key += f':driver:{driver}'
            task_key += f':driver:{driver}'
        if limit:
            cache_key += f':limit:{limit}'
            task_key += f':limit:{limit}'
        try:
            return handle_data_request(cache_key=cache_key, db_fetch_fn=lambda: self._fetch_sector_data(year, round_number, session_name, driver, limit), task_fn=populate_sector_analysis, task_key=task_key, task_args=(year, round_number, session_name), task_kwargs={'driver': driver, 'limit': limit})
        except ValueError as e:
            return Response({'error': str(e)}, status=400)

    @staticmethod
    def _fetch_sector_data(year, round_number, session_name, driver, limit):
        try:
            analysis_payload = get_sector_analysis(year=year, round_number=round_number, session=session_name, driver=driver, limit=limit)
            if isinstance(analysis_payload, dict) and 'data' in analysis_payload:
                try:
                    analysis_payload['data'] = SectorAnalysisRowSerializer(analysis_payload['data'], many=True).data
                except Exception:
                    logger.warning('Failed to release lock or clear cache')
            return _ensure_payload_meta_checklist(analysis_payload, ['laps'], [])
        except Exception:
            return None

class AnalysisTelemetryAPIView(APIView):

    @extend_schema(
        operation_id='analysis_telemetry_retrieve', 
        summary='Get car telemetry (lap, driver, or session)', 
        description='''Streams high-fidelity car telemetry data. The payload is grouped by lap number. If driver and lap are omitted, it returns full telemetry for all drivers across all laps.

Returns the following traces per lap:
- **distance**: Track distance in meters
- **speed**: Car speed in KPH
- **throttle**: Throttle pedal application percentage (0-100)
- **brake**: Brake pedal application (boolean)
- **gear**: Current selected gear (1-8)
- **rpm**: Engine RPM
- **drs**: DRS state (boolean)
- **relative_distance**: Distance normalized from 0.0 to 1.0 representing progression through the lap
- **sector**: The sector of the track (1, 2, or 3) that the car is currently in at this timestamp.

Use `limit_points` to cap the total payload size. Use `stride` to downsample points (e.g. stride=12 takes every 12th point) to prevent browser crashing on full-race queries. Use `sector_start` and `sector_end` to clip the telemetry to specific parts of the track.''', 
        parameters=[
            OpenApiParameter(name='session', location=OpenApiParameter.QUERY, required=False, type=str, description='R, Q, FP1, FP2, FP3'), 
            OpenApiParameter(name='driver', location=OpenApiParameter.QUERY, required=False, type=str, description='Optional 3-letter driver code. Omitting returns all drivers.'), 
            OpenApiParameter(name='lap', location=OpenApiParameter.QUERY, required=False, type=int, description='Optional lap number. Omitting returns all laps.'), 
            OpenApiParameter(name='limit_points', location=OpenApiParameter.QUERY, required=False, type=int, description='Maximum telemetry points'), 
            OpenApiParameter(name='stride', location=OpenApiParameter.QUERY, required=False, type=int, description='Sample every N points'), 
            OpenApiParameter(name='sector_start', location=OpenApiParameter.QUERY, required=False, type=int, description='Sector window start (1-3)'), 
            OpenApiParameter(name='sector_end', location=OpenApiParameter.QUERY, required=False, type=int, description='Sector window end (1-3)')
        ], 
        responses={200: TelemetryAnalysisResponseSerializer, 400: OpenApiResponse(description='Missing or invalid telemetry query parameters')}
    )
    def get(self, request, year, round_number):
        request.endpoint_type = 'telemetry'
        try:
            session_name = request.query_params.get('session', 'R')
            driver = request.query_params.get('driver')
            lap_param = request.query_params.get('lap')
            limit_points_param = request.query_params.get('limit_points')
            stride_param = request.query_params.get('stride', '1')
            sector_start_param = request.query_params.get('sector_start')
            sector_end_param = request.query_params.get('sector_end')
            lap = None
            if lap_param is not None and lap_param != '':
                try:
                    lap = int(lap_param)
                except (TypeError, ValueError):
                    return Response({'error': 'lap must be an integer'}, status=400)
            try:
                stride = int(stride_param)
            except (TypeError, ValueError):
                return Response({'error': 'stride must be an integer'}, status=400)
            limit_points = None
            if limit_points_param is not None and limit_points_param != '':
                try:
                    limit_points = int(limit_points_param)
                except (TypeError, ValueError):
                    return Response({'error': 'limit_points must be an integer'}, status=400)
            sector_start = None
            if sector_start_param is not None and sector_start_param != '':
                try:
                    sector_start = int(sector_start_param)
                except (TypeError, ValueError):
                    return Response({'error': 'sector_start must be an integer'}, status=400)
            sector_end = None
            if sector_end_param is not None and sector_end_param != '':
                try:
                    sector_end = int(sector_end_param)
                except (TypeError, ValueError):
                    return Response({'error': 'sector_end must be an integer'}, status=400)
            cache_key = f'telemetry:{year}:{round_number}:{session_name}:{driver}:{lap}'
            if limit_points:
                cache_key += f':LP{limit_points}'
            if stride and stride != 1:
                cache_key += f':S{stride}'
            if sector_start:
                cache_key += f':SS{sector_start}'
            if sector_end:
                cache_key += f':SE{sector_end}'
            task_key = f'populate_telemetry:{year}:{round_number}:{session_name}:{driver}:{lap}'
            return handle_data_request(cache_key=cache_key, db_fetch_fn=lambda: self._fetch_telemetry_data(year, round_number, session_name, driver, lap, limit_points, stride, sector_start, sector_end), task_fn=populate_telemetry, task_key=task_key, task_args=(year, round_number, session_name), task_kwargs={'driver': driver, 'lap': lap, 'limit_points': limit_points, 'stride': stride, 'sector_start': sector_start, 'sector_end': sector_end}, timeout=180)
        except ValueError as exc:
            return Response({'error': str(exc)}, status=400)
        except Exception as exc:
            return Response(build_error_payload('analysis.telemetry', str(exc), 'ANALYSIS_TELEMETRY_ERROR'), status=500)

    def _fetch_telemetry_data(self, year, round_number, session_name, driver, lap, limit_points, stride, sector_start, sector_end):
        """Fetch telemetry data from analysis service."""
        from api.services.analysis import fetch_telemetry_snapshot
        analysis_payload = fetch_telemetry_snapshot(year=year, round_number=round_number, session=session_name, driver=driver, lap=lap, limit_points=limit_points, stride=stride, sector_start=sector_start, sector_end=sector_end)
        if analysis_payload is None:
            return None
        if isinstance(analysis_payload, dict):
            if 'data' in analysis_payload:
                try:
                    analysis_payload['data'] = TelemetryAnalysisPointSerializer(analysis_payload['data'], many=True).data
                except Exception:
                    logger.warning('Failed to release lock or clear cache')
        analysis_payload = _ensure_payload_meta_checklist(analysis_payload, ['telemetry'], [])
        return analysis_payload

class AnalysisTelemetryOverlayAPIView(APIView):

    @extend_schema(operation_id='analysis_telemetry_overlay_retrieve', summary='Compare telemetry of two drivers', description="Loads telemetry for driver_a and driver_b and returns separate traces aligned by distance so the frontend can render an overlay chart. Both driver codes are required; laps default to returning all laps for each driver when omitted. Sector windowing and downsampling work the same as the single-driver telemetry endpoint.", parameters=[OpenApiParameter(name='session', location=OpenApiParameter.QUERY, required=False, type=str, description='R, Q, FP1, FP2, FP3'), OpenApiParameter(name='driver_a', location=OpenApiParameter.QUERY, required=True, type=str, description='First 3-letter driver code'), OpenApiParameter(name='driver_b', location=OpenApiParameter.QUERY, required=True, type=str, description='Second 3-letter driver code'), OpenApiParameter(name='lap_a', location=OpenApiParameter.QUERY, required=False, type=int, description='Optional lap number for driver_a. Omitting returns all laps.'), OpenApiParameter(name='lap_b', location=OpenApiParameter.QUERY, required=False, type=int, description='Optional lap number for driver_b. Omitting returns all laps.'), OpenApiParameter(name='limit_points', location=OpenApiParameter.QUERY, required=False, type=int, description='Maximum telemetry points per trace'), OpenApiParameter(name='stride', location=OpenApiParameter.QUERY, required=False, type=int, description='Sample every N points'), OpenApiParameter(name='sector_start', location=OpenApiParameter.QUERY, required=False, type=int, description='Sector window start (1-3)'), OpenApiParameter(name='sector_end', location=OpenApiParameter.QUERY, required=False, type=int, description='Sector window end (1-3)')], responses={200: TelemetryOverlayResponseSerializer, 400: OpenApiResponse(description='Missing or invalid telemetry overlay query parameters')}, examples=[OpenApiExample('Telemetry Overlay Missing Drivers', value={'error': 'driver_a and driver_b query parameters are required'}, response_only=True, status_codes=['400'])])
    def get(self, request, year, round_number):
        request.endpoint_type = 'telemetry_overlay'
        try:
            session_name = request.query_params.get('session', 'R')
            driver_a = request.query_params.get('driver_a')
            driver_b = request.query_params.get('driver_b')
            lap_a_param = request.query_params.get('lap_a')
            lap_b_param = request.query_params.get('lap_b')
            limit_points_param = request.query_params.get('limit_points')
            stride_param = request.query_params.get('stride', '1')
            sector_start_param = request.query_params.get('sector_start')
            sector_end_param = request.query_params.get('sector_end')
            if not driver_a or not driver_b:
                return Response({'error': 'driver_a and driver_b query parameters are required'}, status=400)
            lap_a = None
            if lap_a_param is not None and lap_a_param != '':
                try:
                    lap_a = int(lap_a_param)
                except (TypeError, ValueError):
                    return Response({'error': 'lap_a must be an integer'}, status=400)
            lap_b = None
            if lap_b_param is not None and lap_b_param != '':
                try:
                    lap_b = int(lap_b_param)
                except (TypeError, ValueError):
                    return Response({'error': 'lap_b must be an integer'}, status=400)
            try:
                stride = int(stride_param)
            except (TypeError, ValueError):
                return Response({'error': 'stride must be an integer'}, status=400)
            limit_points = None
            if limit_points_param is not None and limit_points_param != '':
                try:
                    limit_points = int(limit_points_param)
                except (TypeError, ValueError):
                    return Response({'error': 'limit_points must be an integer'}, status=400)
            sector_start = None
            if sector_start_param is not None and sector_start_param != '':
                try:
                    sector_start = int(sector_start_param)
                except (TypeError, ValueError):
                    return Response({'error': 'sector_start must be an integer'}, status=400)
            sector_end = None
            if sector_end_param is not None and sector_end_param != '':
                try:
                    sector_end = int(sector_end_param)
                except (TypeError, ValueError):
                    return Response({'error': 'sector_end must be an integer'}, status=400)
            cache_key = f'telemetry_overlay:{year}:{round_number}:{session_name}:{driver_a}:{driver_b}'
            if lap_a:
                cache_key += f':LA{lap_a}'
            if lap_b:
                cache_key += f':LB{lap_b}'
            if limit_points:
                cache_key += f':LP{limit_points}'
            if stride and stride != 1:
                cache_key += f':S{stride}'
            if sector_start:
                cache_key += f':SS{sector_start}'
            if sector_end:
                cache_key += f':SE{sector_end}'
            task_key = f'populate_telemetry_overlay:{year}:{round_number}:{session_name}:{driver_a}:{driver_b}'
            return handle_data_request(cache_key=cache_key, db_fetch_fn=lambda: self._fetch_telemetry_overlay_data(year, round_number, session_name, driver_a, driver_b, lap_a, lap_b, limit_points, stride, sector_start, sector_end), task_fn=populate_telemetry_overlay, task_key=task_key, task_args=(year, round_number, session_name), task_kwargs={'driver_a': driver_a, 'driver_b': driver_b, 'lap_a': lap_a, 'lap_b': lap_b, 'limit_points': limit_points, 'stride': stride, 'sector_start': sector_start, 'sector_end': sector_end}, timeout=180)
        except ValueError as exc:
            return Response({'error': str(exc)}, status=400)
        except Exception as exc:
            return Response(build_error_payload('analysis.telemetry_overlay', str(exc), 'ANALYSIS_TELEMETRY_OVERLAY_ERROR'), status=500)

    def _fetch_telemetry_overlay_data(self, year, round_number, session_name, driver_a, driver_b, lap_a, lap_b, limit_points, stride, sector_start, sector_end):
        """Fetch telemetry overlay data from analysis service."""
        from api.services.analysis import fetch_telemetry_overlay
        analysis_payload = fetch_telemetry_overlay(year=year, round_number=round_number, session=session_name, driver_a=driver_a, driver_b=driver_b, lap_a=lap_a, lap_b=lap_b, limit_points=limit_points, stride=stride, sector_start=sector_start, sector_end=sector_end)
        if analysis_payload is None:
            return None
        if isinstance(analysis_payload, dict):
            traces = analysis_payload.get('traces')
            if isinstance(traces, list):
                for t in traces:
                    if isinstance(t, dict) and 'data' in t:
                        try:
                            t['data'] = TelemetryAnalysisPointSerializer(t['data'], many=True).data
                        except Exception:
                            logger.warning('Failed to release lock or clear cache')
                analysis_payload['traces'] = traces
        analysis_payload = _ensure_payload_meta_checklist(analysis_payload, ['telemetry'], [])
        return analysis_payload

class AnalysisTelemetrySummaryAPIView(APIView):

    @extend_schema(operation_id='analysis_telemetry_summary_retrieve', summary='Get telemetry summary (lap, driver, or session)', description='Returns high-level statistics computed from telemetry: maximum speed, number of braking zones detected, percentage of the lap spent on full throttle, and total sample count. If driver and lap are omitted, it returns summaries for all laps across all drivers. Use sector_start / sector_end to restrict the summary to one part of the track.', parameters=[OpenApiParameter(name='session', location=OpenApiParameter.QUERY, required=False, type=str, description='R, Q, FP1, FP2, FP3'), OpenApiParameter(name='driver', location=OpenApiParameter.QUERY, required=False, type=str, description='Optional 3-letter driver code. Omitting returns all drivers.'), OpenApiParameter(name='lap', location=OpenApiParameter.QUERY, required=False, type=int, description='Optional lap number. Omitting returns all laps.'), OpenApiParameter(name='stride', location=OpenApiParameter.QUERY, required=False, type=int, description='Sample every N points'), OpenApiParameter(name='sector_start', location=OpenApiParameter.QUERY, required=False, type=int, description='Sector window start (1-3)'), OpenApiParameter(name='sector_end', location=OpenApiParameter.QUERY, required=False, type=int, description='Sector window end (1-3)')], responses={200: TelemetrySummaryResponseSerializer, 400: OpenApiResponse(description='Missing or invalid telemetry summary query parameters')}, examples=[])
    def get(self, request, year, round_number):
        request.endpoint_type = 'telemetry_summary'
        try:
            session_name = request.query_params.get('session', 'R')
            driver = request.query_params.get('driver')
            lap_param = request.query_params.get('lap')
            stride_param = request.query_params.get('stride', '1')
            sector_start_param = request.query_params.get('sector_start')
            sector_end_param = request.query_params.get('sector_end')
            lap = None
            if lap_param is not None and lap_param != '':
                try:
                    lap = int(lap_param)
                except (TypeError, ValueError):
                    return Response({'error': 'lap must be an integer'}, status=400)
            try:
                stride = int(stride_param)
            except (TypeError, ValueError):
                return Response({'error': 'stride must be an integer'}, status=400)
            sector_start = None
            if sector_start_param is not None and sector_start_param != '':
                try:
                    sector_start = int(sector_start_param)
                except (TypeError, ValueError):
                    return Response({'error': 'sector_start must be an integer'}, status=400)
            sector_end = None
            if sector_end_param is not None and sector_end_param != '':
                try:
                    sector_end = int(sector_end_param)
                except (TypeError, ValueError):
                    return Response({'error': 'sector_end must be an integer'}, status=400)
            cache_key = f'telemetry_summary:{year}:{round_number}:{session_name}:{driver}:{lap}'
            if stride and stride != 1:
                cache_key += f':S{stride}'
            if sector_start:
                cache_key += f':SS{sector_start}'
            if sector_end:
                cache_key += f':SE{sector_end}'
            task_key = f'populate_telemetry_summary:{year}:{round_number}:{session_name}:{driver}:{lap}'
            return handle_data_request(cache_key=cache_key, db_fetch_fn=lambda: self._fetch_telemetry_summary_data(year, round_number, session_name, driver, lap, stride, sector_start, sector_end), task_fn=populate_telemetry_summary, task_key=task_key, task_args=(year, round_number, session_name), task_kwargs={'driver': driver, 'lap': lap, 'stride': stride, 'sector_start': sector_start, 'sector_end': sector_end}, timeout=180)
        except ValueError as exc:
            return Response({'error': str(exc)}, status=400)
        except Exception as exc:
            return Response(build_error_payload('analysis.telemetry_summary', str(exc), 'ANALYSIS_TELEMETRY_SUMMARY_ERROR'), status=500)

    def _fetch_telemetry_summary_data(self, year, round_number, session_name, driver, lap, stride, sector_start, sector_end):
        """Fetch telemetry summary data from analysis service."""
        analysis_payload = get_telemetry_summary(year=year, round_number=round_number, session=session_name, driver=driver, lap=lap, stride=stride, sector_start=sector_start, sector_end=sector_end)
        if isinstance(analysis_payload, dict) and 'summary' in analysis_payload:
            try:
                analysis_payload['summary'] = TelemetrySummaryPayloadSerializer(analysis_payload['summary']).data
            except Exception:
                logger.warning('Failed to release lock or clear cache')
        analysis_payload = _ensure_payload_meta_checklist(analysis_payload, ['telemetry'], [])
        return analysis_payload

class UnifiedFullSessionAPIView(APIView):
    """Query multiple data types from a session simultaneously."""

    @extend_schema(operation_id='unified_full_session_retrieve', summary='Get multiple data types in one request', description='Accepts a comma-separated include parameter listing any combination of the six available data types: weather, pit_stops, incidents, positions, drs, track_status. The session is loaded once and shared across all extractors, making this far more efficient than calling each dedicated endpoint separately. Partial results are fully supported — if one data type fails the others are still returned, and the top-level can_proceed flag reflects whether at least one type succeeded.', parameters=[OpenApiParameter(name='session', location=OpenApiParameter.QUERY, required=False, type=str, description='R, Q, FP1, FP2, FP3'), OpenApiParameter(name='include', location=OpenApiParameter.QUERY, required=True, type=str, description='Comma-separated: weather,pit_stops,incidents,positions,drs,track_status'), OpenApiParameter(name='driver', location=OpenApiParameter.QUERY, required=False, type=str, description='Optional driver filter')], responses={200: inline_serializer(name='UnifiedFullSessionResponse', fields={'meta': drf_serializers.DictField(), 'data': drf_serializers.DictField()}), 400: OpenApiResponse(description='Invalid include/session parameters')}, examples=[OpenApiExample('Unified Partial Support', value={'meta': {'year': 2016, 'round': 3, 'session': 'R', 'requested_types': ['weather', 'incidents', 'positions'], 'cache_stats': {'cached_sessions': 1, 'hits': 0, 'misses': 1, 'hit_rate_percent': 0.0}, 'can_proceed': True, 'available_data': ['positions'], 'unavailable_data': ['weather', 'incidents'], 'message': "Partial support for 2016 Round 3 (R). Proceeding with: ['positions']. Unavailable: ['weather', 'incidents'].", 'warnings': ["Partial support for 2016 Round 3 (R). Proceeding with: ['positions']. Unavailable: ['weather', 'incidents'].", 'weather: No weather data available for this session', 'incidents: No messages data available for this session']}, 'data': {'positions': {'meta': {'row_count': 24}, 'filters_applied': {'driver': None, 'limit': None}, 'data': []}, 'weather': {'error': 'No weather data available for this session', 'status': 'failed'}, 'incidents': {'error': 'No messages data available for this session', 'status': 'failed'}}}, response_only=True, status_codes=['200'])])
    def get(self, request, year, round_number):
        request.endpoint_type = 'full_session'
        request_start = time.time()
        logger.info('event=api_request endpoint=unified_full_session year=%s round=%s', year, round_number)
        try:
            session_name = request.query_params.get('session', 'R').upper()
            include_param = request.query_params.get('include', '').strip()
            driver = request.query_params.get('driver')
            if not include_param:
                return Response({'error': 'include parameter required (e.g., ?include=weather,pit_stops,incidents)'}, status=400)
            include_types = [t.strip() for t in include_param.split(',') if t.strip()]
            invalid_types = [t for t in include_types if t not in EXTRACTORS_MAP]
            if invalid_types:
                return Response({'error': f'Unknown data types: {invalid_types}. Valid: {list(EXTRACTORS_MAP.keys())}'}, status=400)
            try:
                session = SessionManager.get_session(year, round_number, session_name, required_types=include_types)
            except Exception as exc:
                lowered = str(exc).lower()
                unsupported_markers = ('relevant api is not supported for this session', 'data you are trying to access has not been loaded yet', 'cannot load laps')
                if any((marker in lowered for marker in unsupported_markers)):
                    message = f'Session data is partially unsupported by FastF1 for {year} Round {round_number} ({session_name}). None of the requested includes can proceed: {include_types}.'
                    return Response({'meta': {'year': year, 'round': round_number, 'session': session_name, 'requested_types': include_types, 'cache_stats': SessionManager.get_cache_stats(), 'can_proceed': False, 'available_data': [], 'unavailable_data': include_types, 'message': message, 'warnings': [message]}, 'data': {}})
                raise
            extracted_data = {}
            available_data = []
            unavailable_data = []
            warnings = []
            for data_type in include_types:
                try:
                    extractor_class = EXTRACTORS_MAP[data_type]
                    extractor = extractor_class(session, year, round_number, session_name, driver=driver)
                    extracted = extractor.extract()
                    try:
                        if data_type == 'weather':
                            extracted = {**extracted, 'data': WeatherRowSerializer(extracted.get('data', []), many=True).data}
                        elif data_type == 'pit_stops':
                            extracted = {**extracted, 'data': PitStopRowSerializer(extracted.get('data', []), many=True).data}
                        elif data_type == 'incidents':
                            extracted = {**extracted, 'data': IncidentRowSerializer(extracted.get('data', []), many=True).data}
                        elif data_type == 'positions':
                            extracted = {**extracted, 'data': PositionChangeRowSerializer(extracted.get('data', []), many=True).data}
                        elif data_type == 'drs':
                            extracted = {**extracted, 'data': DRSRowSerializer(extracted.get('data', []), many=True).data}
                        elif data_type == 'track_status':
                            extracted = {**extracted, 'data': TrackStatusRowSerializer(extracted.get('data', []), many=True).data}
                    except Exception:
                        pass
                    extracted_data[data_type] = extracted
                    available_data.append(data_type)
                except Exception as e:
                    extracted_data[data_type] = {'error': str(e), 'status': 'failed'}
                    unavailable_data.append(data_type)
                    warnings.append(f'{data_type}: {str(e)}')
            can_proceed = len(available_data) > 0
            message = None
            if unavailable_data:
                message = f'Partial support for {year} Round {round_number} ({session_name}). Proceeding with: {available_data}. Unavailable: {unavailable_data}.'
                warnings.insert(0, message)
            if available_data:
                _session_end = getattr(session, 'date', None)
                if _session_end is not None:
                    if getattr(_session_end, 'tzinfo', None) is None:
                        _session_end = make_aware(_session_end)
                    if _session_end < timezone.now():
                        logger.info('event=api_live_fetch_success source=unified_session year=%s round=%s session=%s available_types=%s', year, round_number, session_name, available_data)
                        for data_type in available_data:
                            if data_type == 'weather':
                                if not WeatherData.objects.filter(year=int(year), round_number=int(round_number), session=session_name).exists():
                                    TaskManager.enqueue_if_needed(task_key=f'populate_weather:{int(year)}:{int(round_number)}:{session_name}', task_fn=populate_weather, year=int(year), round_number=int(round_number), session_type=session_name)
                            elif data_type == 'pit_stops':
                                if not PitStopData.objects.filter(year=int(year), round_number=int(round_number), session=session_name).exists():
                                    TaskManager.enqueue_if_needed(task_key=f'populate_pit_stops:{int(year)}:{int(round_number)}:{session_name}', task_fn=populate_pit_stops, year=int(year), round_number=int(round_number), session_type=session_name)
                            elif data_type == 'incidents':
                                if not IncidentData.objects.filter(year=int(year), round_number=int(round_number), session=session_name).exists():
                                    TaskManager.enqueue_if_needed(task_key=f'populate_incidents:{int(year)}:{int(round_number)}:{session_name}', task_fn=populate_incidents, year=int(year), round_number=int(round_number), session_type=session_name)
                            elif data_type == 'positions':
                                if not PositionData.objects.filter(year=int(year), round_number=int(round_number), session=session_name).exists():
                                    TaskManager.enqueue_if_needed(task_key=f'populate_positions:{int(year)}:{int(round_number)}:{session_name}', task_fn=populate_positions, year=int(year), round_number=int(round_number), session_type=session_name)
                            elif data_type == 'drs':
                                if not DRSData.objects.filter(year=int(year), round_number=int(round_number), session=session_name).exists():
                                    TaskManager.enqueue_if_needed(task_key=f'populate_drs:{int(year)}:{int(round_number)}:{session_name}', task_fn=populate_drs, year=int(year), round_number=int(round_number), session_type=session_name)
                            elif data_type == 'track_status':
                                if not TrackStatusData.objects.filter(year=int(year), round_number=int(round_number), session=session_name).exists():
                                    TaskManager.enqueue_if_needed(task_key=f'populate_track_status:{int(year)}:{int(round_number)}:{session_name}', task_fn=populate_track_status, year=int(year), round_number=int(round_number), session_type=session_name)
            response_data = {'meta': {'year': year, 'round': round_number, 'session': session_name, 'requested_types': include_types, 'cache_stats': SessionManager.get_cache_stats(), 'can_proceed': can_proceed, 'available_data': available_data, 'unavailable_data': unavailable_data, 'message': message, 'warnings': warnings}, 'data': extracted_data}
            duration_ms = int((time.time() - request_start) * 1000)
            logger.info('event=api_response_complete endpoint=unified_full_session duration_ms=%s status=200', duration_ms)
            return Response(response_data)
        except ValueError as exc:
            return Response({'error': str(exc)}, status=400)
        except Exception as exc:
            return Response(build_error_payload('unified.full_session', str(exc), 'UNIFIED_FULL_SESSION_ERROR'), status=500)

class UnifiedWeatherAPIView(APIView):
    """Extract weather data only."""

    @extend_schema(operation_id='unified_weather_retrieve', summary='Get session weather data', description='Returns time-series weather snapshots captured during the session: track temperature, air temperature, humidity, wind speed, wind direction, and a rainfall flag. Pass per_lap=true to align each snapshot to the closest lap number instead of raw timestamps. Useful for correlating tyre degradation or lap-time changes with ambient conditions.', parameters=[OpenApiParameter(name='session', location=OpenApiParameter.QUERY, required=False, type=str, description='R, Q, FP1, FP2, FP3. Default: R'), OpenApiParameter(name='per_lap', location=OpenApiParameter.QUERY, required=False, type=bool, description='Align snapshots to lap numbers')], responses={200: WeatherResponseSerializer})
    def get(self, request, year, round_number):
        request.endpoint_type = 'weather'
        try:
            session_name = request.query_params.get('session', 'R').upper()
            include_per_lap = request.query_params.get('per_lap', 'false').lower() == 'true'
            cache_key = f'weather:{year}:{round_number}:{session_name}'
            task_key = f'populate_weather:{year}:{round_number}:{session_name}'
            if include_per_lap:
                cache_key += ':per_lap'
                task_key += ':per_lap'
            return handle_data_request(cache_key=cache_key, db_fetch_fn=lambda: self._fetch_weather_data(year, round_number, session_name, include_per_lap), task_fn=populate_weather, task_key=task_key, task_args=(year, round_number, session_name), task_kwargs={'include_per_lap': include_per_lap})
        except ValueError as exc:
            return Response({'error': str(exc)}, status=400)
        except Exception as exc:
            if _is_unsupported_session_error(exc):
                message = f'Session data is partially unsupported by FastF1 for {year} Round {round_number} ({session_name}). Requested data type unavailable: weather.'
                return Response(_build_unified_unavailable_response(year=year, round_number=round_number, session_name=session_name, unavailable_type='weather', detail_message=message, driver=None, limit=None))
            return Response({'error': str(exc)}, status=500)

    def _fetch_weather_data(self, year, round_number, session_name, include_per_lap):
        from api.services.persistence import get_persisted_weather_data
        return get_persisted_weather_data(year, round_number, session_name, include_per_lap)

class UnifiedPitStopsAPIView(APIView):
    """Extract pit stop strategy data only."""

    @extend_schema(operation_id='unified_pit_stops_retrieve', summary='Get pit stop events', description="Returns one row per pit stop: driver, stop number, lap in, lap out, stop duration in seconds, the compound fitted before and after the stop, and an estimated time gain/loss. Primarily meaningful for Race sessions. Use the driver filter to isolate one team's strategy.", parameters=[OpenApiParameter(name='session', location=OpenApiParameter.QUERY, required=False, type=str, description='R, Q, FP1, FP2, FP3. Default: R'), OpenApiParameter(name='limit', location=OpenApiParameter.QUERY, required=False, type=int, description='Maximum rows to return')], responses={200: PitStopResponseSerializer})
    def get(self, request, year, round_number):
        request.endpoint_type = 'pit_stops'
        try:
            session_name = request.query_params.get('session', 'R').upper()
            limit_param = request.query_params.get('limit')
            limit = None
            if limit_param:
                try:
                    limit = int(limit_param)
                except ValueError:
                    return Response({'error': 'limit must be an integer'}, status=400)
            cache_key = f'pit_stops:{year}:{round_number}:{session_name}'
            task_key = f'populate_pit_stops:{year}:{round_number}:{session_name}'
            if limit:
                cache_key += f':limit:{limit}'
                task_key += f':limit:{limit}'
            return handle_data_request(cache_key=cache_key, db_fetch_fn=lambda: self._fetch_pit_stops_data(year, round_number, session_name, limit), task_fn=populate_pit_stops, task_key=task_key, task_args=(year, round_number, session_name), task_kwargs={'limit': limit})
        except ValueError as exc:
            return Response({'error': str(exc)}, status=400)
        except Exception as exc:
            if _is_unsupported_session_error(exc):
                message = f'Session data is partially unsupported by FastF1 for {year} Round {round_number} ({session_name}). Requested data type unavailable: pit_stops.'
                return Response(_build_unified_unavailable_response(year=year, round_number=round_number, session_name=session_name, unavailable_type='pit_stops', detail_message=message, driver=None, limit=None))
            return Response({'error': str(exc)}, status=500)

    def _fetch_pit_stops_data(self, year, round_number, session_name, limit):
        from api.services.persistence import get_persisted_pit_stops_data
        return get_persisted_pit_stops_data(year, round_number, session_name, limit)

class UnifiedIncidentsAPIView(APIView):
    """Extract incidents and messages."""

    @extend_schema(operation_id='unified_incidents_retrieve', summary='Get race-control incidents', description='Parses the session race-control messages feed and returns structured incident rows: lap number, message type (e.g. SAFETY_CAR, COLLISION, PENALTY), drivers involved, the raw message text, a timestamp in seconds, and an impact classification. Race-control messages are only available for seasons where FastF1 carries this data stream; older seasons return can_proceed=false.', parameters=[OpenApiParameter(name='session', location=OpenApiParameter.QUERY, required=False, type=str, description='R, Q, FP1, FP2, FP3. Default: R'), OpenApiParameter(name='limit', location=OpenApiParameter.QUERY, required=False, type=int, description='Maximum rows to return'), OpenApiParameter(name='radio', location=OpenApiParameter.QUERY, required=False, type=bool, description='Include team radio messages')], responses={200: IncidentResponseSerializer})
    def get(self, request, year, round_number):
        request.endpoint_type = 'incidents'
        try:
            session_name = request.query_params.get('session', 'R').upper()
            include_radio = request.query_params.get('radio', 'false').lower() == 'true'
            limit_param = request.query_params.get('limit')
            limit = None
            if limit_param:
                try:
                    limit = int(limit_param)
                except ValueError:
                    return Response({'error': 'limit must be an integer'}, status=400)
            cache_key = f'incidents:{year}:{round_number}:{session_name}'
            task_key = f'populate_incidents:{year}:{round_number}:{session_name}'
            if limit:
                cache_key += f':limit:{limit}'
                task_key += f':limit:{limit}'
            if include_radio:
                cache_key += ':radio'
                task_key += ':radio'
            return handle_data_request(cache_key=cache_key, db_fetch_fn=lambda: self._fetch_incidents_data(year, round_number, session_name, limit, include_radio), task_fn=populate_incidents, task_key=task_key, task_args=(year, round_number, session_name), task_kwargs={'limit': limit, 'include_radio': include_radio})
        except ValueError as exc:
            return Response({'error': str(exc)}, status=400)
        except Exception as exc:
            if _is_unsupported_session_error(exc):
                message = f'Session data is partially unsupported by FastF1 for {year} Round {round_number} ({session_name}). Requested data type unavailable: incidents.'
                return Response(_build_unified_unavailable_response(year=year, round_number=round_number, session_name=session_name, unavailable_type='incidents', detail_message=message, driver=None, limit=None))
            return Response({'error': str(exc)}, status=500)

    def _fetch_incidents_data(self, year, round_number, session_name, limit, include_radio):
        from api.services.persistence import get_persisted_incidents_data
        return get_persisted_incidents_data(year, round_number, session_name, limit, include_radio)

class UnifiedPositionsAPIView(APIView):
    """Extract position and gap data."""

    @extend_schema(operation_id='unified_positions_retrieve', summary='Get lap-by-lap position changes', description='Returns a row per driver per lap showing on-track position, the change in position versus the previous lap, gap to the leader, and gap to the car directly ahead. Each row also includes stint, track status, lap time in seconds, and fastest-lap flags (overall and per-lap-number). Particularly useful for animated race-progression charts and race-pace analysis.', parameters=[OpenApiParameter(name='session', location=OpenApiParameter.QUERY, required=False, type=str, description='R, Q, FP1, FP2, FP3. Default: R'), OpenApiParameter(name='sample_interval', location=OpenApiParameter.QUERY, required=False, type=int, description='Sample every N laps (default 5)')], responses={200: PositionResponseSerializer})
    def get(self, request, year, round_number):
        request.endpoint_type = 'positions'
        try:
            session_name = request.query_params.get('session', 'R').upper()
            sample_interval = request.query_params.get('sample_interval', '5')
            try:
                sample_interval = int(sample_interval)
            except ValueError:
                return Response({'error': 'sample_interval must be an integer'}, status=400)
            cache_key = f'positions:{year}:{round_number}:{session_name}:interval:{sample_interval}'
            task_key = f'populate_positions:{year}:{round_number}:{session_name}:interval:{sample_interval}'
            return handle_data_request(cache_key=cache_key, db_fetch_fn=lambda: self._fetch_positions_data(year, round_number, session_name, sample_interval), task_fn=populate_positions, task_key=task_key, task_args=(year, round_number, session_name), task_kwargs={'sample_interval': sample_interval})
        except ValueError as exc:
            return Response({'error': str(exc)}, status=400)
        except Exception as exc:
            if _is_unsupported_session_error(exc):
                message = f'Session data is partially unsupported by FastF1 for {year} Round {round_number} ({session_name}). Requested data type unavailable: positions.'
                return Response(_build_unified_unavailable_response(year=year, round_number=round_number, session_name=session_name, unavailable_type='positions', detail_message=message, driver=None, limit=None))
            return Response({'error': str(exc)}, status=500)

    def _fetch_positions_data(self, year, round_number, session_name, sample_interval):
        from api.services.persistence import get_persisted_positions_data
        return get_persisted_positions_data(year, round_number, session_name, sample_interval)

class UnifiedDRSAPIView(APIView):
    """Extract DRS activation data."""

    @extend_schema(operation_id='unified_drs_retrieve', summary='Get DRS activation data', description='Returns per-driver per-lap DRS state: whether DRS was available on that lap (gap to the car ahead <=1 second at the detection point), whether it was actually activated, the gap behind in seconds, and a performance delta in milliseconds. Useful for visualising how much DRS influenced overtaking opportunities.', parameters=[OpenApiParameter(name='session', location=OpenApiParameter.QUERY, required=False, type=str, description='R, Q, FP1, FP2, FP3. Default: R'), OpenApiParameter(name='driver', location=OpenApiParameter.QUERY, required=False, type=str, description='3-letter driver code filter')], responses={200: DRSResponseSerializer})
    def get(self, request, year, round_number):
        request.endpoint_type = 'drs'
        try:
            session_name = request.query_params.get('session', 'R').upper()
            driver = request.query_params.get('driver')
            cache_key = f'drs:{year}:{round_number}:{session_name}'
            task_key = f'populate_drs:{year}:{round_number}:{session_name}'
            if driver:
                cache_key += f':driver:{driver}'
                task_key += f':driver:{driver}'
            return handle_data_request(cache_key=cache_key, db_fetch_fn=lambda: self._fetch_drs_data(year, round_number, session_name, driver), task_fn=populate_drs, task_key=task_key, task_args=(year, round_number, session_name), task_kwargs={'driver': driver})
        except ValueError as exc:
            return Response({'error': str(exc)}, status=400)
        except Exception as exc:
            if _is_unsupported_session_error(exc):
                message = f'Session data is partially unsupported by FastF1 for {year} Round {round_number} ({session_name}). Requested data type unavailable: drs.'
                return Response(_build_unified_unavailable_response(year=year, round_number=round_number, session_name=session_name, unavailable_type='drs', detail_message=message, driver=driver, limit=None))
            return Response({'error': str(exc)}, status=500)

    def _fetch_drs_data(self, year, round_number, session_name, driver):
        from api.services.persistence import get_persisted_drs_data
        return get_persisted_drs_data(year, round_number, session_name, driver)

class UnifiedTrackStatusAPIView(APIView):
    """Extract track status timeline."""

    @extend_schema(operation_id='unified_track_status_retrieve', summary='Get track status timeline', description='Returns the sequence of official track-status changes broadcast during the session. Each row includes the lap number, status code (GREEN, YELLOW, RED, SAFETY_CAR, VSC), how many laps that status persisted, the cause if available, and the affected track zone. Essential context for understanding lap-time anomalies caused by caution periods.', parameters=[OpenApiParameter(name='session', location=OpenApiParameter.QUERY, required=False, type=str, description='R, Q, FP1, FP2, FP3. Default: R')], responses={200: TrackStatusResponseSerializer})
    def get(self, request, year, round_number):
        request.endpoint_type = 'track_status'
        try:
            session_name = request.query_params.get('session', 'R').upper()
            cache_key = f'track_status:{year}:{round_number}:{session_name}'
            task_key = f'populate_track_status:{year}:{round_number}:{session_name}'
            return handle_data_request(cache_key=cache_key, db_fetch_fn=lambda: self._fetch_track_status_data(year, round_number, session_name), task_fn=populate_track_status, task_key=task_key, task_args=(year, round_number, session_name))
        except ValueError as exc:
            return Response({'error': str(exc)}, status=400)
        except Exception as exc:
            if _is_unsupported_session_error(exc):
                message = f'Session data is partially unsupported by FastF1 for {year} Round {round_number} ({session_name}). Requested data type unavailable: track_status.'
                return Response(_build_unified_unavailable_response(year=year, round_number=round_number, session_name=session_name, unavailable_type='track_status', detail_message=message, driver=None, limit=None))
            return Response({'error': str(exc)}, status=500)

    def _fetch_track_status_data(self, year, round_number, session_name):
        from api.services.persistence import get_persisted_track_status_data
        return get_persisted_track_status_data(year, round_number, session_name)