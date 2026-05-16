from unittest.mock import patch

from django.test import TestCase

from api.services.utils import is_current_year, is_round_completed


_PAST_DATE = "2026-03-16"      # Bahrain GP 2026 — already completed
_FUTURE_DATE = "2099-12-01"    # Far future — never completed


class IsRoundCompletedTests(TestCase):
    @patch("api.services.persistence.get_persisted_race_by_round")
    def test_returns_true_for_completed_round_using_date_field(self, mock_get):
        mock_get.return_value = {"round": 1, "date": _PAST_DATE}
        self.assertTrue(is_round_completed(2026, 1))

    @patch("api.services.persistence.get_persisted_race_by_round")
    def test_returns_false_for_upcoming_round_using_date_field(self, mock_get):
        mock_get.return_value = {"round": 10, "date": _FUTURE_DATE}
        self.assertFalse(is_round_completed(2026, 10))

    @patch("api.services.persistence.get_persisted_race_by_round")
    def test_falls_back_to_session5_date_utc_when_date_missing(self, mock_get):
        mock_get.return_value = {
            "round": 1,
            "session5_date_utc": "2026-03-16T15:00:00Z",
        }
        self.assertTrue(is_round_completed(2026, 1))

    @patch("api.services.persistence.get_persisted_race_by_round")
    def test_returns_false_when_session5_is_in_future(self, mock_get):
        mock_get.return_value = {
            "round": 10,
            "session5_date_utc": "2099-12-01T15:00:00Z",
        }
        self.assertFalse(is_round_completed(2026, 10))

    @patch("api.services.persistence.get_persisted_race_by_round")
    def test_returns_false_when_schedule_not_found(self, mock_get):
        mock_get.return_value = None
        self.assertFalse(is_round_completed(2026, 99))

    @patch("api.services.persistence.get_persisted_race_by_round")
    def test_returns_false_when_date_fields_absent(self, mock_get):
        mock_get.return_value = {"round": 1, "name": "Bahrain Grand Prix"}
        self.assertFalse(is_round_completed(2026, 1))

    @patch("api.services.persistence.get_persisted_race_by_round")
    def test_returns_false_on_malformed_date_string(self, mock_get):
        mock_get.return_value = {"round": 1, "date": "not-a-date"}
        self.assertFalse(is_round_completed(2026, 1))

    @patch("api.services.persistence.get_persisted_race_by_round")
    def test_returns_false_when_persistence_raises(self, mock_get):
        mock_get.side_effect = Exception("DB connection failed")
        self.assertFalse(is_round_completed(2026, 1))


class IsCurrentYearTests(TestCase):
    def test_current_year_returns_true(self):
        import datetime
        current = datetime.datetime.now().year
        self.assertTrue(is_current_year(current))

    def test_past_year_returns_false(self):
        import datetime
        past = datetime.datetime.now().year - 1
        self.assertFalse(is_current_year(past))

    def test_future_year_returns_true(self):
        import datetime
        future = datetime.datetime.now().year + 1
        self.assertTrue(is_current_year(future))
