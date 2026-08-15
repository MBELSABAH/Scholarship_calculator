"""Deterministic, allow-listed tools available to the academic agent."""

from __future__ import annotations

import json
from typing import Any, Callable

from Mark import Mark
from backend.models import AcademicSnapshot
from backend.scholarship_agent import ScholarshipSession
from backend.scholarship_service import ScholarshipResearchError


SCHOLARSHIP_SESSION = ScholarshipSession()


class ToolExecutionError(ValueError):
    """A safe validation or dispatch error that can be returned to the model."""


TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "get_student_summary",
            "description": (
                "Retrieve the student's current cumulative GPA, completed credits, "
                "majors, and minors. Use this for factual questions about the student's "
                "overall academic summary or completed credit count."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_scholarship_summary",
            "description": (
                "Retrieve scholarship amounts and weighted averages produced by the "
                "application's deterministic scholarship engine. Use this for scholarship "
                "eligibility, award, yearly-average, and best-academic-year questions."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_academic_record",
            "description": (
                "Retrieve structured completed courses, grades, GPA values, letters, and "
                "credits. Use this for questions about courses, grades, highest or lowest "
                "marks, or a specific academic year. Filters are optional."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "academic_year": {
                        "type": "string",
                        "description": "Exact academic year such as 2025-2026.",
                    },
                    "course_code": {
                        "type": "string",
                        "description": (
                            "Exact full or base course code, such as CS-2920-01 or CS-2920."
                        ),
                    },
                    "limit": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 100,
                        "description": "Maximum total number of course records to return.",
                    },
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "project_gpa",
            "description": (
                "Calculate a hypothetical cumulative GPA with deterministic UPEI grade-to-"
                "GPA rules. Always use this tool for future-grade or projected-GPA questions; "
                "do not calculate a projection yourself."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "future_courses": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": 40,
                        "items": {
                            "type": "object",
                            "properties": {
                                "grade": {
                                    "type": "integer",
                                    "minimum": 0,
                                    "maximum": 100,
                                    "description": "Expected percentage grade.",
                                },
                                "credits": {
                                    "type": "number",
                                    "exclusiveMinimum": 0,
                                    "maximum": 30,
                                    "description": "Credit hours for the future course.",
                                },
                            },
                            "required": ["grade", "credits"],
                            "additionalProperties": False,
                        },
                    }
                },
                "required": ["future_courses"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_course_extremes",
            "description": "Deterministically return the highest or lowest graded courses from the current connected snapshot, always including academic year. Use for course ranking questions.",
            "parameters": {
                "type": "object",
                "properties": {"count": {"type": "integer", "minimum": 1, "maximum": 20}, "direction": {"type": "string", "enum": ["highest", "lowest"]}},
                "required": ["count", "direction"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_subject_performance",
            "description": "Deterministically aggregate the complete current connected academic record by subject prefix. Use for subject-performance claims.",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
]

TOOL_DEFINITIONS.extend(
    [
        {
            "type": "function",
            "function": {
                "name": "search_upei_scholarships",
                "description": (
                    "Search the official UPEI scholarship directory using safe cached web retrieval. "
                    "Use after get_student_summary when the student asks to find opportunities. "
                    "Omitted filters default to the connected academic profile."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "faculty": {"type": "string"},
                        "major": {"type": "string"},
                        "year_of_study": {"type": "integer", "minimum": 1, "maximum": 6},
                        "keyword": {"type": "string"},
                        "refresh": {"type": "boolean", "description": "Bypass the in-memory cache only when explicitly requested."},
                    },
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "rank_scholarship_matches",
                "description": (
                    "Compare the most recently searched official UPEI scholarships with the connected "
                    "academic snapshot and confirmed background profile. Distinguishes conflicts from "
                    "missing personal information; never infer eligibility yourself."
                ),
                "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "inspect_scholarship",
                "description": "Retrieve one cached official scholarship and its match explanation by ID.",
                "parameters": {
                    "type": "object",
                    "properties": {"scholarship_id": {"type": "string"}},
                    "required": ["scholarship_id"],
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_student_background",
                "description": "Retrieve confirmed scholarship-relevant personal facts stored for this session.",
                "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "save_student_background_answer",
                "description": (
                    "Save one personal fact explicitly confirmed by the student. For a one-word reply such "
                    "as Yes, omit field to use the application's pending question. Never call without confirmation."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "field": {"type": "string"},
                        "value": {},
                        "confirmed": {"type": "boolean"},
                    },
                    "required": ["value", "confirmed"],
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "open_scholarship_application",
                "description": (
                    "Open semantic application state for a selected scholarship, inspect normalized official "
                    "form fields when accessible, prefill known academic facts, and identify the next missing field. "
                    "Use only when there is no current_application_id; otherwise inspect the existing application."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {"scholarship_id": {"type": "string"}},
                    "required": ["scholarship_id"],
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "inspect_application_form",
                "description": "Retrieve normalized fields and the one pending question for an application already opened in this session. Prefer this whenever current_application_id is present.",
                "parameters": {
                    "type": "object",
                    "properties": {"application_id": {"type": "string"}},
                    "required": ["application_id"],
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "save_application_answer",
                "description": "Save a student-provided application answer. Sensitive and essay answers require explicit user approval. Use this with user_approved=true when the student says Use this answer for an existing draft.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "application_id": {"type": "string"},
                        "field_id": {"type": "string"},
                        "value": {},
                        "user_approved": {"type": "boolean"},
                    },
                    "required": ["application_id", "field_id", "value", "user_approved"],
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "draft_personal_statement",
                "description": (
                    "Store an unapproved personal-statement draft. source_notes must be the student's real raw "
                    "facts copied exactly from a student message. draft_text must use only those facts, add no "
                    "inferred emotions or outcomes, and respect the field limit."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "application_id": {"type": "string"},
                        "field_id": {"type": "string"},
                        "source_notes": {"type": "string"},
                        "draft_text": {"type": "string"},
                    },
                    "required": ["application_id", "field_id", "source_notes", "draft_text"],
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "prepare_application_preview",
                "description": "Validate required fields, reviewed essays, limits, and warnings without submitting anything.",
                "parameters": {
                    "type": "object",
                    "properties": {"application_id": {"type": "string"}},
                    "required": ["application_id"],
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "prepare_application_email",
                "description": "Prepare a reviewable scholarship application email draft. Never send email; use only official recipient, deadline, and document metadata from the application state.",
                "parameters": {
                    "type": "object",
                    "properties": {"application_id": {"type": "string"}},
                    "required": ["application_id"],
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "submit_application",
                "description": (
                    "Check submission state. This cannot authorize submission; the student must first use the "
                    "explicit Approve & Submit UI control."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {"application_id": {"type": "string"}},
                    "required": ["application_id"],
                    "additionalProperties": False,
                },
            },
        },
    ]
)


def _model_dump(model: Any) -> dict[str, Any]:
    return model.model_dump() if hasattr(model, "model_dump") else model.dict()


def _normalise_number(value: float) -> int | float:
    return int(value) if value.is_integer() else value


def _require_no_arguments(arguments: dict[str, Any]) -> None:
    if arguments:
        raise ToolExecutionError("This tool does not accept arguments.")


def get_student_summary(
    snapshot: AcademicSnapshot, arguments: dict[str, Any] | None = None
) -> dict[str, Any]:
    _require_no_arguments(arguments or {})
    student = snapshot.student
    return {
        "name": student.name,
        "full_name": student.full_name,
        "display_name": student.display_name,
        "university": student.university,
        "faculty": student.faculty,
        "majors": list(student.majors),
        "minors": list(student.minors),
        "year_of_study": student.year_of_study,
        "cumulative_gpa": student.cumulative_gpa,
        "total_credit_hours": student.total_credit_hours,
        "completed_credits": student.completed_credits,
        "required_degree_credits": student.required_degree_credits,
        "academic_progress": _model_dump(snapshot.academic_progress),
    }


def get_scholarship_summary(
    snapshot: AcademicSnapshot, arguments: dict[str, Any] | None = None
) -> dict[str, Any]:
    _require_no_arguments(arguments or {})
    years = snapshot.scholarship_summary.years
    summary = snapshot.scholarship_summary
    return {
        "latest_acquired_year": summary.latest_acquired_year,
        "latest_acquired_amount": summary.latest_acquired_amount,
        "latest_acquired_weighted_average": summary.latest_acquired_weighted_average,
        "academic_years": [
            {
                "year": year.year,
                "weighted_average": year.weighted_average,
                "scholarship_amount": year.amount,
                "calculation_status": year.calculation_status,
            }
            for year in years
        ],
    }


def get_academic_record(
    snapshot: AcademicSnapshot, arguments: dict[str, Any] | None = None
) -> dict[str, Any]:
    arguments = arguments or {}
    allowed = {"academic_year", "course_code", "limit"}
    unexpected = set(arguments) - allowed
    if unexpected:
        raise ToolExecutionError(f"Unsupported academic record filter: {sorted(unexpected)[0]}.")

    academic_year = arguments.get("academic_year")
    if academic_year is not None:
        if not isinstance(academic_year, str) or not academic_year.strip():
            raise ToolExecutionError("academic_year must be a non-empty string.")
        academic_year = academic_year.strip()

    course_code = arguments.get("course_code")
    if course_code is not None:
        if not isinstance(course_code, str) or not course_code.strip():
            raise ToolExecutionError("course_code must be a non-empty string.")
        course_code = course_code.strip().upper()

    limit = arguments.get("limit")
    if limit is not None:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
            raise ToolExecutionError("limit must be an integer between 1 and 100.")

    remaining = limit
    result_years: list[dict[str, Any]] = []
    for year in snapshot.academic_years:
        if academic_year and year.year != academic_year:
            continue
        courses: list[dict[str, Any]] = []
        for course in year.courses:
            if course_code and course.code.upper() != course_code and course.base_code.upper() != course_code:
                continue
            if remaining is not None and remaining <= 0:
                break
            courses.append(_model_dump(course))
            if remaining is not None:
                remaining -= 1
        if courses:
            result_years.append({"year": year.year, "courses": courses})
        if remaining is not None and remaining <= 0:
            break

    return {"snapshot_id": snapshot.snapshot_id, "source": snapshot.source, "academic_years": result_years}


def get_course_extremes(
    snapshot: AcademicSnapshot, arguments: dict[str, Any] | None = None
) -> dict[str, Any]:
    arguments = arguments or {}
    if set(arguments) != {"count", "direction"} or not isinstance(arguments.get("count"), int) or arguments["count"] < 1 or arguments["count"] > 20 or arguments.get("direction") not in {"highest", "lowest"}:
        raise ToolExecutionError("get_course_extremes requires count (1–20) and direction (highest or lowest).")
    courses = [
        {**_model_dump(course), "academic_year": year.year}
        for year in snapshot.academic_years
        for course in year.courses
        if isinstance(course.grade, int) and not isinstance(course.grade, bool)
    ]
    reverse = arguments["direction"] == "highest"
    courses.sort(key=lambda course: (course["grade"], course["code"]), reverse=reverse)
    return {"snapshot_id": snapshot.snapshot_id, "source": snapshot.source, "direction": arguments["direction"], "courses": courses[:arguments["count"]]}


def get_subject_performance(
    snapshot: AcademicSnapshot, arguments: dict[str, Any] | None = None
) -> dict[str, Any]:
    _require_no_arguments(arguments or {})
    groups: dict[str, list[int]] = {}
    for year in snapshot.academic_years:
        for course in year.courses:
            if isinstance(course.grade, int) and not isinstance(course.grade, bool):
                subject = course.base_code.split("-")[0]
                groups.setdefault(subject, []).append(course.grade)
    subjects = [
        {"subject": subject, "course_count": len(grades), "average_grade": round(sum(grades) / len(grades), 2)}
        for subject, grades in groups.items()
    ]
    subjects.sort(key=lambda item: (-item["average_grade"], -item["course_count"], item["subject"]))
    return {"snapshot_id": snapshot.snapshot_id, "source": snapshot.source, "subjects": subjects}


def _current_quality_points(snapshot: AcademicSnapshot) -> tuple[float, float]:
    """Recreate Courses.calculate_cumulative_gpa without using its rounded string."""
    highest_attempts: dict[str, tuple[float, float, float]] = {}
    for year in snapshot.academic_years:
        for course in year.courses:
            grade = course.grade
            if isinstance(grade, str):
                if grade in {"DSC", "N/A", "P"}:
                    continue
                comparable = 0.0 if grade == "E" else -1.0
            elif isinstance(grade, (int, float)) and not isinstance(grade, bool):
                comparable = float(grade)
            else:
                continue
            if not isinstance(course.gpa, (int, float)) or isinstance(course.gpa, bool):
                continue
            previous = highest_attempts.get(course.base_code)
            if previous is None or comparable > previous[0]:
                highest_attempts[course.base_code] = (
                    comparable,
                    float(course.gpa),
                    float(course.credits),
                )

    credits = sum(item[2] for item in highest_attempts.values())
    quality_points = sum(item[1] * item[2] for item in highest_attempts.values())
    if credits:
        return quality_points, credits

    fallback_credits = float(snapshot.student.total_credit_hours)
    fallback_gpa = snapshot.student.cumulative_gpa
    if fallback_credits and fallback_gpa is not None:
        return float(fallback_gpa) * fallback_credits, fallback_credits
    return 0.0, 0.0


def project_gpa(
    snapshot: AcademicSnapshot, arguments: dict[str, Any] | None = None
) -> dict[str, Any]:
    arguments = arguments or {}
    if set(arguments) != {"future_courses"}:
        raise ToolExecutionError("project_gpa requires only future_courses.")
    future_courses = arguments.get("future_courses")
    if not isinstance(future_courses, list) or not 1 <= len(future_courses) <= 40:
        raise ToolExecutionError("future_courses must contain between 1 and 40 courses.")

    added_quality_points = 0.0
    added_credits = 0.0
    for index, course in enumerate(future_courses, start=1):
        if not isinstance(course, dict) or set(course) != {"grade", "credits"}:
            raise ToolExecutionError(
                f"Future course {index} must contain only grade and credits."
            )
        grade = course["grade"]
        credits = course["credits"]
        if (
            isinstance(grade, bool)
            or not isinstance(grade, (int, float))
            or not float(grade).is_integer()
            or not 0 <= grade <= 100
        ):
            raise ToolExecutionError(
                f"Future course {index} grade must be a whole number from 0 to 100."
            )
        if (
            isinstance(credits, bool)
            or not isinstance(credits, (int, float))
            or not 0 < credits <= 30
        ):
            raise ToolExecutionError(
                f"Future course {index} credits must be a number greater than 0 and at most 30."
            )
        mark = Mark(int(grade))
        added_quality_points += float(mark.gpa) * float(credits)
        added_credits += float(credits)

    current_quality_points, current_credits = _current_quality_points(snapshot)
    projected_gpa = (current_quality_points + added_quality_points) / (
        current_credits + added_credits
    )
    return {
        "current_gpa": snapshot.student.cumulative_gpa,
        "current_credits": _normalise_number(current_credits),
        "projected_gpa": round(projected_gpa, 3),
        "added_credits": _normalise_number(added_credits),
    }


def search_upei_scholarships(
    snapshot: AcademicSnapshot, arguments: dict[str, Any] | None = None
) -> dict[str, Any]:
    arguments = arguments or {}
    allowed = {"faculty", "major", "year_of_study", "keyword", "refresh"}
    if set(arguments) - allowed:
        raise ToolExecutionError("Unsupported scholarship search argument.")
    for key in ("faculty", "major", "keyword"):
        if key in arguments and (
            not isinstance(arguments[key], str) or not arguments[key].strip()
        ):
            raise ToolExecutionError(f"{key} must be a non-empty string.")
    year = arguments.get("year_of_study")
    if year is not None and (
        isinstance(year, bool) or not isinstance(year, int) or not 1 <= year <= 6
    ):
        raise ToolExecutionError("year_of_study must be an integer from 1 to 6.")
    refresh = arguments.get("refresh", False)
    if not isinstance(refresh, bool):
        raise ToolExecutionError("refresh must be true or false.")
    result = SCHOLARSHIP_SESSION.discovery.search(
        faculty=arguments.get("faculty") or snapshot.student.faculty,
        major=arguments.get("major")
        or (snapshot.student.majors[0] if snapshot.student.majors else None),
        year_of_study=year or snapshot.student.year_of_study,
        keyword=arguments.get("keyword"),
        refresh=refresh,
    )
    payload = _model_dump(result)
    payload["filters_used"] = {
        "faculty": arguments.get("faculty") or snapshot.student.faculty,
        "major": arguments.get("major")
        or (snapshot.student.majors[0] if snapshot.student.majors else None),
        "year_of_study": year or snapshot.student.year_of_study,
    }
    payload["academic_progress"] = _model_dump(snapshot.academic_progress)
    return payload


def rank_scholarship_matches(
    snapshot: AcademicSnapshot, arguments: dict[str, Any] | None = None
) -> dict[str, Any]:
    _require_no_arguments(arguments or {})
    search = SCHOLARSHIP_SESSION.discovery.cached_search()
    if search is None:
        raise ToolExecutionError("Search official UPEI scholarships before ranking matches.")
    matches = SCHOLARSHIP_SESSION.rank(search, snapshot)
    return {
        "matches": [_model_dump(match) for match in matches],
        "sources": [_model_dump(source) for source in search.sources],
        "source_mode": search.source_mode,
        "warning": search.warning,
        "student_profile_used": {
            "faculty": snapshot.student.faculty,
            "majors": list(snapshot.student.majors),
            "year_of_study": snapshot.student.year_of_study,
            "completed_credits": snapshot.student.completed_credits,
            "cumulative_gpa": snapshot.student.cumulative_gpa,
            "confirmed_background": {
                key: value
                for key, value in SCHOLARSHIP_SESSION.get_background().items()
                if value not in (None, [], "")
            },
        },
    }


def inspect_scholarship(
    snapshot: AcademicSnapshot, arguments: dict[str, Any] | None = None
) -> dict[str, Any]:
    del snapshot
    arguments = arguments or {}
    if set(arguments) != {"scholarship_id"} or not isinstance(
        arguments.get("scholarship_id"), str
    ):
        raise ToolExecutionError("inspect_scholarship requires scholarship_id.")
    return SCHOLARSHIP_SESSION.inspect_match(arguments["scholarship_id"])


def get_student_background(
    snapshot: AcademicSnapshot, arguments: dict[str, Any] | None = None
) -> dict[str, Any]:
    del snapshot
    _require_no_arguments(arguments or {})
    return SCHOLARSHIP_SESSION.get_background()


def save_student_background_answer(
    snapshot: AcademicSnapshot, arguments: dict[str, Any] | None = None
) -> dict[str, Any]:
    del snapshot
    arguments = arguments or {}
    allowed = {"field", "value", "confirmed"}
    if set(arguments) - allowed or "value" not in arguments or "confirmed" not in arguments:
        raise ToolExecutionError("A confirmed value is required for one background field.")
    field = arguments.get("field")
    if field is not None and not isinstance(field, str):
        raise ToolExecutionError("field must be a string.")
    if not isinstance(arguments["confirmed"], bool):
        raise ToolExecutionError("confirmed must be true or false.")
    return SCHOLARSHIP_SESSION.save_background_answer(
        field, arguments["value"], confirmed=arguments["confirmed"]
    )


def open_scholarship_application(
    snapshot: AcademicSnapshot, arguments: dict[str, Any] | None = None
) -> dict[str, Any]:
    arguments = arguments or {}
    if set(arguments) != {"scholarship_id"} or not isinstance(
        arguments.get("scholarship_id"), str
    ):
        raise ToolExecutionError("open_scholarship_application requires scholarship_id.")
    return _model_dump(
        SCHOLARSHIP_SESSION.open_application(arguments["scholarship_id"], snapshot)
    )


def inspect_application_form(
    snapshot: AcademicSnapshot, arguments: dict[str, Any] | None = None
) -> dict[str, Any]:
    del snapshot
    arguments = arguments or {}
    if set(arguments) != {"application_id"} or not isinstance(
        arguments.get("application_id"), str
    ):
        raise ToolExecutionError("inspect_application_form requires application_id.")
    return _model_dump(SCHOLARSHIP_SESSION.get_application(arguments["application_id"]))


def save_application_answer(
    snapshot: AcademicSnapshot, arguments: dict[str, Any] | None = None
) -> dict[str, Any]:
    del snapshot
    arguments = arguments or {}
    required = {"application_id", "field_id", "value", "user_approved"}
    if set(arguments) != required:
        raise ToolExecutionError("save_application_answer requires one complete approved field answer.")
    if not isinstance(arguments["application_id"], str) or not isinstance(
        arguments["field_id"], str
    ):
        raise ToolExecutionError("Application and field IDs must be strings.")
    if not isinstance(arguments["user_approved"], bool):
        raise ToolExecutionError("user_approved must be true or false.")
    return _model_dump(
        SCHOLARSHIP_SESSION.save_application_answer(
            arguments["application_id"],
            arguments["field_id"],
            arguments["value"],
            user_approved=arguments["user_approved"],
        )
    )


def draft_personal_statement(
    snapshot: AcademicSnapshot, arguments: dict[str, Any] | None = None
) -> dict[str, Any]:
    del snapshot
    arguments = arguments or {}
    required = {"application_id", "field_id", "source_notes", "draft_text"}
    if set(arguments) != required or not all(
        isinstance(arguments[key], str) for key in required
    ):
        raise ToolExecutionError("Drafting requires application_id, field_id, source_notes, and draft_text.")
    draft = SCHOLARSHIP_SESSION.save_draft(
        arguments["application_id"],
        arguments["field_id"],
        arguments["source_notes"],
        arguments["draft_text"],
    )
    return {
        "draft": _model_dump(draft),
        "review_required": True,
        "message": "The draft is saved but cannot be used until the student reviews and approves it.",
    }


def prepare_application_preview(
    snapshot: AcademicSnapshot, arguments: dict[str, Any] | None = None
) -> dict[str, Any]:
    del snapshot
    arguments = arguments or {}
    if set(arguments) != {"application_id"} or not isinstance(
        arguments.get("application_id"), str
    ):
        raise ToolExecutionError("prepare_application_preview requires application_id.")
    return _model_dump(SCHOLARSHIP_SESSION.prepare_preview(arguments["application_id"]))


def prepare_application_email(
    snapshot: AcademicSnapshot, arguments: dict[str, Any] | None = None
) -> dict[str, Any]:
    del snapshot
    arguments = arguments or {}
    if set(arguments) != {"application_id"} or not isinstance(arguments.get("application_id"), str):
        raise ToolExecutionError("prepare_application_email requires application_id.")
    return _model_dump(SCHOLARSHIP_SESSION.prepare_application_email(arguments["application_id"]))


def submit_application(
    snapshot: AcademicSnapshot, arguments: dict[str, Any] | None = None
) -> dict[str, Any]:
    del snapshot
    arguments = arguments or {}
    if set(arguments) != {"application_id"} or not isinstance(
        arguments.get("application_id"), str
    ):
        raise ToolExecutionError("submit_application requires application_id.")
    return SCHOLARSHIP_SESSION.submit_from_agent(arguments["application_id"])


ToolFunction = Callable[[AcademicSnapshot, dict[str, Any] | None], dict[str, Any]]
TOOL_FUNCTIONS: dict[str, ToolFunction] = {
    "get_student_summary": get_student_summary,
    "get_scholarship_summary": get_scholarship_summary,
    "get_academic_record": get_academic_record,
    "get_course_extremes": get_course_extremes,
    "get_subject_performance": get_subject_performance,
    "project_gpa": project_gpa,
    "search_upei_scholarships": search_upei_scholarships,
    "rank_scholarship_matches": rank_scholarship_matches,
    "inspect_scholarship": inspect_scholarship,
    "get_student_background": get_student_background,
    "save_student_background_answer": save_student_background_answer,
    "open_scholarship_application": open_scholarship_application,
    "inspect_application_form": inspect_application_form,
    "save_application_answer": save_application_answer,
    "draft_personal_statement": draft_personal_statement,
    "prepare_application_preview": prepare_application_preview,
    "prepare_application_email": prepare_application_email,
    "submit_application": submit_application,
}


def execute_tool(
    name: str, raw_arguments: str | dict[str, Any] | None, snapshot: AcademicSnapshot
) -> dict[str, Any]:
    tool = TOOL_FUNCTIONS.get(name)
    if tool is None:
        raise ToolExecutionError(f"Unknown academic tool: {name}.")

    if raw_arguments in (None, ""):
        arguments: dict[str, Any] = {}
    elif isinstance(raw_arguments, str):
        try:
            parsed = json.loads(raw_arguments)
        except json.JSONDecodeError as exc:
            raise ToolExecutionError("Tool arguments were not valid JSON.") from exc
        if not isinstance(parsed, dict):
            raise ToolExecutionError("Tool arguments must be a JSON object.")
        arguments = parsed
    elif isinstance(raw_arguments, dict):
        arguments = raw_arguments
    else:
        raise ToolExecutionError("Tool arguments must be a JSON object.")

    try:
        return tool(snapshot, arguments)
    except ToolExecutionError:
        raise
    except (ValueError, ScholarshipResearchError) as exc:
        raise ToolExecutionError(str(exc)) from exc
