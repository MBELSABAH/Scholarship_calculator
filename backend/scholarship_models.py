"""Structured contracts for scholarship discovery and application assistance."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class ScholarshipSource(BaseModel):
    title: str
    url: str
    retrieved_at: str | None = None


class DeadlineOccurrence(BaseModel):
    month: int | None = None
    day: int | None = None
    year: int | None = None
    display: str
    precision: Literal["exact", "month_day", "month", "unknown"]
    source: str | None = None
    source_url: str | None = None
    confidence: Literal["high", "medium", "unknown"] = "unknown"
    recurring: bool = False


class DeadlineConflict(BaseModel):
    value: str
    source: str
    source_url: str | None = None


class ScholarshipRecord(BaseModel):
    id: str
    name: str
    amount: float | None = None
    deadline: str | None = None
    deadline_display: str | None = None
    deadline_precision: Literal["exact", "month_day", "month", "unknown"] = "unknown"
    deadline_month: int | None = None
    deadline_day: int | None = None
    deadline_source: str | None = None
    deadline_source_url: str | None = None
    deadline_confidence: Literal["high", "medium", "unknown"] = "unknown"
    deadlines: list[DeadlineOccurrence] = Field(default_factory=list)
    next_deadline: str | None = None
    next_deadline_display: str | None = None
    deadline_conflict: bool = False
    other_deadlines: list[DeadlineConflict] = Field(default_factory=list)
    application_status: Literal["open", "closed", "upcoming", "unknown"] = "unknown"
    description: str
    faculty: list[str] = Field(default_factory=list)
    major: list[str] = Field(default_factory=list)
    year_of_study: list[str] = Field(default_factory=list)
    academic_requirements: str | None = None
    minimum_average: float | None = None
    financial_need_required: bool | None = None
    citizenship_or_residency_requirements: str | None = None
    personal_statement_required: bool | None = None
    reference_required: bool | None = None
    application_required: bool | None = None
    application_url: str | None = None
    submission_method: Literal["portal", "email", "external_form", "unknown"] = "unknown"
    submission_email: str | None = None
    required_documents: list[str] = Field(default_factory=list)
    source_url: str
    source_title: str
    detail_status: Literal["extracted", "source_only"] = "extracted"
    is_demo: bool = False


class ScholarshipSearchResult(BaseModel):
    scholarships: list[ScholarshipRecord]
    source_mode: Literal["live", "cached", "demo_fallback"]
    sources: list[ScholarshipSource]
    warning: str | None = None


class StudentBackgroundProfile(BaseModel):
    country_of_origin: str | None = None
    citizenship_status: str | None = None
    international_student: bool | None = None
    province_or_region: str | None = None
    financial_need: bool | None = None
    gender_identity_criterion: bool | None = None
    indigenous_identity: bool | None = None
    disability_status: bool | None = None
    pei_high_school_graduate: bool | None = None
    co_op_terms_completed: int | None = None
    employment: str | None = None
    community_involvement: list[str] = Field(default_factory=list)
    leadership: list[str] = Field(default_factory=list)
    volunteering: list[str] = Field(default_factory=list)
    clubs: list[str] = Field(default_factory=list)
    career_goals: str | None = None
    personal_story_notes: list[str] = Field(default_factory=list)
    other_awards: list[str] = Field(default_factory=list)


class ScholarshipMatch(BaseModel):
    scholarship_id: str
    scholarship: ScholarshipRecord
    match_level: Literal[
        "excellent", "strong", "potential", "unlikely"
    ]
    confidence: float
    known_matches: list[str] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)
    known_conflicts: list[str] = Field(default_factory=list)


class ApplicationField(BaseModel):
    field_id: str
    label: str
    type: Literal["text", "textarea", "number", "boolean", "select", "file"]
    required: bool = True
    max_length: int | None = None
    options: list[str] = Field(default_factory=list)
    known_answer: Any = None
    sensitive: bool = False
    essay: bool = False
    source: Literal["official_form", "official_criteria", "academic_snapshot", "student"] = (
        "official_criteria"
    )


class DraftAnswer(BaseModel):
    field_id: str
    source_notes: str
    draft_text: str
    character_count: int
    max_length: int | None = None
    user_approved: bool = False


class ScholarshipApplicationState(BaseModel):
    application_id: str
    scholarship_id: str
    scholarship_name: str
    application_url: str | None = None
    submission_method: Literal["portal", "email", "external_form", "unknown"] = "unknown"
    submission_email: str | None = None
    required_documents: list[str] = Field(default_factory=list)
    deadline_display: str = "Not found"
    application_status: Literal["open", "closed", "upcoming", "unknown"] = "unknown"
    inspection_status: Literal["official_form", "criteria_based_preview", "unavailable"]
    next_action: Literal[
        "guided_application",
        "open_official_application",
        "open_official_scholarship",
        "unavailable",
    ]
    destination_url: str | None = None
    status_message: str
    next_question: str | None = None
    fields: list[ApplicationField]
    known_fields: dict[str, Any] = Field(default_factory=dict)
    missing_fields: list[str] = Field(default_factory=list)
    drafted_answers: dict[str, DraftAnswer] = Field(default_factory=dict)
    user_approved_answers: list[str] = Field(default_factory=list)
    validation_errors: list[str] = Field(default_factory=list)
    ready_for_review: bool = False
    approved_for_submission: bool = False
    submitted: bool = False
    submission_status: str = "not_submitted"
    pending_background_field: str | None = None
    source: ScholarshipSource


class ApplicationPreview(BaseModel):
    application_id: str
    ready: bool
    completed_fields: int
    missing_required_fields: list[str]
    warnings: list[str]
    answers: list[dict[str, Any]]


class ApplicationEmailDraft(BaseModel):
    application_id: str
    to: str | None
    subject: str
    body: str
    attachments_required: list[str] = Field(default_factory=list)
    scholarship_name: str
    deadline: str
    ready: bool
    missing_fields: list[str] = Field(default_factory=list)
    mailto_url: str | None = None
