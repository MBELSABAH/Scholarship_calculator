"""API and AcademicSnapshot data contracts."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, SecretStr


class ConnectRequest(BaseModel):
    username: str = ""
    password: SecretStr = Field(default_factory=lambda: SecretStr(""))
    demo: bool = False


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    conversation_id: str | None = Field(default=None, max_length=100)
    current_view: Literal["dashboard", "scholarships", "scholarship_detail", "application"] = "dashboard"
    current_scholarship_id: str | None = Field(default=None, max_length=100)
    current_application_id: str | None = Field(default=None, max_length=100)


class ChatSource(BaseModel):
    title: str
    url: str


class ChatResponse(BaseModel):
    message: str
    conversation_id: str
    suggested_replies: list[str]
    tools_used: list[str]
    sources: list[ChatSource] = Field(default_factory=list)
    ui_updates: list[str] = Field(default_factory=list)


class ScholarshipSearchRequest(BaseModel):
    faculty: str | None = Field(default=None, max_length=120)
    major: str | None = Field(default=None, max_length=120)
    year_of_study: int | None = Field(default=None, ge=1, le=6)
    keyword: str | None = Field(default=None, max_length=120)
    refresh: bool = False


class BackgroundAnswerRequest(BaseModel):
    field: str | None = Field(default=None, max_length=80)
    value: str | bool | list[str]
    confirmed: bool


class ApplicationAnswerRequest(BaseModel):
    field_id: str = Field(min_length=1, max_length=120)
    value: str | bool | float
    user_approved: bool = False


class ApproveSubmissionRequest(BaseModel):
    explicit_action: Literal["APPROVE_AND_SUBMIT"]


class CourseRecord(BaseModel):
    code: str
    base_code: str
    name: str
    grade: int | str
    gpa: float | str
    letter: str
    credits: float
    performance_band: Literal[
        "excellent", "strong", "good", "needs_improvement", "low", "neutral"
    ] = "neutral"


class AcademicYearStatistics(BaseModel):
    total_courses: int
    graded_courses: int
    non_graded_courses: int
    grade_bands: dict[str, int]


class AcademicYear(BaseModel):
    year: str
    weighted_average: float | None
    performance_band: Literal[
        "excellent", "strong", "good", "needs_improvement", "low", "neutral"
    ] = "neutral"
    statistics: AcademicYearStatistics
    scholarship_amount: int | None
    calculation_status: Literal["calculated", "not_calculated"]
    scholarship_status: Literal[
        "eligible", "not_eligible", "insufficient_credits", "no_courses"
    ]
    scholarship_message: str
    courses: list[CourseRecord]


class StudentSummary(BaseModel):
    name: str
    full_name: str
    display_name: str
    student_id_masked: str
    university: str = "UPEI"
    faculty: str | None = None
    majors: list[str]
    minors: list[str]
    year_of_study: int | None = None
    cumulative_gpa: float | None
    total_credit_hours: float
    completed_credits: float
    required_degree_credits: float


class AcademicProgress(BaseModel):
    completed_credits: float
    required_degree_credits: float
    credits_per_year: float
    completed_year_equivalents: float
    year_of_study: int


class ScholarshipYearSummary(BaseModel):
    year: str
    weighted_average: float | None
    amount: int | None
    calculation_status: Literal["calculated", "not_calculated"]
    status: str


class ScholarshipSummary(BaseModel):
    latest_acquired_year: str | None
    latest_acquired_amount: int | None
    latest_acquired_weighted_average: float | None
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
    academic_progress: AcademicProgress
    degree_progress: DegreeProgress
