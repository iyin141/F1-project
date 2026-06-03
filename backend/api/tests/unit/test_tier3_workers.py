"""
Unit tests for Tier 3 workers: positions, DRS, track status, laps.
Verifies worker output structure and database persistence.
"""
import pytest
from unittest.mock import Mock, patch
from django.test import TestCase

from api.workers.tier3_medium.populate_positions import populate_positions
from api.workers.tier3_medium.populate_drs import populate_drs
from api.workers.tier3_medium.populate_track_status import populate_track_status
from api.workers.tier3_medium.populate_laps import populate_laps

from api.models import PositionData, DRSData, TrackStatusData


@pytest.mark.django_db
class TestPopulatePositionsWorker(TestCase):
    """Test position changes extraction and persistence."""
    
    @patch('api.workers.tier3_medium.populate_positions.SessionManager.get_session')
    @patch('api.workers.tier3_medium.populate_positions.PositionExtractor')
    def test_populate_positions_returns_correct_structure(self, mock_extractor_class, mock_get_session):
        """Verify populate_positions returns structured data with required fields."""
        mock_session = Mock()
        mock_get_session.return_value = mock_session
        
        mock_extractor = Mock()
        mock_extractor.extract.return_value = {
            'data': [
                {
                    'lap': 1,
                    'driver_number': 1,
                    'driver_code': 'VER',
                    'position': 1,
                    'gap_to_leader': None,
                },
                {
                    'lap': 1,
                    'driver_number': 44,
                    'driver_code': 'HAM',
                    'position': 2,
                    'gap_to_leader': 0.234,
                }
            ]
        }
        mock_extractor_class.return_value = mock_extractor
        
        result = populate_positions(year=2023, round_number=4, session_type="R")
        
        assert result is not None
        assert 'data' in result
        assert len(result['data']) == 2
        assert all('driver_code' in row for row in result['data'])
        assert all('position' in row for row in result['data'])
    
    @patch('api.workers.tier3_medium.populate_positions.SessionManager.get_session')
    @patch('api.workers.tier3_medium.populate_positions.PositionExtractor')
    def test_populate_positions_persists_to_database(self, mock_extractor_class, mock_get_session):
        """Verify populate_positions creates PositionData record with correct payload."""
        mock_session = Mock()
        mock_get_session.return_value = mock_session
        
        mock_extractor = Mock()
        mock_extractor.extract.return_value = {
            'data': [
                {'lap': 1, 'driver_code': 'VER', 'position': 1}
            ]
        }
        mock_extractor_class.return_value = mock_extractor
        
        populate_positions(year=2023, round_number=4, session_type="R")
        
        record = PositionData.objects.get(year=2023, round_number=4, session="R")
        assert record.payload == {'data': [{'lap': 1, 'driver_code': 'VER', 'position': 1}]}
        assert record.created_at is not None


@pytest.mark.django_db
class TestPopulateDRSWorker(TestCase):
    """Test DRS activation data extraction and persistence."""
    
    @patch('api.workers.tier3_medium.populate_drs.SessionManager.get_session')
    @patch('api.workers.tier3_medium.populate_drs.DRSExtractor')
    def test_populate_drs_returns_correct_structure(self, mock_extractor_class, mock_get_session):
        """Verify populate_drs returns structured data with required fields."""
        mock_session = Mock()
        mock_get_session.return_value = mock_session
        
        mock_extractor = Mock()
        mock_extractor.extract.return_value = {
            'data': [
                {
                    'lap': 5,
                    'driver_number': 1,
                    'driver_code': 'VER',
                    'status': 'AVAILABLE',
                    'time': '2023-04-30T11:20:00Z',
                },
                {
                    'lap': 6,
                    'driver_number': 44,
                    'driver_code': 'HAM',
                    'status': 'USED',
                    'time': '2023-04-30T11:22:00Z',
                }
            ]
        }
        mock_extractor_class.return_value = mock_extractor
        
        result = populate_drs(year=2023, round_number=4, session_type="R")
        
        assert result is not None
        assert 'data' in result
        assert len(result['data']) == 2
        assert all('status' in row for row in result['data'])
        assert all('lap' in row for row in result['data'])
    
    @patch('api.workers.tier3_medium.populate_drs.SessionManager.get_session')
    @patch('api.workers.tier3_medium.populate_drs.DRSExtractor')
    def test_populate_drs_persists_to_database(self, mock_extractor_class, mock_get_session):
        """Verify populate_drs creates DRSData record with correct payload."""
        mock_session = Mock()
        mock_get_session.return_value = mock_session
        
        mock_extractor = Mock()
        mock_extractor.extract.return_value = {
            'data': [
                {'lap': 5, 'driver_code': 'VER', 'status': 'AVAILABLE'}
            ]
        }
        mock_extractor_class.return_value = mock_extractor
        
        populate_drs(year=2023, round_number=4, session_type="R")
        
        record = DRSData.objects.get(year=2023, round_number=4, session="R")
        assert record.payload == {'data': [{'lap': 5, 'driver_code': 'VER', 'status': 'AVAILABLE'}]}
        assert record.created_at is not None


@pytest.mark.django_db
class TestPopulateTrackStatusWorker(TestCase):
    """Test track status changes extraction and persistence."""
    
    @patch('api.workers.tier3_medium.populate_track_status.SessionManager.get_session')
    @patch('api.workers.tier3_medium.populate_track_status.TrackStatusExtractor')
    def test_populate_track_status_returns_correct_structure(self, mock_extractor_class, mock_get_session):
        """Verify populate_track_status returns structured data with required fields."""
        mock_session = Mock()
        mock_get_session.return_value = mock_session
        
        mock_extractor = Mock()
        mock_extractor.extract.return_value = {
            'data': [
                {
                    'lap': 0,
                    'time': '2023-04-30T11:00:00Z',
                    'status': 'GREEN',
                    'message': 'Race start',
                },
                {
                    'lap': 10,
                    'time': '2023-04-30T11:15:00Z',
                    'status': 'YELLOW',
                    'message': 'Incident at Turn 1',
                }
            ]
        }
        mock_extractor_class.return_value = mock_extractor
        
        result = populate_track_status(year=2023, round_number=4, session_type="R")
        
        assert result is not None
        assert 'data' in result
        assert len(result['data']) == 2
        assert all('status' in row for row in result['data'])
        assert all('message' in row for row in result['data'])
    
    @patch('api.workers.tier3_medium.populate_track_status.SessionManager.get_session')
    @patch('api.workers.tier3_medium.populate_track_status.TrackStatusExtractor')
    def test_populate_track_status_persists_to_database(self, mock_extractor_class, mock_get_session):
        """Verify populate_track_status creates TrackStatusData record with correct payload."""
        mock_session = Mock()
        mock_get_session.return_value = mock_session
        
        mock_extractor = Mock()
        mock_extractor.extract.return_value = {
            'data': [
                {'lap': 0, 'status': 'GREEN', 'message': 'Race start'}
            ]
        }
        mock_extractor_class.return_value = mock_extractor
        
        populate_track_status(year=2023, round_number=4, session_type="R")
        
        record = TrackStatusData.objects.get(year=2023, round_number=4, session="R")
        assert record.payload == {'data': [{'lap': 0, 'status': 'GREEN', 'message': 'Race start'}]}
        assert record.created_at is not None


@pytest.mark.django_db
class TestPopulateLapsWorker(TestCase):
    """Test lap analysis extraction and persistence."""
    
    @patch('api.workers.tier3_medium.populate_laps.SessionManager.get_session')
    @patch('api.workers.tier3_medium.populate_laps.get_pace_analysis')
    def test_populate_laps_returns_correct_structure(self, mock_get_pace, mock_get_session):
        """Verify populate_laps returns structured data with required fields."""
        mock_session = Mock()
        mock_get_session.return_value = mock_session
        
        mock_get_pace.return_value = {
            'data': [
                {
                    'driver_code': 'VER',
                    'driver_number': 1,
                    'laps_completed': 57,
                    'median_lap_seconds': 95.5,
                    'consistency_stddev_seconds': 0.42,
                },
                {
                    'driver_code': 'HAM',
                    'driver_number': 44,
                    'laps_completed': 57,
                    'median_lap_seconds': 96.2,
                    'consistency_stddev_seconds': 0.55,
                }
            ]
        }
        
        result = populate_laps(year=2023, round_number=4, session_type="R")
        
        assert result is not None
        assert 'data' in result
        assert len(result['data']) == 2
        assert all('driver_code' in row for row in result['data'])
        assert all('laps_completed' in row for row in result['data'])
    
    @patch('api.workers.tier3_medium.populate_laps.SessionManager.get_session')
    @patch('api.workers.tier3_medium.populate_laps.get_pace_analysis')
    def test_populate_laps_structure_includes_pace_data(self, mock_get_pace, mock_get_session):
        """Verify populate_laps includes pace analysis data in return."""
        mock_session = Mock()
        mock_get_session.return_value = mock_session
        
        mock_get_pace.return_value = {
            'data': [
                {
                    'driver_code': 'VER',
                    'median_lap_seconds': 95.5,
                    'consistency_stddev_seconds': 0.42,
                }
            ]
        }
        
        result = populate_laps(year=2023, round_number=4, session_type="R")
        
        assert result is not None
        assert 'data' in result
        assert len(result['data']) > 0
        # Verify pace-specific fields
        assert any('median_lap_seconds' in row for row in result['data'])
