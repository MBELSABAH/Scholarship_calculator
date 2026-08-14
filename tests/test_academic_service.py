from __future__ import annotations

import unittest

from backend.academic_service import build_academic_snapshot, load_demo_record
from backend.models import ConnectRequest


def dump_model(model):
    return model.model_dump() if hasattr(model, "model_dump") else model.dict()


def scholarship_fixture(year_grades, declared_years):
    courses = []
    for year, grade in year_grades.items():
        for index in range(6):
            courses.append(
                {
                    "academic_year": year,
                    "code": f"TEST-{year[:4]}{index}-01",
                    "name": f"Test Course {index + 1}",
                    "grade": str(grade),
                    "credits": 3,
                }
            )
    return {
        "student": {
            "name": "Scholarship Student",
            "student_id": "1234567",
            "majors": ["Computer Science"],
            "minors": [],
        },
        "academic_years": declared_years,
        "courses": courses,
    }


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
        self.assertEqual(snapshot.scholarship_summary.latest_acquired_year, "2025-2026")
        self.assertEqual(snapshot.scholarship_summary.latest_acquired_amount, 2000)

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

    def test_latest_acquired_ignores_newer_empty_year(self):
        snapshot = build_academic_snapshot(
            scholarship_fixture(
                {"2024-2025": 87, "2025-2026": 92},
                ["2024-2025", "2025-2026", "2026-2027"],
            )
        )

        self.assertEqual(snapshot.scholarship_summary.latest_acquired_year, "2025-2026")
        self.assertEqual(snapshot.scholarship_summary.latest_acquired_amount, 2000)
        future = snapshot.academic_years[-1]
        self.assertEqual(future.calculation_status, "not_calculated")
        self.assertIsNone(future.scholarship_amount)

    def test_calculated_zero_is_preserved_but_not_latest_acquired(self):
        snapshot = build_academic_snapshot(
            scholarship_fixture(
                {"2024-2025": 82, "2025-2026": 70},
                ["2024-2025", "2025-2026", "2026-2027"],
            )
        )

        self.assertEqual(snapshot.scholarship_summary.latest_acquired_year, "2024-2025")
        self.assertEqual(snapshot.scholarship_summary.latest_acquired_amount, 500)
        calculated_zero = snapshot.academic_years[1]
        self.assertEqual(calculated_zero.calculation_status, "calculated")
        self.assertEqual(calculated_zero.scholarship_amount, 0)
        self.assertEqual(snapshot.academic_years[2].calculation_status, "not_calculated")
        self.assertIsNone(snapshot.academic_years[2].scholarship_amount)

    def test_no_acquired_scholarship_uses_null_summary_fields(self):
        snapshot = build_academic_snapshot(
            scholarship_fixture(
                {"2025-2026": 70}, ["2025-2026", "2026-2027"]
            )
        )

        self.assertIsNone(snapshot.scholarship_summary.latest_acquired_year)
        self.assertIsNone(snapshot.scholarship_summary.latest_acquired_amount)
        self.assertIsNone(snapshot.scholarship_summary.latest_acquired_weighted_average)


if __name__ == "__main__":
    unittest.main()
