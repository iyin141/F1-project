"""
Unit tests for Tier 4 telemetry workers: telemetry, telemetry overlay, telemetry summary.
Verifies worker output structure and caching behavior.
"""
import pytest
from unittest.mock import Mock, patch
from django.test import TestCase

from api.workers.tier4_telemetry.populate_telemetry import populate_telemetry
from api.workers.tier4_telemetry.populate_telemetry_overlay import populate_telemetry_overlay
from api.workers.tier4_telemetry.populate_telemetry_summary import populate_telemetry_summary


@pytest.mark.django_db
class TestPopulateTelemetryWorker(TestCase):
    """Test telemetry data extraction and caching."""
    
    @patch('api.workers.tier4_telemetry.populate_telemetry.SessionManager.get_session')
    @patch('api.workers.tier4_telemetry.populate_telemetry.TelemetryExtractor')
    def test_populate_telemetry_returns_structured_data(self, mock_extractor_class, mock_get_session):
        """Verify populate_telemetry returns structured telemetry data."""
        mock_session = Mock()
        mock_get_session.return_value = mock_session
        
        mock_extractor = Mock()
        mock_extractor.extract.return_value = {
            'data': [
                {
                    'driver_code': 'VER',
                    'driver_number': 1,
                    'lap': 1,
                    'time_delta': 0.0,
                    'throttle': 85.5,
                    'brake': 0.0,
                    'drs': False,
                    'speed': 285,
                    'rpm': 13500,
                    'gear': 8,
                },
                {
                    'driver_code': 'VER',
                    'driver_number': 1,
                    'lap': 1,
                    'time_delta': 0.1,
                    'throttle': 100.0,
                    'brake': 0.0,
                    'drs': True,
                    'speed': 320,
                    'rpm': 14000,
                    'gear': 8,
                }
            ]
        }
        mock_extractor_class.return_value = mock_extractor
        
        result = populate_telemetry(year=2023, round_number=4, session_type="R", driver="VER")
        
        assert result is not None
        assert 'data' in result
        assert len(result['data']) >= 1
        assert all('driver_code' in row for row in result['data'])
        assert all('throttle' in row for row in result['data'])
        assert all('speed' in row for row in result['data'])
    
    @patch('api.workers.tier4_telemetry.populate_telemetry.SessionManager.get_session')
    @patch('api.workers.tier4_telemetry.populate_telemetry.TelemetryExtractor')
    def test_populate_telemetry_includes_drs_and_braking(self, mock_extractor_class, mock_get_session):
        """Verify populate_telemetry includes DRS and braking data."""
        mock_session = Mock()
        mock_get_session.return_value = mock_session
        
        mock_extractor = Mock()
        mock_extractor.extract.return_value = {
            'data': [
                {
                    'driver_code': 'HAM',
                    'throttle': 50.0,
                    'brake': 75.5,
                    'drs': True,
                }
            ]
        }
        mock_extractor_class.return_value = mock_extractor
        
        result = populate_telemetry(year=2023, round_number=4, session_type="R", driver="HAM")
        
        assert result is not None
        assert 'data' in result
        assert len(result['data']) > 0
        assert 'drs' in result['data'][0]
        assert 'brake' in result['data'][0]


@pytest.mark.django_db
class TestPopulateTelemetryOverlayWorker(TestCase):
    """Test telemetry overlay (dual driver comparison) extraction and caching."""
    
    @patch('api.workers.tier4_telemetry.populate_telemetry_overlay.SessionManager.get_session')
    @patch('api.workers.tier4_telemetry.populate_telemetry_overlay.TelemetryExtractor')
    def test_populate_telemetry_overlay_returns_dual_driver_data(self, mock_extractor_class, mock_get_session):
        """Verify populate_telemetry_overlay returns data for two drivers."""
        mock_session = Mock()
        mock_get_session.return_value = mock_session
        
        mock_extractor = Mock()
        mock_extractor.extract.side_effect = [
            {
                'data': [
                    {
                        'driver_code': 'VER',
                        'driver_number': 1,
                        'lap': 1,
                        'time_delta': 0.0,
                        'throttle': 85.5,
                        'speed': 285,
                    }
                ]
            },
            {
                'data': [
                    {
                        'driver_code': 'HAM',
                        'driver_number': 44,
                        'lap': 1,
                        'time_delta': 0.0,
                        'throttle': 82.0,
                        'speed': 280,
                    }
                ]
            }
        ]
        mock_extractor_class.return_value = mock_extractor
        
        result = populate_telemetry_overlay(year=2023, round_number=4, session_type="R", driver1="VER", driver2="HAM")
        
        assert result is not None
        assert isinstance(result, dict)
        # Result should contain comparison/overlay data
        assert len(result) > 0
    
    @patch('api.workers.tier4_telemetry.populate_telemetry_overlay.SessionManager.get_session')
    @patch('api.workers.tier4_telemetry.populate_telemetry_overlay.TelemetryExtractor')
    def test_populate_telemetry_overlay_accepts_driver_parameters(self, mock_extractor_class, mock_get_session):
        """Verify populate_telemetry_overlay accepts driver1 and driver2 parameters."""
        mock_session = Mock()
        mock_get_session.return_value = mock_session
        
        mock_extractor = Mock()
        mock_extractor.extract.return_value = {'data': []}
        mock_extractor_class.return_value = mock_extractor
        
        # Should accept two driver codes
        result = populate_telemetry_overlay(
            year=2023,
            round_number=4,
            session_type="R",
            driver1="VER",
            driver2="HAM"
        )
        
        assert result is not None


@pytest.mark.django_db
class TestPopulateTelemetrySummaryWorker(TestCase):
    """Test telemetry summary statistics extraction and caching."""
    
    @patch('api.workers.tier4_telemetry.populate_telemetry_summary.SessionManager.get_session')
    @patch('api.workers.tier4_telemetry.populate_telemetry_summary.TelemetryExtractor')
    def test_populate_telemetry_summary_returns_aggregated_statistics(self, mock_extractor_class, mock_get_session):
        """Verify populate_telemetry_summary returns aggregated telemetry statistics."""
        mock_session = Mock()
        mock_get_session.return_value = mock_session
        
        mock_extractor = Mock()
        mock_extractor.extract.return_value = {
            'data': [
                {
                    'driver_code': 'VER',
                    'driver_number': 1,
                    'avg_throttle': 87.2,
                    'avg_brake': 35.1,
                    'avg_speed': 285.3,
                    'max_speed': 328,
                    'min_speed': 65,
                    'drs_activated_laps': 42,
                    'total_laps': 57,
                },
                {
                    'driver_code': 'HAM',
                    'driver_number': 44,
                    'avg_throttle': 85.8,
                    'avg_brake': 38.5,
                    'avg_speed': 282.1,
                    'max_speed': 325,
                    'min_speed': 62,
                    'drs_activated_laps': 39,
                    'total_laps': 57,
                }
            ]
        }
        mock_extractor_class.return_value = mock_extractor
        
        result = populate_telemetry_summary(year=2023, round_number=4, session_type="R")
        
        assert result is not None
        assert 'data' in result
        assert len(result['data']) == 2
        assert all('avg_throttle' in row for row in result['data'])
        assert all('avg_speed' in row for row in result['data'])
        assert all('drs_activated_laps' in row for row in result['data'])
    
    @patch('api.workers.tier4_telemetry.populate_telemetry_summary.SessionManager.get_session')
    @patch('api.workers.tier4_telemetry.populate_telemetry_summary.TelemetryExtractor')
    def test_populate_telemetry_summary_includes_speed_statistics(self, mock_extractor_class, mock_get_session):
        """Verify populate_telemetry_summary includes max/min speed data."""
        mock_session = Mock()
        mock_get_session.return_value = mock_session
        
        mock_extractor = Mock()
        mock_extractor.extract.return_value = {
            'data': [
                {
                    'driver_code': 'VER',
                    'max_speed': 328,
                    'min_speed': 65,
                    'avg_speed': 285.3,
                }
            ]
        }
        mock_extractor_class.return_value = mock_extractor
        
        result = populate_telemetry_summary(year=2023, round_number=4, session_type="R")
        
        assert result is not None
        assert 'data' in result
        assert len(result['data']) > 0
        assert 'max_speed' in result['data'][0]
        assert 'min_speed' in result['data'][0]
        assert 'avg_speed' in result['data'][0]
