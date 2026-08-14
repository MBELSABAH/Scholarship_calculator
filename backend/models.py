"""API and AcademicSnapshot data contracts."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, SecretStr


class ConnectRequest(BaseModel):
    username: str = ""
    password: SecretStr = Field(default_factory=lambda: SecretStr(""))
    browser: Literal["chrome", "safari"] = "chrome"
    demo: bool = False


class CourseRecord(BaseModel):
    code: str
    base_code: str
    name: str
    grade: int | str
    gpa: float | str
    letter: str
    credits: float


class AcademicYear(BaseModel):
    year: str
    weighted_average: float | None
    scholarship_amount: int
    scholarship_status: Literal[
        "eligible", "not_eligible", "insufficient_credits", "no_courses"
    ]
    scholarship_message: str
    courses: list[CourseRecord]


class StudentSummary(BaseModel):
    name: str
    student_id_masked: str
    majors: list[str]
    minors: list[str]
    cumulative_gpa: float | None
    total_credit_hours: float


class ScholarshipYearSummary(BaseModel):
    year: str
    weighted_average: float | None
    amount: int
    status: str


class ScholarshipSummary(BaseModel):
    latest_academic_year: str | None
    latest_scholarship_amount: int
    eligible_years: int
    years: list[ScholarshipYearSummary]


class DegreeProgress(BaseModel):
    status: Literal["not_available", "partial", "available"] = "not_available"
    credits_required: float | None = None
    credits_completed: float
    requirements: list[dict] = Field(default_factory=list)
    message: str


class AcademicSnapshot(BaseModel):
    source: Literal["live", "demo"]
    student: StudentSummary
    academic_years: list[AcademicYear]
    scholarship_summary: ScholarshipSummary
    degree_progress: DegreeProgress

