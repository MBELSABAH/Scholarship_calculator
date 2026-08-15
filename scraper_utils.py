"""Shared, credential-free helpers for the browser scrapers.

The functions in this module only transform already-loaded portal text.  Login
credentials are deliberately never accepted here and legacy text files are
written only when the command-line wrappers explicitly request them.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Callable


ProgressCallback = Callable[[str], None]


def notify(callback: ProgressCallback | None, stage: str) -> None:
    if callback is not None:
        callback(stage)


def infer_academic_year(start_date: str) -> int:
    """Return the starting year for UPEI's September-to-August academic year."""
    year, month = map(int, start_date.split("-")[:2])
    return year - 1 if month < 9 else year


def parse_progress_text(text: str) -> dict[str, Any]:
    """Extract the stable at-a-glance values from visible MyProgress text."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    result: dict[str, Any] = {
        "portal_cumulative_gpa": None,
        "faculty": None,
        "majors": [],
        "minors": [],
        "year_of_study": None,
        "completed_credits": None,
        "required_degree_credits": None,
    }

    gpa_match = re.search(r"Cumulative GPA:\s*([0-9.]+)", text, re.IGNORECASE)
    if gpa_match:
        result["portal_cumulative_gpa"] = float(gpa_match.group(1))

    def values_after(label: str) -> list[str]:
        values: list[str] = []
        collecting = False
        for line in lines:
            label_match = re.match(rf"^{re.escape(label)}\s*:\s*(.*)$", line, re.IGNORECASE)
            if label_match:
                collecting = True
                inline_value = label_match.group(1).strip()
                if inline_value and inline_value.lower() != "none":
                    values.append(inline_value)
                continue
            if collecting and re.match(r"^[A-Za-z][A-Za-z ]*:\s*", line):
                break
            if collecting:
                values.append(line)
        return values

    result["majors"] = values_after("Majors")
    result["minors"] = values_after("Minors")
    faculty_match = re.search(r"^(?:Faculty|School):\s*(.+)$", text, re.IGNORECASE | re.MULTILINE)
    if faculty_match:
        result["faculty"] = faculty_match.group(1).strip()
    year_match = re.search(
        r"^(?:Year of Study|Academic Level|Class Level):\s*(?:Year\s*)?([1-6])\b",
        text,
        re.IGNORECASE | re.MULTILINE,
    )
    if year_match:
        result["year_of_study"] = int(year_match.group(1))

    combined_credit_match = re.search(
        r"(?:Credits?|Credit Hours?)\s*(?:Completed|Earned)?\s*:?\s*"
        r"([0-9]+(?:\.[0-9]+)?)\s*(?:of|/)\s*([0-9]+(?:\.[0-9]+)?)",
        text,
        re.IGNORECASE,
    ) or re.search(
        r"([0-9]+(?:\.[0-9]+)?)\s*(?:of|/)\s*([0-9]+(?:\.[0-9]+)?)"
        r"\s*(?:Credits?|Credit Hours?)",
        text,
        re.IGNORECASE,
    )
    if combined_credit_match:
        result["completed_credits"] = float(combined_credit_match.group(1))
        result["required_degree_credits"] = float(combined_credit_match.group(2))

    completed_patterns = (
        r"(?:Completed|Earned)\s+Credits?\s*:\s*([0-9]+(?:\.[0-9]+)?)",
        r"Credits?\s+(?:Completed|Earned)\s*:\s*([0-9]+(?:\.[0-9]+)?)",
    )
    required_patterns = (
        r"(?:Required|Total)\s+(?:Degree\s+)?Credits?\s*:\s*([0-9]+(?:\.[0-9]+)?)",
        r"Credits?\s+Required\s*:\s*([0-9]+(?:\.[0-9]+)?)",
    )
    for pattern in completed_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match and result["completed_credits"] is None:
            result["completed_credits"] = float(match.group(1))
            break
    for pattern in required_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match and result["required_degree_credits"] is None:
            result["required_degree_credits"] = float(match.group(1))
            break
    return result


def parse_credit(value: str) -> int | float:
    match = re.search(r"-?[0-9]+(?:\.[0-9]+)?", value)
    if not match:
        return 0
    number = float(match.group(0))
    return int(number) if number.is_integer() else number


def make_course_record(
    *, section: str, name: str, credit_text: str, grade: str, start_date: str
) -> dict[str, Any]:
    start_year = infer_academic_year(start_date)
    return {
        "academic_year": f"{start_year}-{start_year + 1}",
        "code": section.split()[0],
        "name": name,
        "grade": grade or "N/A",
        "credits": parse_credit(credit_text),
        "raw_section": section,
    }


def write_legacy_outputs(
    scraped: dict[str, Any],
    *,
    info_path: str | Path = "student_information.txt",
    grades_path: str | Path = "printer_friendly_grades.txt",
) -> None:
    """Write the historical CLI artifacts without involving credentials."""
    profile = scraped["student"]
    info_lines = [
        f"Name: {profile.get('name', 'Unknown')}",
        f"Student ID: {profile.get('student_id', '')}",
        f"Cumulative GPA: {profile.get('portal_cumulative_gpa', 'N/A')}",
        f"Majors: {', '.join(profile.get('majors', []))}",
        f"Minors: {', '.join(profile.get('minors', [])) or 'None'}",
    ]
    Path(info_path).write_text("\n".join(info_lines), encoding="utf-8")

    courses = sorted(
        scraped["courses"],
        key=lambda course: (course["academic_year"], course.get("raw_section", course["code"])),
    )
    grade_lines: list[str] = []
    current_year: str | None = None
    for course in courses:
        if course["academic_year"] != current_year:
            if grade_lines:
                grade_lines.append("")
            current_year = course["academic_year"]
            grade_lines.append(f"--- Academic Year {current_year} ---")
        section = course.get("raw_section", course["code"])
        grade_lines.append(
            f"{section} | {course['name']} | {course['credits']} credits | "
            f"Final Grade: {course['grade']}"
        )
    Path(grades_path).write_text("\n".join(grade_lines) + "\n", encoding="utf-8")
