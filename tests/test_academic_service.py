from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from backend.academic_service import (
    build_academic_snapshot,
    calculate_academic_progress,
    classify_performance_band,
    derive_display_name,
    load_demo_record,
    run_academic_scrape,
)
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
    def test_portal_name_formats_produce_clean_display_names(self):
        cases = {
            "Elsabah, Mohamed B.": "Mohamed",
            "Chen, Maya": "Maya",
            "Maya Chen": "Maya",
            "Mohamed": "Mohamed",
            "  Elsabah,   Mohamed B.  ": "Mohamed",
        }
        for full_name, expected in cases.items():
            with self.subTest(full_name=full_name):
                self.assertEqual(derive_display_name(full_name), expected)

    def test_year_of_study_boundaries_use_completed_credits(self):
        expected_years = {
            29: 1,
            30: 2,
            59: 2,
            60: 3,
            89: 3,
            90: 4,
            102: 4,
            120: 4,
            150: 4,
        }
        for credits, expected in expected_years.items():
            with self.subTest(credits=credits):
                progress = calculate_academic_progress(credits, 120)
                self.assertEqual(progress.year_of_study, expected)

        progress = calculate_academic_progress(102, 120)
        self.assertEqual(progress.credits_per_year, 30)
        self.assertEqual(progress.completed_year_equivalents, 3.4)

    def test_snapshot_keeps_full_name_and_exposes_calculated_progress(self):
        snapshot = build_academic_snapshot(
            {
                "student": {
                    "name": "Elsabah, Mohamed B.",
                    "student_id": "1234567",
                    "faculty": "SMCS",
                    "majors": ["Computer Science"],
                    "minors": [],
                    "completed_credits": 102,
                    "required_degree_credits": 120,
                    "year_of_study": 1,
                },
                "courses": [],
            }
        )

        self.assertEqual(snapshot.student.full_name, "Elsabah, Mohamed B.")
        self.assertEqual(snapshot.student.display_name, "Mohamed")
        self.assertEqual(snapshot.student.completed_credits, 102)
        self.assertEqual(snapshot.student.year_of_study, 4)
        self.assertEqual(snapshot.academic_progress.year_of_study, 4)
        self.assertEqual(snapshot.academic_progress.completed_year_equivalents, 3.4)

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

    def test_web_connect_contract_has_no_browser_choice(self):
        model_fields = getattr(ConnectRequest, "model_fields", None)
        if model_fields is None:
            model_fields = ConnectRequest.__fields__

        self.assertNotIn("browser", model_fields)

    def test_web_academic_scrape_always_invokes_chrome(self):
        scraper = Mock(return_value={"student": {}, "courses": []})
        chrome_module = SimpleNamespace(scrape_academic_record=scraper)

        with patch.dict("sys.modules", {"grades_extractor_chrome": chrome_module}):
            result = run_academic_scrape("student", "secret")

        self.assertEqual(result, {"student": {}, "courses": []})
        scraper.assert_called_once_with("student", "secret", None)

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

    def test_year_statistics_use_mutually_exclusive_numeric_bands(self):
        grades = [95, 93, 88, 84, 77, 71, 66, 58, "P", "DSC"]
        scraped = {
            "student": {
                "name": "Statistics Student",
                "student_id": "1234567",
                "majors": ["Computer Science"],
                "minors": [],
            },
            "courses": [
                {
                    "academic_year": "2025-2026",
                    "code": f"STAT-{index:04d}-01",
                    "name": f"Statistics Course {index}",
                    "grade": str(grade),
                    "credits": 3,
                }
                for index, grade in enumerate(grades, start=1)
            ],
        }

        statistics = build_academic_snapshot(scraped).academic_years[0].statistics

        self.assertEqual(statistics.total_courses, 10)
        self.assertEqual(statistics.graded_courses, 8)
        self.assertEqual(statistics.non_graded_courses, 2)
        self.assertEqual(
            statistics.grade_bands,
            {
                "90_100": 2,
                "80_89": 2,
                "70_79": 2,
                "60_69": 1,
                "below_60": 1,
            },
        )

    def test_performance_band_boundaries_and_special_grades(self):
        cases = {
            90: "excellent",
            89: "strong",
            80: "strong",
            79: "good",
            70: "good",
            69: "needs_improvement",
            60: "needs_improvement",
            59: "low",
            "P": "neutral",
            "DSC": "neutral",
            "N/A": "neutral",
            "E": "neutral",
        }
        for grade, expected in cases.items():
            with self.subTest(grade=grade):
                self.assertEqual(classify_performance_band(grade), expected)

        self.assertEqual(classify_performance_band(95, credits=0), "neutral")


if __name__ == "__main__":
    unittest.main()
