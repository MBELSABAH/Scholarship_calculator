from __future__ import annotations

import unittest

from backend.academic_service import build_academic_snapshot, load_demo_record
from backend.models import ConnectRequest


def dump_model(model):
    return model.model_dump() if hasattr(model, "model_dump") else model.dict()


class AcademicServiceTests(unittest.TestCase):
    def test_demo_snapshot_uses_existing_calculators(self):
        snapshot = build_academic_snapshot(load_demo_record(), source="demo")

        self.assertEqual(snapshot.source, "demo")
        self.assertEqual(snapshot.student.student_id_masked, "••••007")
        self.assertAlmostEqual(snapshot.student.cumulative_gpa, 4.094, places=3)
        self.assertEqual(snapshot.student.total_credit_hours, 54)
        self.assertEqual(
            [year.scholarship_amount for year in snapshot.academic_years],
            [500, 2000, 2000],
        )
        self.assertEqual(snapshot.scholarship_summary.latest_academic_year, "2025-2026")

        serialized = dump_model(snapshot)
        self.assertNotIn("student_id", serialized["student"])
        self.assertNotIn("portal_cumulative_gpa", serialized["student"])

    def test_repeated_course_keeps_highest_attempt_for_gpa(self):
        scraped = {
            "student": {
                "name": "Sample Student",
                "student_id": "1234567",
                "majors": ["Computer Science"],
                "minors": [],
            },
            "courses": [
                {
                    "academic_year": "2023-2024",
                    "code": "CS-1910-01",
                    "name": "Computer Science I",
                    "grade": "60",
                    "credits": 3,
                },
                {
                    "academic_year": "2024-2025",
                    "code": "CS-1910-02",
                    "name": "Computer Science I",
                    "grade": "95",
                    "credits": 3,
                },
            ],
        }

        snapshot = build_academic_snapshot(scraped)

        self.assertEqual(snapshot.student.cumulative_gpa, 4.3)
        self.assertEqual(snapshot.student.total_credit_hours, 3)

    def test_password_is_secret_in_request_representation(self):
        request = ConnectRequest(username="student", password="do-not-log-this")

        self.assertNotIn("do-not-log-this", repr(request))
        self.assertEqual(request.password.get_secret_value(), "do-not-log-this")


if __name__ == "__main__":
    unittest.main()
