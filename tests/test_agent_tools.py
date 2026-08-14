from __future__ import annotations

import unittest

from backend.academic_service import build_academic_snapshot, load_demo_record
from backend.agent_tools import (
    ToolExecutionError,
    execute_tool,
    get_academic_record,
    get_scholarship_summary,
    get_student_summary,
    project_gpa,
)


class AcademicAgentToolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.snapshot = build_academic_snapshot(load_demo_record(), source="demo")

    def test_get_student_summary_returns_sanitized_snapshot_data(self):
        result = get_student_summary(self.snapshot)

        self.assertEqual(result["name"], "Maya Chen")
        self.assertEqual(result["majors"], ["Computer Science", "Mathematics"])
        self.assertEqual(result["minors"], ["Business"])
        self.assertEqual(result["cumulative_gpa"], 4.094)
        self.assertEqual(result["total_credit_hours"], 54)
        self.assertNotIn("student_id_masked", result)

    def test_get_scholarship_summary_preserves_deterministic_values(self):
        result = get_scholarship_summary(self.snapshot)

        self.assertEqual(result["latest_acquired_year"], "2025-2026")
        self.assertEqual(result["latest_acquired_weighted_average"], 92.83)
        self.assertEqual(result["latest_acquired_amount"], 2000)
        self.assertEqual(
            [year["scholarship_amount"] for year in result["academic_years"]],
            [500, 2000, 2000],
        )
        self.assertTrue(
            all(year["calculation_status"] == "calculated" for year in result["academic_years"])
        )

    def test_get_academic_record_returns_structured_filtered_courses(self):
        result = get_academic_record(
            self.snapshot, {"academic_year": "2025-2026", "limit": 2}
        )

        self.assertEqual(len(result["academic_years"]), 1)
        self.assertEqual(result["academic_years"][0]["year"], "2025-2026")
        self.assertEqual(len(result["academic_years"][0]["courses"]), 2)
        course = result["academic_years"][0]["courses"][0]
        self.assertEqual(
            set(course),
            {
                "code",
                "base_code",
                "name",
                "grade",
                "gpa",
                "letter",
                "credits",
                "performance_band",
            },
        )
        self.assertEqual(course["performance_band"], "excellent")

    def test_project_gpa_uses_mark_mapping_and_python_math(self):
        result = project_gpa(
            self.snapshot,
            {"future_courses": [{"grade": 90, "credits": 3} for _ in range(4)]},
        )

        self.assertEqual(result["current_gpa"], 4.094)
        self.assertEqual(result["current_credits"], 54)
        self.assertEqual(result["added_credits"], 12)
        self.assertEqual(result["projected_gpa"], 4.077)

    def test_unknown_tool_is_rejected_safely(self):
        with self.assertRaisesRegex(ToolExecutionError, "Unknown academic tool"):
            execute_tool("run_python", "{}", self.snapshot)

    def test_tool_arguments_are_bounded_and_validated(self):
        with self.assertRaisesRegex(ToolExecutionError, "between 1 and 100"):
            get_academic_record(self.snapshot, {"limit": 1000})
        with self.assertRaisesRegex(ToolExecutionError, "whole number"):
            project_gpa(
                self.snapshot,
                {"future_courses": [{"grade": 90.5, "credits": 3}]},
            )


if __name__ == "__main__":
    unittest.main()
