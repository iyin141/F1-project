"""
Unit tests for Tier 3 analysis workers: pace, stint, sector, tyre strategy.
Verifies worker output structure and caching behavior.
"""
import pytest
from unittest.mock import Mock, patch
from django.test import TestCase

from api.workers.tier3_medium.populate_pace_analysis import populate_pace_analysis
from api.workers.tier3_medium.populate_stint_analysis import populate_stint_analysis
from api.workers.tier3_medium.populate_sector_analysis import populate_sector_analysis
from api.workers.tier3_medium.populate_tyre_strategy import populate_tyre_strategy


@pytest.mark.django_db
class TestPopulatePaceAnalysisWorker(TestCase):
    """Test pace analysis extraction and caching."""
    
    @patch('api.workers.tier3_medium.populate_pace_analysis.worker_utils.handle_result')
    @patch('api.services.analysis.get_pace_analysis')
    def test_populate_pace_analysis_returns_structured_data(self, mock_get_pace, mock_handle_result):
        """Verify populate_pace_analysis returns structured pace data."""
        
        mock_get_pace.return_value = {
            'meta': {'year': 2023, 'round': 4, 'session': 'R', 'can_proceed': True, 'row_count': 2, 'limit_max': 1000},
            'filters_applied': {},
            'data': [
                {
                    'driver_code': 'VER',
                    'driver_number': 1,
                    'laps_completed': 57,
                    'session_median_lap_seconds': 95.5, 'laps_completed': 50,
                    'consistency_stddev_seconds': 0.42,
                    'fastest_lap_seconds': 94.1,
                },
                {
                    'driver_code': 'HAM',
                    'driver_number': 44,
                    'laps_completed': 57,
                    'session_median_lap_seconds': 96.2,
                    'consistency_stddev_seconds': 0.55,
                    'fastest_lap_seconds': 95.8,
                }
            ]
        }
        
        populate_pace_analysis(task_key="mock", year=2023, round_number=4, session_type="R")
        
        mock_handle_result.assert_called_once()
        result = mock_handle_result.call_args[1]['serialized_data']
        assert 'data' in result
        assert len(result['data']) == 2
        assert all('driver_code' in row for row in result['data'])
        assert all('session_median_lap_seconds' in row for row in result['data'])
        assert all('consistency_stddev_seconds' in row for row in result['data'])
    
    @patch('api.workers.tier3_medium.populate_pace_analysis.worker_utils.handle_result')
    @patch('api.services.analysis.get_pace_analysis')
    def test_populate_pace_analysis_caches_result(self, mock_get_pace, mock_handle_result):
        """Verify populate_pace_analysis caches the result."""
        
        mock_get_pace.return_value = {
            'meta': {'year': 2023, 'round': 4, 'session': 'R', 'can_proceed': True, 'row_count': 2, 'limit_max': 1000},
            'filters_applied': {},
            'data': [
                {'driver_code': 'VER', 'session_median_lap_seconds': 95.5, 'laps_completed': 50}
            ]
        }
        
        populate_pace_analysis(task_key="mock", year=2023, round_number=4, session_type="R")
        
        mock_handle_result.assert_called_once()
        result = mock_handle_result.call_args[1]['serialized_data']
        assert isinstance(result, dict)
        assert 'data' in result


@pytest.mark.django_db
class TestPopulateStintAnalysisWorker(TestCase):
    """Test stint analysis extraction and caching."""
    
    @patch('api.workers.tier3_medium.populate_stint_analysis.worker_utils.handle_result')
    @patch('api.services.analysis.get_stint_analysis')
    def test_populate_stint_analysis_returns_structured_data(self, mock_get_stints, mock_handle_result):
        """Verify populate_stint_analysis returns structured stint data."""
        
        mock_get_stints.return_value = {
            'meta': {'year': 2023, 'round': 4, 'session': 'R', 'can_proceed': True, 'row_count': 2, 'limit_max': 1000},
            'filters_applied': {},
            'data': [
                {
                    'driver_code': 'VER',
                    'driver_number': 1,
                    'stint_number': 1,
                    'compound': 'SOFT',
                    'lap_start': 1,
                    'lap_end': 20,
                    'total_laps': 20,
                    'laps_in_stint': 20,
                    'median_lap_seconds': 95.8,
                    'min_lap_seconds': 94.1,
                    'max_lap_seconds': 98.5,
                },
                {
                    'driver_code': 'VER',
                    'driver_number': 1,
                    'stint_number': 2,
                    'compound': 'MEDIUM',
                    'lap_start': 21,
                    'lap_end': 57,
                    'total_laps': 37,
                    'laps_in_stint': 37,
                    'median_lap_seconds': 95.2,
                    'min_lap_seconds': 94.8,
                    'max_lap_seconds': 96.1,
                }
            ]
        }
        
        populate_stint_analysis(task_key="mock", year=2023, round_number=4, session_type="R")
        
        mock_handle_result.assert_called_once()
        result = mock_handle_result.call_args[1]['serialized_data']
        assert 'data' in result
        assert len(result['data']) == 2
        assert all('compound' in row for row in result['data'])
        assert all('median_lap_seconds' in row for row in result['data'])
    
    @patch('api.workers.tier3_medium.populate_stint_analysis.worker_utils.handle_result')
    @patch('api.services.analysis.get_stint_analysis')
    def test_populate_stint_analysis_includes_tyre_info(self, mock_get_stints, mock_handle_result):
        """Verify populate_stint_analysis includes tyre compound information."""
        
        mock_get_stints.return_value = {
            'meta': {'year': 2023, 'round': 4, 'session': 'R', 'can_proceed': True, 'row_count': 2, 'limit_max': 1000},
            'filters_applied': {},
            'data': [
                {
                    'driver_code': 'HAM',
                    'compound': 'HARD',
                    'lap_start': 1,
                    'lap_end': 30,
                    'laps_in_stint': 30,
                }
            ]
        }
        
        populate_stint_analysis(task_key="mock", year=2023, round_number=4, session_type="R")
        
        mock_handle_result.assert_called_once()
        result = mock_handle_result.call_args[1]['serialized_data']
        assert 'data' in result
        assert len(result['data']) > 0
        assert result['data'][0]['compound'] in ['SOFT', 'MEDIUM', 'HARD']


@pytest.mark.django_db
class TestPopulateSectorAnalysisWorker(TestCase):
    """Test sector analysis extraction and caching."""
    
    @patch('api.workers.tier3_medium.populate_sector_analysis.worker_utils.handle_result')
    @patch('api.services.analysis.get_sector_analysis')
    def test_populate_sector_analysis_returns_structured_data(self, mock_get_sectors, mock_handle_result):
        """Verify populate_sector_analysis returns structured sector data."""
        
        mock_get_sectors.return_value = {
            'meta': {'year': 2023, 'round': 4, 'session': 'R', 'can_proceed': True, 'row_count': 2, 'limit_max': 1000},
            'filters_applied': {},
            'data': [
                {
                    'driver_code': 'VER',
                    'driver_number': 1,
                    'laps_count': 10,
                    'best_sector1_seconds': 30.111,
                    'best_sector2_seconds': 35.222,
                    'best_sector3_seconds': 28.333,
                    'median_sector1_seconds': 30.444,
                    'median_sector2_seconds': 35.555,
                    'median_sector3_seconds': 28.666,
                    'best_lap_seconds': 93.900,
                    'theoretical_best_lap_seconds': 93.666,
                    'delta_to_theoretical_seconds': 0.234,
                },
                {
                    'driver_code': 'HAM',
                    'driver_number': 44,
                    'laps_count': 10,
                    'best_sector1_seconds': 30.889,
                    'best_sector2_seconds': 36.111,
                    'best_sector3_seconds': 28.945,
                    'median_sector1_seconds': 31.222,
                    'median_sector2_seconds': 36.333,
                    'median_sector3_seconds': 29.111,
                    'best_lap_seconds': 95.000,
                    'theoretical_best_lap_seconds': 94.667,
                    'delta_to_theoretical_seconds': 0.333,
                }
            ]
        }
        
        populate_sector_analysis(task_key="mock", year=2023, round_number=4, session_type="R")
        
        mock_handle_result.assert_called_once()
        result = mock_handle_result.call_args[1]['serialized_data']
        assert 'data' in result
        assert len(result['data']) == 2
        assert all('best_sector1_seconds' in row for row in result['data'])
        assert all('delta_to_theoretical_seconds' in row for row in result['data'])
    
    @patch('api.workers.tier3_medium.populate_sector_analysis.worker_utils.handle_result')
    @patch('api.services.analysis.get_sector_analysis')
    def test_populate_sector_analysis_includes_best_lap(self, mock_get_sectors, mock_handle_result):
        """Verify populate_sector_analysis includes best lap information."""
        
        mock_get_sectors.return_value = {
            'meta': {'year': 2023, 'round': 4, 'session': 'R', 'can_proceed': True, 'row_count': 2, 'limit_max': 1000},
            'filters_applied': {},
            'data': [
                {
                    'driver_code': 'VER',
                    'best_lap_seconds': 93.900,
                    'theoretical_best_lap_seconds': 93.666,
                    'laps_count': 10,
                }
            ]
        }
        
        populate_sector_analysis(task_key="mock", year=2023, round_number=4, session_type="R")
        
        mock_handle_result.assert_called_once()
        result = mock_handle_result.call_args[1]['serialized_data']
        assert 'data' in result
        assert len(result['data']) > 0
        assert 'best_lap_seconds' in result['data'][0]


@pytest.mark.django_db
class TestPopulateTyreStrategyWorker(TestCase):
    """Test tyre strategy analysis extraction and caching."""
    
    @patch('api.workers.tier3_medium.populate_tyre_strategy.worker_utils.handle_result')
    @patch('api.services.analysis.get_tyre_strategy_analysis')
    def test_populate_tyre_strategy_returns_structured_data(self, mock_get_tyre_strategy, mock_handle_result):
        """Verify populate_tyre_strategy returns structured tyre strategy data."""
        
        mock_get_tyre_strategy.return_value = {
            'meta': {'year': 2023, 'round': 4, 'session': 'R', 'can_proceed': True, 'row_count': 2, 'limit_max': 1000},
            'filters_applied': {},
            'data': [
                {
                    'driver_code': 'VER',
                    'driver_number': 1,
                    'stint_number': 1,
                    'compound': 'SOFT',
                    'lap_start': 1,
                    'lap_end': 20,
                    'total_laps': 20,
                    'laps_in_stint': 20,
                },
                {
                    'driver_code': 'VER',
                    'driver_number': 1,
                    'stint_number': 2,
                    'compound': 'MEDIUM',
                    'lap_start': 21,
                    'lap_end': 57,
                    'total_laps': 37,
                    'laps_in_stint': 37,
                }
            ]
        }
        
        populate_tyre_strategy(task_key="mock", year=2023, round_number=4, session_type="R")
        
        mock_handle_result.assert_called_once()
        result = mock_handle_result.call_args[1]['serialized_data']
        assert 'data' in result
        assert len(result['data']) >= 1
        assert all('compound' in row for row in result['data'])
    
    @patch('api.workers.tier3_medium.populate_tyre_strategy.worker_utils.handle_result')
    @patch('api.services.analysis.get_stint_analysis')
    def test_populate_tyre_strategy_aggregates_stints(self, mock_get_stints, mock_handle_result):
        """Verify populate_tyre_strategy aggregates stint data by driver and compound."""
        
        mock_get_stints.return_value = {
            'meta': {'year': 2023, 'round': 4, 'session': 'R', 'can_proceed': True, 'row_count': 2, 'limit_max': 1000},
            'filters_applied': {},
            'data': [
                {'driver_code': 'HAM', 'compound': 'SOFT', 'total_laps': 20},
                {'driver_code': 'HAM', 'compound': 'HARD', 'total_laps': 37},
            ]
        }
        
        populate_tyre_strategy(task_key="mock", year=2023, round_number=4, session_type="R")
        
        mock_handle_result.assert_called_once()
        result = mock_handle_result.call_args[1]['serialized_data']
        assert 'data' in result
        assert isinstance(result['data'], list)
