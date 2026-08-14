"""Deterministic scholarship matching, background, and application session state."""

from __future__ import annotations

import re
from threading import Lock
from typing import Any
from uuid import uuid4

from backend.models import AcademicSnapshot
from backend.scholarship_models import (
    ApplicationField,
    ApplicationPreview,
    DraftAnswer,
    ScholarshipApplicationState,
    ScholarshipMatch,
    ScholarshipRecord,
    ScholarshipSearchResult,
    ScholarshipSource,
    StudentBackgroundProfile,
)
from backend.scholarship_service import ScholarshipDiscoveryService, ScholarshipResearchError


BACKGROUND_FIELDS = set(StudentBackgroundProfile.model_fields)
LIST_BACKGROUND_FIELDS = {
    "community_involvement",
    "leadership",
    "volunteering",
    "clubs",
    "personal_story_notes",
    "other_awards",
}
BOOLEAN_BACKGROUND_FIELDS = {
    "international_student",
    "financial_need",
    "gender_identity_criterion",
    "indigenous_identity",
    "disability_status",
    "pei_high_school_graduate",
}


def _model_dump(model: Any) -> dict[str, Any]:
    return model.model_dump() if hasattr(model, "model_dump") else model.dict()


class ScholarshipSession:
    def __init__(self, discovery: ScholarshipDiscoveryService | None = None) -> None:
        self.discovery = discovery or ScholarshipDiscoveryService()
        self.background = StudentBackgroundProfile()
        self.matches: list[ScholarshipMatch] = []
        self.applications: dict[str, ScholarshipApplicationState] = {}
        self._lock = Lock()

    def clear_student_state(self) -> None:
        with self._lock:
            self.background = StudentBackgroundProfile()
            self.matches = []
            self.applications = {}
        self.discovery.clear()

    def get_background(self) -> dict[str, Any]:
        with self._lock:
            return _model_dump(self.background)

    def save_background_answer(
        self, field: str | None, value: Any, *, confirmed: bool
    ) -> dict[str, Any]:
        if not confirmed:
            raise ValueError("The student must confirm personal background information.")
        if not field:
            field = self._pending_background_field()
        if field not in BACKGROUND_FIELDS:
            raise ValueError("That student background field is not supported.")
        normalised = self._normalise_background_value(field, value)
        with self._lock:
            data = _model_dump(self.background)
            data[field] = normalised
            self.background = StudentBackgroundProfile(**data)
            for application_id, application in list(self.applications.items()):
                updated = self._apply_background_to_application(application, field, normalised)
                self.applications[application_id] = updated
        return {"saved": True, "field": field, "value": normalised}

    def search_and_rank(
        self,
        snapshot: AcademicSnapshot,
        *,
        faculty: str | None = None,
        major: str | None = None,
        year_of_study: int | None = None,
        keyword: str | None = None,
        refresh: bool = False,
    ) -> dict[str, Any]:
        student = snapshot.student
        search = self.discovery.search(
            faculty=faculty or student.faculty,
            major=major or (student.majors[0] if student.majors else None),
            year_of_study=year_of_study or student.year_of_study,
            keyword=keyword,
            refresh=refresh,
        )
        matches = self.rank(search, snapshot)
        return {
            "matches": [_model_dump(match) for match in matches],
            "source_mode": search.source_mode,
            "warning": search.warning,
            "sources": [_model_dump(source) for source in search.sources],
        }

    def rank(
        self, search: ScholarshipSearchResult, snapshot: AcademicSnapshot
    ) -> list[ScholarshipMatch]:
        with self._lock:
            background = self.background
        latest_average = next(
            (
                year.weighted_average
                for year in reversed(snapshot.scholarship_summary.years)
                if year.calculation_status == "calculated" and year.weighted_average is not None
            ),
            None,
        )
        student_majors = {major.casefold() for major in snapshot.student.majors}
        student_minors = {minor.casefold() for minor in snapshot.student.minors}
        student_faculty = (snapshot.student.faculty or "").casefold()
        results: list[ScholarshipMatch] = []

        for scholarship in search.scholarships:
            known_matches: list[str] = []
            missing: list[str] = []
            conflicts: list[str] = []
            eligibility_unknown = False

            if scholarship.major:
                accepted = {major.casefold() for major in scholarship.major}
                overlap = accepted & (student_majors | student_minors)
                if overlap:
                    known_matches.append(f"Program matches: {', '.join(sorted(overlap)).title()}")
                else:
                    conflicts.append("The listed program requirement does not match the connected major or minor.")
            elif scholarship.faculty:
                faculty_terms = {faculty.casefold() for faculty in scholarship.faculty}
                is_open_faculty = any("all facult" in term for term in faculty_terms)
                if is_open_faculty:
                    known_matches.append("The award is listed for all faculties.")
                elif any(term in student_faculty or student_faculty in term for term in faculty_terms if student_faculty):
                    known_matches.append("Faculty or school matches the connected record.")
                else:
                    missing.append("The published faculty wording needs confirmation against the connected school.")
                    eligibility_unknown = True
            else:
                known_matches.append("Open program criteria; no conflicting major was found.")

            if scholarship.minimum_average is not None:
                if latest_average is None:
                    missing.append("A comparable completed-year percentage average is unavailable.")
                    eligibility_unknown = True
                elif latest_average >= scholarship.minimum_average:
                    known_matches.append(
                        f"Latest calculated average {latest_average:.2f}% meets the {scholarship.minimum_average:g}% minimum."
                    )
                else:
                    conflicts.append(
                        f"Latest calculated average {latest_average:.2f}% is below the {scholarship.minimum_average:g}% minimum."
                    )
            elif scholarship.academic_requirements:
                known_matches.append("The connected record can support review of the stated academic criterion.")

            if scholarship.year_of_study:
                student_year = snapshot.student.year_of_study
                if student_year is None:
                    missing.append("Year of study is required but unavailable in the connected profile.")
                    eligibility_unknown = True
                else:
                    year_pattern = re.compile(rf"\b{student_year}(?:st|nd|rd|th)\b")
                    year_matches = any(year_pattern.search(label.casefold()) for label in scholarship.year_of_study)
                    if year_matches:
                        known_matches.append(f"Year of study matches year {student_year}.")
                    else:
                        conflicts.append(f"The published year-of-study requirement does not include year {student_year}.")

            if scholarship.financial_need_required:
                if background.financial_need is None:
                    missing.append("Financial need status must be confirmed by the student.")
                    eligibility_unknown = True
                elif background.financial_need:
                    known_matches.append("Student confirmed that financial need applies.")
                else:
                    conflicts.append("Student reported that financial need does not apply.")

            if scholarship.citizenship_or_residency_requirements:
                if not background.citizenship_status and not background.province_or_region:
                    missing.append("Citizenship or residency status must be confirmed by the student.")
                    eligibility_unknown = True
                else:
                    missing.append("Student-supplied citizenship/residency information must be checked against the published wording.")
                    eligibility_unknown = True

            personal_checks = [
                (
                    r"\b(?:woman|women|female)\b",
                    background.gender_identity_criterion,
                    "Whether the published women/female identity criterion applies must be confirmed by the student.",
                    "Student confirmed that the published women/female identity criterion applies.",
                    "Student reported that the published women/female identity criterion does not apply.",
                ),
                (
                    r"\b(?:indigenous|mi['’]?kmaq|first nations|inuit|m[eé]tis)\b",
                    background.indigenous_identity,
                    "Indigenous identity must be confirmed by the student.",
                    "Student confirmed that the published Indigenous identity criterion applies.",
                    "Student reported that the published Indigenous identity criterion does not apply.",
                ),
                (
                    r"\bdisabilit(?:y|ies)\b",
                    background.disability_status,
                    "Disability status must be confirmed by the student.",
                    "Student confirmed that the published disability criterion applies.",
                    "Student reported that the published disability criterion does not apply.",
                ),
                (
                    r"\bpei high school|prince edward island high school\b",
                    background.pei_high_school_graduate,
                    "PEI high-school graduation must be confirmed by the student.",
                    "Student confirmed PEI high-school graduation.",
                    "Student reported that the PEI high-school criterion does not apply.",
                ),
            ]
            description = scholarship.description.casefold()
            for pattern, answer, unknown_text, match_text, conflict_text in personal_checks:
                if not re.search(pattern, description, re.IGNORECASE):
                    continue
                criterion_sentence = next(
                    (
                        sentence
                        for sentence in re.split(r"(?<=[.!?])\s+", description)
                        if re.search(pattern, sentence, re.IGNORECASE)
                    ),
                    description,
                )
                is_preference = bool(re.search(r"\bprefer(?:ence|red|ably)?\b", criterion_sentence))
                if answer is None:
                    missing.append(unknown_text)
                    eligibility_unknown = eligibility_unknown or not is_preference
                elif answer:
                    known_matches.append(match_text)
                elif is_preference:
                    missing.append("A published preference does not appear to apply, but it is not treated as a disqualifying conflict.")
                else:
                    conflicts.append(conflict_text)

            co_op_match = re.search(r"(?:completed?|completion of)\s+(?:at least\s+)?(\w+|\d+)\s+co-?op", description)
            if co_op_match:
                word_numbers = {"one": 1, "two": 2, "three": 3, "four": 4}
                required_terms = word_numbers.get(co_op_match.group(1), None)
                if required_terms is None and co_op_match.group(1).isdigit():
                    required_terms = int(co_op_match.group(1))
                if background.co_op_terms_completed is None:
                    missing.append("Completed co-op work terms must be confirmed by the student.")
                    eligibility_unknown = True
                elif required_terms is not None and background.co_op_terms_completed < required_terms:
                    conflicts.append(f"The award requires {required_terms} completed co-op work terms.")
                else:
                    known_matches.append("Student-confirmed co-op experience is available for the published criterion.")

            if scholarship.personal_statement_required:
                missing.append("A reviewed personal statement is required for the application.")
            if scholarship.reference_required:
                missing.append("A reference is required for the application.")

            if conflicts:
                level = "not_eligible"
            elif eligibility_unknown:
                level = "needs_more_information"
            elif len(known_matches) >= 3:
                level = "excellent"
            elif len(known_matches) >= 1:
                level = "good"
            else:
                level = "possible"
            known_count = len(known_matches) + len(conflicts)
            total_count = known_count + sum(
                "required for the application" not in item for item in missing
            )
            confidence = round(min(0.98, max(0.2, known_count / max(1, total_count))), 2)
            results.append(
                ScholarshipMatch(
                    scholarship_id=scholarship.id,
                    scholarship=scholarship,
                    match_level=level,
                    confidence=confidence,
                    known_matches=known_matches,
                    missing_information=missing,
                    known_conflicts=conflicts,
                )
            )

        order = {
            "excellent": 0,
            "good": 1,
            "possible": 2,
            "needs_more_information": 3,
            "not_eligible": 4,
        }
        results.sort(
            key=lambda match: (
                order[match.match_level],
                -match.confidence,
                -(match.scholarship.amount or 0),
            )
        )
        with self._lock:
            self.matches = results
        return results

    def get_matches(self) -> list[dict[str, Any]]:
        with self._lock:
            return [_model_dump(match) for match in self.matches]

    def inspect_match(self, scholarship_id: str) -> dict[str, Any]:
        with self._lock:
            for match in self.matches:
                if match.scholarship_id == scholarship_id:
                    return _model_dump(match)
        scholarship = self.discovery.inspect(scholarship_id)
        return {
            "scholarship_id": scholarship.id,
            "scholarship": _model_dump(scholarship),
            "match_level": "possible",
            "confidence": 0.2,
            "known_matches": [],
            "missing_information": ["Run scholarship matching against the connected profile."],
            "known_conflicts": [],
        }

    def open_application(
        self, scholarship_id: str, snapshot: AcademicSnapshot
    ) -> ScholarshipApplicationState:
        scholarship = self.discovery.inspect(scholarship_id)
        inspection_status, raw_fields = self.discovery.inspect_application_fields(scholarship)
        academic_known = {
            "name": snapshot.student.name,
            "major": ", ".join(snapshot.student.majors),
            "minor": ", ".join(snapshot.student.minors),
            "cumulative_gpa": snapshot.student.cumulative_gpa,
            "completed_credits": snapshot.student.total_credit_hours,
        }
        fields = [ApplicationField(**field) for field in raw_fields]
        with self._lock:
            background = self.background
        for field in fields:
            mapped = self._known_answer_for_field(field, academic_known, background)
            if mapped is not None:
                field.known_answer = mapped
                field.source = "student" if field.field_id in BACKGROUND_FIELDS else "academic_snapshot"
        missing = [field.field_id for field in fields if field.required and field.known_answer in (None, "")]
        pending = next((field.field_id for field in fields if field.field_id in BACKGROUND_FIELDS and field.field_id in missing), None)
        state = ScholarshipApplicationState(
            application_id=uuid4().hex,
            scholarship_id=scholarship.id,
            scholarship_name=scholarship.name,
            application_url=scholarship.application_url,
            inspection_status=inspection_status,
            fields=fields,
            known_fields=academic_known,
            missing_fields=missing,
            pending_background_field=pending,
            source=ScholarshipSource(title=scholarship.source_title, url=scholarship.source_url),
        )
        with self._lock:
            self.applications[state.application_id] = state
        return state

    def get_application(self, application_id: str) -> ScholarshipApplicationState:
        with self._lock:
            state = self.applications.get(application_id)
        if state is None:
            raise ValueError("That scholarship application is not available in this session.")
        return state

    def save_application_answer(
        self,
        application_id: str,
        field_id: str,
        value: Any,
        *,
        user_approved: bool,
    ) -> ScholarshipApplicationState:
        state = self.get_application(application_id)
        field = next((item for item in state.fields if item.field_id == field_id), None)
        if field is None:
            raise ValueError("That application field is not available.")
        if field.sensitive and not user_approved:
            raise ValueError("The student must explicitly confirm this sensitive answer.")
        if field_id in BACKGROUND_FIELDS:
            self.save_background_answer(field_id, value, confirmed=user_approved)
        text_value = str(value).strip() if not isinstance(value, bool) else value
        if field.max_length and len(str(text_value)) > field.max_length:
            raise ValueError(f"The answer exceeds the {field.max_length}-character limit.")
        field.known_answer = text_value
        field.source = "student"
        state.known_fields[field_id] = text_value
        if field.essay:
            draft = state.drafted_answers.get(field_id)
            if draft:
                draft.user_approved = user_approved
            if user_approved and field_id not in state.user_approved_answers:
                state.user_approved_answers.append(field_id)
        state.missing_fields = [
            item.field_id
            for item in state.fields
            if item.required and item.known_answer in (None, "")
        ]
        state.pending_background_field = next(
            (item.field_id for item in state.fields if item.field_id in BACKGROUND_FIELDS and item.field_id in state.missing_fields),
            None,
        )
        with self._lock:
            self.applications[application_id] = state
        return state

    def save_draft(
        self,
        application_id: str,
        field_id: str,
        source_notes: str,
        draft_text: str,
    ) -> DraftAnswer:
        if not source_notes.strip():
            raise ValueError("Student-provided notes are required before drafting a statement.")
        state = self.get_application(application_id)
        field = next((item for item in state.fields if item.field_id == field_id and item.essay), None)
        if field is None:
            raise ValueError("That application field is not a personal-statement field.")
        if field.max_length and len(draft_text) > field.max_length:
            raise ValueError(f"The draft exceeds the {field.max_length}-character limit.")
        notes_folded = source_notes.casefold()
        draft_folded = draft_text.casefold()
        unsupported_claim_patterns = [
            r"\bseeing\b",
            r"\bgain(?:ed|ing)? confidence\b",
            r"\b(?:deepened|strengthened|inspired)\b",
            r"\bappreciation\b",
            r"\b(?:felt|feel|feels|feeling)\b",
            r"\b(?:learned|realized|discovered)\b",
            r"\b(?:impact|difference|rewarding|passion)\b",
        ]
        for pattern in unsupported_claim_patterns:
            for claim in re.findall(pattern, draft_folded):
                claim_text = claim if isinstance(claim, str) else " ".join(claim)
                if claim_text and claim_text not in notes_folded:
                    raise ValueError(
                        "The draft adds an unsupported personal impact, emotion, or outcome. "
                        "Rewrite using only the student's concrete source notes."
                    )
        unsupported_numbers = set(re.findall(r"\b\d+\b", draft_text)) - set(
            re.findall(r"\b\d+\b", source_notes)
        )
        if unsupported_numbers:
            raise ValueError("The draft adds a number or date that is not in the student's source notes.")
        draft = DraftAnswer(
            field_id=field_id,
            source_notes=source_notes.strip(),
            draft_text=draft_text.strip(),
            character_count=len(draft_text.strip()),
            max_length=field.max_length,
        )
        state.drafted_answers[field_id] = draft
        field.known_answer = draft.draft_text
        state.known_fields[field_id] = draft.draft_text
        state.missing_fields = [item for item in state.missing_fields if item != field_id]
        with self._lock:
            self.applications[application_id] = state
        return draft

    def prepare_preview(self, application_id: str) -> ApplicationPreview:
        state = self.get_application(application_id)
        missing = [
            field.field_id
            for field in state.fields
            if field.required and field.known_answer in (None, "")
        ]
        warnings: list[str] = []
        for field in state.fields:
            if field.essay and field.known_answer and field.field_id not in state.user_approved_answers:
                warnings.append(f"{field.label} has not been explicitly reviewed and approved.")
        if state.inspection_status != "official_form":
            warnings.append("Application fields were inferred from official award criteria; review the official application before submission.")
        state.missing_fields = missing
        state.validation_errors = missing + warnings
        state.ready_for_review = not missing and not any("not been explicitly" in warning for warning in warnings)
        with self._lock:
            self.applications[application_id] = state
        return ApplicationPreview(
            application_id=application_id,
            ready=state.ready_for_review,
            completed_fields=sum(field.known_answer not in (None, "") for field in state.fields),
            missing_required_fields=missing,
            warnings=warnings,
            answers=[{"field_id": field.field_id, "label": field.label, "answer": field.known_answer} for field in state.fields if field.known_answer not in (None, "")],
        )

    def approve_and_submit(self, application_id: str, explicit_action: str) -> ScholarshipApplicationState:
        if explicit_action != "APPROVE_AND_SUBMIT":
            raise ValueError("Use the explicit Approve & Submit control to authorize submission.")
        state = self.get_application(application_id)
        preview = self.prepare_preview(application_id)
        if not preview.ready:
            raise ValueError("The application is not ready for submission review.")
        state.approved_for_submission = True
        scholarship = self.discovery.inspect(state.scholarship_id)
        if scholarship.is_demo:
            state.submitted = True
            state.submission_status = "demo_submission_recorded_no_external_action"
        else:
            state.submitted = False
            state.submission_status = "approved_manual_official_submission_required"
        with self._lock:
            self.applications[application_id] = state
        return state

    def submit_from_agent(self, application_id: str) -> dict[str, Any]:
        state = self.get_application(application_id)
        if not state.approved_for_submission:
            return {
                "submitted": False,
                "status": "explicit_ui_approval_required",
                "message": "The student must use the Approve & Submit control after reviewing the application.",
            }
        return {
            "submitted": state.submitted,
            "status": state.submission_status,
            "message": "Submission state was determined by the explicit user approval workflow.",
        }

    def _pending_background_field(self) -> str | None:
        with self._lock:
            for application in self.applications.values():
                if application.pending_background_field:
                    return application.pending_background_field
        return None

    @staticmethod
    def _normalise_background_value(field: str, value: Any) -> Any:
        if field in BOOLEAN_BACKGROUND_FIELDS:
            if isinstance(value, bool):
                return value
            lowered = str(value).strip().casefold()
            if lowered in {"yes", "true", "1"}:
                return True
            if lowered in {"no", "false", "0"}:
                return False
            raise ValueError(f"{field} must be answered yes or no.")
        if field in LIST_BACKGROUND_FIELDS:
            values = value if isinstance(value, list) else [value]
            return [str(item).strip() for item in values if str(item).strip()]
        if field == "co_op_terms_completed":
            if isinstance(value, bool) or not str(value).strip().isdigit():
                raise ValueError("co_op_terms_completed must be a non-negative whole number.")
            return int(value)
        text = str(value).strip()
        if not text:
            raise ValueError("The confirmed background answer cannot be empty.")
        return text

    @staticmethod
    def _known_answer_for_field(
        field: ApplicationField,
        academic_known: dict[str, Any],
        background: StudentBackgroundProfile,
    ) -> Any:
        key = field.field_id.casefold()
        label = field.label.casefold()
        mapping = {
            "name": academic_known["name"],
            "major": academic_known["major"],
            "minor": academic_known["minor"],
            "gpa": academic_known["cumulative_gpa"],
            "credit": academic_known["completed_credits"],
        }
        for term, value in mapping.items():
            if term in key or term in label:
                return value
        background_data = _model_dump(background)
        if field.field_id in background_data:
            return background_data[field.field_id]
        return None

    @staticmethod
    def _apply_background_to_application(
        state: ScholarshipApplicationState, field: str, value: Any
    ) -> ScholarshipApplicationState:
        for application_field in state.fields:
            if application_field.field_id == field:
                application_field.known_answer = value
                application_field.source = "student"
                state.known_fields[field] = value
        state.missing_fields = [
            item.field_id
            for item in state.fields
            if item.required and item.known_answer in (None, "")
        ]
        state.pending_background_field = next(
            (item.field_id for item in state.fields if item.field_id in BACKGROUND_FIELDS and item.field_id in state.missing_fields),
            None,
        )
        return state
