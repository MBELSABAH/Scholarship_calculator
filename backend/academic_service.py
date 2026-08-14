"""Reusable orchestration around the existing deterministic academic engine."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from Courses import Courses
from Mark import Mark
from Student import Student
from backend.models import (
    AcademicSnapshot,
    AcademicYear,
    CourseRecord,
    DegreeProgress,
    ScholarshipSummary,
    ScholarshipYearSummary,
    StudentSummary,
)


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEMO_RECORD_PATH = PROJECT_ROOT / "demo_data" / "academic_record.json"


class AcademicScrapeError(RuntimeError):
    """A safe, credential-free error suitable for the API boundary."""


def run_academic_scrape(
    username: str,
    password: str,
    *,
    browser: str = "chrome",
    progress_callback=None,
) -> dict[str, Any]:
    """Call a browser scraper directly; credentials never enter argv or disk."""
    try:
        if browser == "safari":
            from grades_extractor_safari import scrape_academic_record
        elif browser == "chrome":
            from grades_extractor_chrome import scrape_academic_record
        else:
            raise AcademicScrapeError("Choose Chrome or Safari.")
        return scrape_academic_record(username, password, progress_callback)
    except AcademicScrapeError:
        raise
    except Exception as exc:
        raise AcademicScrapeError(
            "We could not retrieve the academic record. Check the login details, "
            "browser setup, and UPEI portal availability, then try again."
        ) from exc


def load_demo_record() -> dict[str, Any]:
    with DEMO_RECORD_PATH.open("r", encoding="utf-8") as demo_file:
        return json.load(demo_file)


def _mark_from_grade(raw_grade: Any) -> Mark:
    value = str(raw_grade).strip()
    return Mark(int(value)) if value.isdigit() else Mark(value.upper())


def _mask_student_id(student_id: Any) -> str:
    compact = re.sub(r"\s+", "", str(student_id or ""))
    return f"••••{compact[-3:]}" if compact else "Not available"


def _parse_gpa_result(result: str) -> tuple[float | None, float]:
    gpa_match = re.search(r"Cumulative GPA:\s*([0-9.]+)", result)
    credits_match = re.search(r"Total Credit Hours:\s*([0-9.]+)", result)
    return (
        float(gpa_match.group(1)) if gpa_match else None,
        float(credits_match.group(1)) if credits_match else 0.0,
    )


def _parse_scholarship_result(
    result: str,
) -> tuple[float | None, int | None, str, str]:
    average_match = re.search(r"Weighted Average(?: must[^:]*|):\s*([0-9.]+)", result)
    if not average_match:
        average_match = re.search(r"Current:\s*([0-9.]+)", result)
    amount_match = re.search(r"\$(\d+) Scholarship", result)

    if "Not enough courses" in result:
        status = "insufficient_credits"
        calculation_status = "not_calculated"
    elif "No courses taken" in result:
        status = "no_courses"
        calculation_status = "not_calculated"
    elif amount_match:
        status = "eligible"
        calculation_status = "calculated"
    else:
        status = "not_eligible"
        calculation_status = "calculated"

    return (
        float(average_match.group(1)) if average_match else None,
        int(amount_match.group(1))
        if amount_match
        else (0 if calculation_status == "calculated" else None),
        status,
        calculation_status,
    )


def build_academic_snapshot(
    scraped_record: dict[str, Any], *, source: str = "live"
) -> AcademicSnapshot:
    """Build JSON-ready data while delegating all facts to existing classes."""
    profile = scraped_record.get("student", {})
    raw_courses = scraped_record.get("courses", [])
    declared_years = {
        str(year.get("year")) if isinstance(year, dict) else str(year)
        for year in scraped_record.get("academic_years", [])
        if (year.get("year") if isinstance(year, dict) else year)
    }
    years = sorted(
        {str(course["academic_year"]) for course in raw_courses} | declared_years
    )
    courses_by_year = {
        year: [course for course in raw_courses if str(course["academic_year"]) == year]
        for year in years
    }

    majors = [str(major).strip() for major in profile.get("majors", []) if str(major).strip()]
    minors = [str(minor).strip() for minor in profile.get("minors", []) if str(minor).strip()]
    student = Student(
        str(profile.get("name") or "Student"),
        profile.get("student_id") or 0,
        None,
        tuple(majors),
        tuple(minors),
    )
    courses_engine = Courses(student)
    marks_by_course: dict[int, Mark] = {}

    for year_index, year in enumerate(years, start=1):
        for course in courses_by_year[year]:
            mark = _mark_from_grade(course.get("grade", "N/A"))
            marks_by_course[id(course)] = mark
            courses_engine.add_course(
                (
                    str(course.get("code") or "UNKNOWN"),
                    str(course.get("name") or "Untitled course"),
                    mark,
                    float(course.get("credits") or 0),
                ),
                academic_year=year_index,
            )
    student.set_courses(courses_engine)

    cumulative_gpa, total_credit_hours = _parse_gpa_result(
        courses_engine.calculate_cumulative_gpa()
    )
    academic_years: list[AcademicYear] = []
    scholarship_years: list[ScholarshipYearSummary] = []

    for year_index, year in enumerate(years, start=1):
        calculation = courses_engine.calculate_scholarship(year_index)
        weighted_average, amount, status, calculation_status = _parse_scholarship_result(
            calculation
        )
        course_records: list[CourseRecord] = []
        for course in courses_by_year[year]:
            mark = marks_by_course[id(course)]
            grade = mark.percentage
            course_records.append(
                CourseRecord(
                    code=str(course.get("code") or "UNKNOWN"),
                    base_code="-".join(str(course.get("code") or "UNKNOWN").split("-")[:2]),
                    name=str(course.get("name") or "Untitled course"),
                    grade=grade,
                    gpa=mark.gpa,
                    letter=mark.letter,
                    credits=float(course.get("credits") or 0),
                )
            )
        academic_years.append(
            AcademicYear(
                year=year,
                weighted_average=weighted_average,
                scholarship_amount=amount,
                calculation_status=calculation_status,
                scholarship_status=status,
                scholarship_message=calculation.replace(f"Year {year_index} - ", ""),
                courses=course_records,
            )
        )
        scholarship_years.append(
            ScholarshipYearSummary(
                year=year,
                weighted_average=weighted_average,
                amount=amount,
                calculation_status=calculation_status,
                status=status,
            )
        )

    latest_acquired = next(
        (
            year
            for year in reversed(scholarship_years)
            if year.calculation_status == "calculated"
            and year.amount is not None
            and year.amount > 0
        ),
        None,
    )
    snapshot_source = "demo" if source == "demo" else "live"
    return AcademicSnapshot(
        source=snapshot_source,
        student=StudentSummary(
            name=str(profile.get("name") or "Student"),
            student_id_masked=_mask_student_id(profile.get("student_id")),
            faculty=str(profile.get("faculty") or "").strip() or None,
            majors=majors,
            minors=minors,
            year_of_study=(
                int(profile["year_of_study"])
                if str(profile.get("year_of_study") or "").isdigit()
                else None
            ),
            cumulative_gpa=cumulative_gpa,
            total_credit_hours=total_credit_hours,
        ),
        academic_years=academic_years,
        scholarship_summary=ScholarshipSummary(
            latest_acquired_year=latest_acquired.year if latest_acquired else None,
            latest_acquired_amount=latest_acquired.amount if latest_acquired else None,
            latest_acquired_weighted_average=(
                latest_acquired.weighted_average if latest_acquired else None
            ),
            eligible_years=sum(year.status == "eligible" for year in scholarship_years),
            years=scholarship_years,
        ),
        degree_progress=DegreeProgress(
            credits_completed=total_credit_hours,
            message="Detailed MyProgress requirements are reserved for Phase 4.",
        ),
    )


def calculate_academic_summary(scraped_record: dict[str, Any]) -> AcademicSnapshot:
    """Compatibility-friendly name for callers that only need calculations."""
    return build_academic_snapshot(scraped_record)
