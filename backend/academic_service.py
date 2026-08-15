"""Reusable orchestration around the existing deterministic academic engine."""

from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any

from Courses import Courses
from Mark import Mark
from Student import Student
from backend.models import (
    AcademicSnapshot,
    AcademicProgress,
    AcademicYear,
    AcademicYearStatistics,
    CourseRecord,
    DegreeProgress,
    ScholarshipSummary,
    ScholarshipYearSummary,
    StudentSummary,
)


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEMO_RECORD_PATH = PROJECT_ROOT / "demo_data" / "academic_record.json"
DEFAULT_REQUIRED_DEGREE_CREDITS = 120.0
DEFAULT_PROGRAM_DURATION_YEARS = 4


class AcademicScrapeError(RuntimeError):
    """A safe, credential-free error suitable for the API boundary."""


def run_academic_scrape(
    username: str,
    password: str,
    *,
    progress_callback=None,
) -> dict[str, Any]:
    """Call the Chrome scraper directly; credentials never enter argv or disk."""
    try:
        from grades_extractor_chrome import scrape_academic_record

        return scrape_academic_record(username, password, progress_callback)
    except AcademicScrapeError:
        raise
    except Exception as exc:
        raise AcademicScrapeError(
            "We could not retrieve the academic record. Check the login details, "
            "Chrome setup, and UPEI portal availability, then try again."
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


def derive_display_name(full_name: Any) -> str:
    """Return the student's given name from common portal name formats."""
    normalized = " ".join(str(full_name or "").split())
    if not normalized:
        return "Student"
    given_name_source = normalized.split(",", 1)[1] if "," in normalized else normalized
    tokens = re.findall(r"[A-Za-zÀ-ÖØ-öø-ÿ'’-]+", given_name_source)
    return tokens[0] if tokens else "Student"


def _positive_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def calculate_completed_credits(raw_courses: list[dict[str, Any]]) -> float:
    """Count completed, passed courses once without changing GPA calculations."""
    completed_by_course: dict[str, tuple[float, float]] = {}
    for course in raw_courses:
        credits = _positive_number(course.get("credits"))
        if credits is None:
            continue
        grade_text = str(course.get("grade") or "").strip().upper()
        if grade_text == "P":
            comparable_grade = 101.0
        else:
            try:
                comparable_grade = float(grade_text)
            except ValueError:
                continue
            if comparable_grade < 50:
                continue
        code = str(course.get("code") or "UNKNOWN")
        base_code = "-".join(code.split("-")[:2]).upper()
        previous = completed_by_course.get(base_code)
        if previous is None or comparable_grade > previous[0]:
            completed_by_course[base_code] = (comparable_grade, credits)
    return sum(credits for _, credits in completed_by_course.values())


def calculate_academic_progress(
    completed_credits: float,
    required_degree_credits: float = DEFAULT_REQUIRED_DEGREE_CREDITS,
    *,
    program_duration_years: int = DEFAULT_PROGRAM_DURATION_YEARS,
) -> AcademicProgress:
    """Derive standing from credits using one deterministic four-year rule."""
    required = _positive_number(required_degree_credits) or DEFAULT_REQUIRED_DEGREE_CREDITS
    duration = program_duration_years if program_duration_years > 0 else 4
    completed = max(0.0, float(completed_credits))
    credits_per_year = required / duration
    equivalents = completed / credits_per_year
    if completed >= required:
        year = duration
    else:
        year = min(duration, math.floor(equivalents) + 1)
    return AcademicProgress(
        completed_credits=completed,
        required_degree_credits=required,
        credits_per_year=credits_per_year,
        completed_year_equivalents=round(equivalents, 4),
        year_of_study=year,
    )


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


def classify_performance_band(grade: Any, *, credits: float = 1) -> str:
    """Classify presentation-only performance without changing academic rules."""
    if (
        isinstance(grade, bool)
        or not isinstance(grade, (int, float))
        or not 0 <= float(grade) <= 100
        or credits <= 0
    ):
        return "neutral"
    numeric_grade = float(grade)
    if numeric_grade >= 90:
        return "excellent"
    if numeric_grade >= 80:
        return "strong"
    if numeric_grade >= 70:
        return "good"
    if numeric_grade >= 60:
        return "needs_improvement"
    return "low"


def calculate_year_statistics(courses: list[CourseRecord]) -> AcademicYearStatistics:
    """Count mutually exclusive numeric grade bands for visible course records."""
    grade_bands = {
        "90_100": 0,
        "80_89": 0,
        "70_79": 0,
        "60_69": 0,
        "below_60": 0,
    }
    band_keys = {
        "excellent": "90_100",
        "strong": "80_89",
        "good": "70_79",
        "needs_improvement": "60_69",
        "low": "below_60",
    }
    for course in courses:
        key = band_keys.get(course.performance_band)
        if key:
            grade_bands[key] += 1
    graded_courses = sum(grade_bands.values())
    return AcademicYearStatistics(
        total_courses=len(courses),
        graded_courses=graded_courses,
        non_graded_courses=len(courses) - graded_courses,
        grade_bands=grade_bands,
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
    scraped_completed_credits = _positive_number(profile.get("completed_credits"))
    completed_credits = (
        scraped_completed_credits
        if scraped_completed_credits is not None
        else calculate_completed_credits(raw_courses)
    )
    required_degree_credits = (
        _positive_number(profile.get("required_degree_credits"))
        or _positive_number(profile.get("degree_required_credits"))
        or DEFAULT_REQUIRED_DEGREE_CREDITS
    )
    academic_progress = calculate_academic_progress(
        completed_credits, required_degree_credits
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
                    performance_band=classify_performance_band(
                        grade, credits=float(course.get("credits") or 0)
                    ),
                )
            )
        academic_years.append(
            AcademicYear(
                year=year,
                weighted_average=weighted_average,
                performance_band=classify_performance_band(weighted_average),
                statistics=calculate_year_statistics(course_records),
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
    full_name = str(profile.get("name") or "Student")
    return AcademicSnapshot(
        source=snapshot_source,
        student=StudentSummary(
            name=full_name,
            full_name=full_name,
            display_name=derive_display_name(full_name),
            student_id_masked=_mask_student_id(profile.get("student_id")),
            faculty=str(profile.get("faculty") or "").strip() or None,
            majors=majors,
            minors=minors,
            year_of_study=academic_progress.year_of_study,
            cumulative_gpa=cumulative_gpa,
            total_credit_hours=total_credit_hours,
            completed_credits=completed_credits,
            required_degree_credits=required_degree_credits,
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
        academic_progress=academic_progress,
        degree_progress=DegreeProgress(
            status="partial",
            credits_required=required_degree_credits,
            credits_completed=completed_credits,
            message="Credit progress is available; detailed requirement groups are not yet imported.",
        ),
    )


def calculate_academic_summary(scraped_record: dict[str, Any]) -> AcademicSnapshot:
    """Compatibility-friendly name for callers that only need calculations."""
    return build_academic_snapshot(scraped_record)
