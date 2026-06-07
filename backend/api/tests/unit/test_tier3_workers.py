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

    @patch('api.workers.tier3_medium.populate_positions.worker_utils.handle_result')
    @patch('api.workers.tier3_medium.populate_positions.PositionExtractor')
    def test_populate_positions_returns_correct_structure(self, mock_extractor_class, mock_handle_result):
        """Verify populate_positions returns structured data with required fields."""
        mock_extractor_instance = mock_extractor_class.return_value
        mock_extractor_instance.extract.return_value = {'meta': {'year': 2023, 'round': 4, 'session': 'R', 'can_proceed': True, 'row_count': 2, 'limit_max': 1000}, 'filters_applied': {}, 'data': [{'driver_code': 'VER', 'driver_number': 1, 'position': 1, 'lap': 1, 'time_seconds': 95.5, 'is_personal_best': False, 'compound': 'SOFT', 'pit_status': 'none', 'is_personal_best': False, 'compound': 'SOFT', 'pit_status': 'none'}, {'driver_code': 'HAM', 'driver_number': 44, 'position': 2, 'lap': 1, 'time_seconds': 96.2}]}
        populate_positions(task_key='mock', year=2023, round_number=4, session_type='R')
        mock_handle_result.assert_called_once()
        result = mock_handle_result.call_args[1]['serialized_data']
        assert 'data' in result
        assert len(result['data']) == 2
        assert all(('driver_code' in row for row in result['data']))
        assert all(('position' in row for row in result['data']))

    @patch('api.workers.tier3_medium.populate_positions.worker_utils.handle_result')
    @patch('api.workers.tier3_medium.populate_positions.PositionExtractor')
    @pytest.mark.skip(reason='Legacy test incompatible with pure DB fetchers')
    def test_populate_positions_persists_to_database(self, mock_extractor_class, mock_handle_result):
        """Verify populate_positions creates PositionData record with correct payload."""
        mock_extractor_instance = mock_extractor_class.return_value
        mock_extractor_instance.extract.return_value = {'meta': {'year': 2023, 'round': 4, 'session': 'R', 'can_proceed': True, 'row_count': 2, 'limit_max': 1000}, 'filters_applied': {}, 'data': [{'lap': 1, 'driver_code': 'VER', 'position': 1}]}
        populate_positions(task_key='mock', year=2023, round_number=4, session_type='R')
        assert PositionData.objects.filter(year=2023, round_number=4, session='R').exists()
        record = PositionData.objects.get(year=2023, round_number=4, session='R')
        assert record.payload == {'data': [{'lap': 1, 'driver_code': 'VER', 'position': 1}]}
        assert record.created_at is not None

@pytest.mark.django_db
class TestPopulateDRSWorker(TestCase):
    """Test DRS activation data extraction and persistence."""

    @patch('api.workers.tier3_medium.populate_drs.worker_utils.handle_result')
    @patch('api.workers.tier3_medium.populate_drs.DRSExtractor')
    def test_populate_drs_returns_correct_structure(self, mock_extractor_class, mock_handle_result):
        """Verify populate_drs returns structured data with required fields."""
        mock_extractor_instance = mock_extractor_class.return_value
        mock_extractor_instance.extract.return_value = {'meta': {'year': 2023, 'round': 4, 'session': 'R', 'can_proceed': True, 'row_count': 2, 'limit_max': 1000}, 'filters_applied': {}, 'data': [{'status': 'ON', 'lap': 3, 'time_seconds': 180.5}, {'status': 'OFF', 'lap': 57, 'time_seconds': 5400.2}]}
        populate_drs(task_key='mock', year=2023, round_number=4, session_type='R')
        mock_handle_result.assert_called_once()
        result = mock_handle_result.call_args[1]['serialized_data']
        assert 'data' in result
        assert len(result['data']) == 2
        assert all(('status' in row for row in result['data']))
        assert all(('lap' in row for row in result['data']))

    @patch('api.workers.tier3_medium.populate_drs.worker_utils.handle_result')
    @patch('api.workers.tier3_medium.populate_drs.DRSExtractor')
    @pytest.mark.skip(reason='Legacy test incompatible with pure DB fetchers')
    def test_populate_drs_persists_to_database(self, mock_extractor_class, mock_handle_result):
        """Verify populate_drs creates DRSData record with correct payload."""
        mock_extractor_instance = mock_extractor_class.return_value
        mock_extractor_instance.extract.return_value = {'meta': {'year': 2023, 'round': 4, 'session': 'R', 'can_proceed': True, 'row_count': 2, 'limit_max': 1000}, 'filters_applied': {}, 'data': [{'lap': 5, 'driver_code': 'VER', 'status': 'AVAILABLE'}]}
        populate_drs(task_key='mock', year=2023, round_number=4, session_type='R')
        assert DRSData.objects.filter(year=2023, round_number=4, session='R').exists()
        record = DRSData.objects.get(year=2023, round_number=4, session='R')
        assert record.payload == {'data': [{'lap': 5, 'driver_code': 'VER', 'status': 'AVAILABLE'}]}
        assert record.created_at is not None

@pytest.mark.django_db
class TestPopulateTrackStatusWorker(TestCase):
    """Test track status changes extraction and persistence."""

    @patch('api.workers.tier3_medium.populate_track_status.worker_utils.handle_result')
    @patch('api.workers.tier3_medium.populate_track_status.TrackStatusExtractor')
    def test_populate_track_status_returns_correct_structure(self, mock_extractor_class, mock_handle_result):
        """Verify populate_track_status returns structured data with required fields."""
        mock_extractor_instance = mock_extractor_class.return_value
        mock_extractor_instance.extract.return_value = {'meta': {'year': 2023, 'round': 4, 'session': 'R', 'can_proceed': True, 'row_count': 2, 'limit_max': 1000}, 'filters_applied': {}, 'data': [{'status': '1', 'message': 'AllClear', 'time_seconds': 0.0}, {'status': '4', 'message': 'SafetyCar', 'time_seconds': 1500.5}]}
        populate_track_status(task_key='mock', year=2023, round_number=4, session_type='R')
        mock_handle_result.assert_called_once()
        result = mock_handle_result.call_args[1]['serialized_data']
        assert 'data' in result
        assert len(result['data']) == 2
        assert all(('status' in row for row in result['data']))
        assert all(('message' in row for row in result['data']))

    @patch('api.workers.tier3_medium.populate_track_status.worker_utils.handle_result')
    @patch('api.workers.tier3_medium.populate_track_status.TrackStatusExtractor')
    @pytest.mark.skip(reason='Legacy test incompatible with pure DB fetchers')
    def test_populate_track_status_persists_to_database(self, mock_extractor_class, mock_handle_result):
        """Verify populate_track_status creates TrackStatusData record with correct payload."""
        mock_extractor_instance = mock_extractor_class.return_value
        mock_extractor_instance.extract.return_value = {'meta': {'year': 2023, 'round': 4, 'session': 'R', 'can_proceed': True, 'row_count': 2, 'limit_max': 1000}, 'filters_applied': {}, 'data': [{'lap': 0, 'status': 'GREEN', 'message': 'Race start'}]}
        populate_track_status(task_key='mock', year=2023, round_number=4, session_type='R')
        assert TrackStatusData.objects.filter(year=2023, round_number=4, session='R').exists()
        record = TrackStatusData.objects.get(year=2023, round_number=4, session='R')
        assert record.payload == {'data': [{'lap': 0, 'status': 'GREEN', 'message': 'Race start'}]}
        assert record.created_at is not None

@pytest.mark.django_db
class TestPopulateLapsWorker(TestCase):
    """Test lap analysis extraction and persistence."""

    @patch('api.workers.tier3_medium.populate_laps.worker_utils.handle_result')
    @patch('api.models.DriverLapAnalysis.objects.filter')
    @patch('api.services.analysis.get_lap_analysis')
    @pytest.mark.skip(reason='Legacy test incompatible with pure DB fetchers')
    def test_populate_laps_returns_correct_structure(self, mock_get_lap, mock_filter, mock_handle_result):
        """Verify populate_laps returns structured data with required fields."""
        mock_filter.return_value.exists.return_value = True
        mock_get_lap.return_value = {'meta': {'year': 2023, 'round': 4, 'session': 'R', 'can_proceed': True, 'row_count': 2, 'limit_max': 1000}, 'filters_applied': {}, 'data': [{'driver_code': 'VER', 'driver_number': 1, 'laps_completed': 57, 'median_lap_seconds': 95.5, 'consistency_stddev_seconds': 0.42, 'is_personal_best': False, 'compound': 'SOFT', 'pit_status': 'none'}, {'driver_code': 'HAM', 'driver_number': 44, 'laps_completed': 57, 'median_lap_seconds': 96.2, 'consistency_stddev_seconds': 0.55, 'is_personal_best': True, 'compound': 'MEDIUM', 'pit_status': 'none'}]}
        populate_laps(task_key='mock', year=2023, round_number=4, session_type='R')
        mock_handle_result.assert_called_once()
        result = mock_handle_result.call_args[1]['serialized_data']
        assert 'data' in result
        assert len(result['data']) == 2
        assert all(('driver_code' in row for row in result['data']))
        assert all(('laps_completed' in row for row in result['data']))

    @patch('api.workers.tier3_medium.populate_laps.worker_utils.handle_result')
    @patch('api.models.DriverLapAnalysis.objects.filter')
    @patch('api.services.analysis.get_lap_analysis')
    @pytest.mark.skip(reason='Legacy test incompatible with pure DB fetchers')
    def test_populate_laps_structure_includes_pace_data(self, mock_get_lap, mock_filter, mock_handle_result):
        """Verify populate_laps includes pace analysis data in return."""
        mock_filter.return_value.exists.return_value = True
        mock_get_lap.return_value = {'meta': {'year': 2023, 'round': 4, 'session': 'R', 'can_proceed': True, 'row_count': 2, 'limit_max': 1000}, 'filters_applied': {}, 'data': [{'driver_code': 'VER', 'median_lap_seconds': 95.5, 'consistency_stddev_seconds': 0.42, 'is_personal_best': False, 'compound': 'SOFT', 'pit_status': 'none'}]}
        populate_laps(task_key='mock', year=2023, round_number=4, session_type='R')
        mock_handle_result.assert_called_once()
        result = mock_handle_result.call_args[1]['serialized_data']
        assert 'data' in result
        assert len(result['data']) > 0
        assert 'median_lap_seconds' in result['data'][0]
        assert any(('median_lap_seconds' in row for row in result['data']))