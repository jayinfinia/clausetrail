import unittest
from datetime import date
from backend.domain.deadlines import ReviewedDeadline, add_calendar_months
from backend.domain.policy import ProcessingApproval, can_view, require_external_processing

class DeadlineTests(unittest.TestCase):
    def test_unreviewed_and_unknown_never_alert(self):
        for due, reviewed in [(date(2026, 12, 1), False), (None, True)]:
            self.assertIsNone(ReviewedDeadline("a", due, reviewed, 1).alert_date(30))
    def test_notice_crosses_year(self):
        self.assertEqual(ReviewedDeadline("a", date(2027, 1, 15), True, 1).alert_date(30), date(2026, 12, 16))
    def test_negative_offset_rejected(self):
        with self.assertRaises(ValueError):
            ReviewedDeadline("a", date(2027, 1, 1), True, 1).alert_date(-1)
    def test_month_end_leap_year(self):
        self.assertEqual(add_calendar_months(date(2024, 1, 31), 1), date(2024, 2, 29))
        self.assertEqual(add_calendar_months(date(2025, 1, 31), 1), date(2025, 2, 28))
    def test_amendment_changes_idempotency_key(self):
        old = ReviewedDeadline("a", date(2027, 1, 1), True, 1)
        new = ReviewedDeadline("a", date(2027, 1, 1), True, 2)
        self.assertEqual(old.alert_key(7), old.alert_key(7))
        self.assertNotEqual(old.alert_key(7), new.alert_key(7))

class PolicyTests(unittest.TestCase):
    def test_access_defaults_closed(self):
        self.assertFalse(can_view({"viewer"}, set()))
        self.assertFalse(can_view({"admin"}, {"legal"}))
        self.assertTrue(can_view({"legal"}, {"legal"}))
    def test_local_mode_blocks_cloud(self):
        with self.assertRaises(PermissionError):
            require_external_processing("local_only", None, date(2026, 10, 26))
    def test_approval_missing_or_expired(self):
        for approval in [None, ProcessingApproval("p", "d", "e", "review-1", date(2026, 1, 1))]:
            with self.assertRaises(PermissionError):
                require_external_processing("approved_cloud", approval, date(2026, 10, 26))
    def test_valid_approval_and_incomplete_evidence(self):
        today = date(2026, 10, 26)
        require_external_processing("approved_cloud", ProcessingApproval("p", "d", "e", "review-1", today), today)
        with self.assertRaises(PermissionError):
            require_external_processing("approved_cloud", ProcessingApproval("p", "d", "e", "", today), today)

if __name__ == "__main__":
    unittest.main()

