"""Deterministic scholarship matching, background, and application session state."""

from __future__ import annotations

import re
from threading import Lock
from urllib.parse import urlencode
from typing import Any
from uuid import uuid4

from backend.models import AcademicSnapshot
from backend.scholarship_models import (
    ApplicationField,
    ApplicationPreview,
    ApplicationEmailDraft,
    DraftAnswer,
    ScholarshipApplicationState,
    ScholarshipMatch,
    ScholarshipCriterionStatus,
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
    "athletics",
    "field_specific_involvement",
    "personal_story_notes",
    "other_awards",
    "faculty_confirmations",
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


YEAR_WORDS = {1: "first", 2: "second", 3: "third", 4: "fourth"}


def _ordinal_word(year: int) -> str:
    return YEAR_WORDS.get(year, f"year {year}")


def _year_numbers(labels: list[str]) -> set[int]:
    numbers: set[int] = set()
    for label in labels:
        folded = label.casefold()
        for year, word in YEAR_WORDS.items():
            if re.search(rf"\b(?:{year}(?:st|nd|rd|th)|{word})\b", folded):
                numbers.add(year)
    return numbers


def _faculty_matches(student_faculty: str, published_faculty: str) -> bool:
    aliases = {
        "smcs": "science",
        "school of mathematical and computational sciences": "science",
        "faculty of science": "science",
    }
    student_key = re.sub(r"\s+", " ", student_faculty.strip().casefold())
    published_key = re.sub(r"\s+", " ", published_faculty.strip().casefold())
    student = aliases.get(student_key, student_key)
    published = aliases.get(published_key, published_key)
    return bool(student and (student in published or published in student))


class ScholarshipSession:
    def __init__(self, discovery: ScholarshipDiscoveryService | None = None) -> None:
        self.discovery = discovery or ScholarshipDiscoveryService()
        self.background = StudentBackgroundProfile()
        self.matches: list[ScholarshipMatch] = []
        self.applications: dict[str, ScholarshipApplicationState] = {}
        self.pending_question: dict[str, Any] | None = None
        self.discovery_questions_asked = 0
        self.discovery_question_limit = 5
        self._lock = Lock()

    def clear_student_state(self) -> None:
        with self._lock:
            self.background = StudentBackgroundProfile()
            self.matches = []
            self.applications = {}
            self.pending_question = None
            self.discovery_questions_asked = 0
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

    @staticmethod
    def _extract_personal_criteria(scholarship: ScholarshipRecord) -> list[dict[str, Any]]:
        """Normalize only explicit, student-supplied criteria from official award text."""
        patterns = (
            ("financial_need", r"financial need", "Does financial need apply to your situation?", "boolean"),
            ("international_student", r"international student", "Are you an international student?", "boolean"),
            ("citizenship_status", r"canadian citizen|permanent resident|citizenship", "What is your citizenship or residency status?", "text"),
            ("province_or_region", r"pei resident|prince edward island resident|resident of", "Are you a PEI resident?", "boolean"),
            ("pei_high_school_graduate", r"(?:pei|prince edward island) high school", "Did you graduate from a Prince Edward Island high school?", "boolean"),
            ("gender_identity_criterion", r"\b(?:woman|women|female)\b", "This award is restricted to female students. Does that apply to you?", "boolean"),
            ("indigenous_identity", r"indigenous|mi['’]?kmaq|first nations|inuit|m[eé]tis", "Does the Indigenous identity criterion apply to you?", "boolean"),
            ("disability_status", r"disabilit(?:y|ies)", "Does the disability criterion apply to you?", "boolean"),
            ("community_involvement", r"community involvement|volunteer(?:ing| work)?", "Have you done volunteer or community work?", "boolean"),
            ("leadership", r"\bleadership\b", "Do you have leadership experience?", "boolean"),
            ("clubs", r"\bclubs?|extracurricular", "Have you participated in clubs or extracurricular activities?", "boolean"),
            ("employment", r"employment|work experience|workplace", "Do you have relevant work experience?", "boolean"),
            ("career_goals", r"career goals?|career interest", "Do you have career goals related to this award?", "boolean"),
            ("athletics", r"athlet(?:e|ic|ics)|varsity|sport", "Have you participated in athletics or varsity sport?", "boolean"),
            ("family_alumni_relationship", r"alumni relationship|child of an alumn|family.*alumn", "Does an alumni or family relationship criterion apply to you?", "boolean"),
            ("school_or_community_affiliation", r"community affiliation|school affiliation|from the community of", "Does the named school or community affiliation apply to you?", "boolean"),
            ("academic_interests", r"academic interest|interest in", "Do you have the academic interest named by this award?", "boolean"),
            ("field_specific_involvement", r"demonstrated involvement in|participation in (?:community|research|music|athletics|sport)", "Have you participated in the named field-specific activity?", "boolean"),
        )
        criteria: list[dict[str, Any]] = []
        for sentence in re.split(r"(?<=[.!?])\s+", scholarship.description or ""):
            lowered = sentence.casefold()
            if not lowered:
                continue
            preference = bool(re.search(r"preference|consideration|desirable", lowered))
            required = not preference and bool(re.search(r"must|required|restricted|available to|awarded to|open to", lowered))
            for key, pattern, question, answer_type in patterns:
                if re.search(pattern, lowered, re.I):
                    criterion_required = required or (key == "financial_need" and bool(scholarship.financial_need_required))
                    criteria.append({
                        "key": key,
                        "required": criterion_required,
                        "preference": preference,
                        "published_text": sentence.strip(),
                        "source_url": scholarship.source_url,
                        "question": question,
                        "expected_answer_type": answer_type,
                    })
        return criteria

    @staticmethod
    def _criterion_key(text: str) -> str:
        lowered = text.casefold()
        mappings = (
            ("faculty", "faculty_match"),
            ("financial need", "financial_need"),
            ("citizenship", "citizenship_status"),
            ("residency", "citizenship_status"),
            ("international student", "international_student"),
            ("women/female", "gender_identity_criterion"),
            ("female student", "gender_identity_criterion"),
            ("indigenous", "indigenous_identity"),
            ("disability", "disability_status"),
            ("pei high-school", "pei_high_school_graduate"),
            ("pei high school", "pei_high_school_graduate"),
            ("co-op", "co_op_terms_completed"),
            ("personal statement", "personal_statement"),
            ("reference", "reference"),
            ("year of study", "year_of_study"),
            ("historical admission", "historical_admission"),
            ("completed-year percentage", "completed_year_average"),
        )
        for needle, key in mappings:
            if needle in lowered:
                return key
        slug = re.sub(r"[^a-z0-9]+", "_", lowered).strip("_")
        return slug[:64] or "published_criterion"

    def _criteria_for_match(
        self,
        scholarship: ScholarshipRecord,
        missing: list[str],
        known_matches: list[str],
        conflicts: list[str],
    ) -> list[ScholarshipCriterionStatus]:
        """Create the one structured criterion representation used by cards and questions."""
        extracted = {
            item["key"]: item for item in self._extract_personal_criteria(scholarship)
        }
        question_defaults: dict[str, tuple[str, str, str]] = {
            "faculty_match": (
                "Should I treat your connected faculty or school as satisfying this published faculty wording?",
                "boolean",
                "faculty_confirmations",
            ),
            "financial_need": ("Does financial need apply to your situation?", "boolean", "financial_need"),
            "citizenship_status": ("What is your citizenship or residency status?", "text", "citizenship_status"),
            "international_student": ("Are you an international student?", "boolean", "international_student"),
            "gender_identity_criterion": ("This award is restricted to female students. Does that apply to you?", "boolean", "gender_identity_criterion"),
            "indigenous_identity": ("Does the Indigenous identity criterion apply to you?", "boolean", "indigenous_identity"),
            "disability_status": ("Does the disability criterion apply to you?", "boolean", "disability_status"),
            "pei_high_school_graduate": ("Did you graduate from a Prince Edward Island high school?", "boolean", "pei_high_school_graduate"),
            "co_op_terms_completed": ("How many co-op work terms have you completed?", "number", "co_op_terms_completed"),
        }

        criteria: list[ScholarshipCriterionStatus] = []
        for status, items in (
            ("unknown", missing),
            ("matched", known_matches),
            ("conflict", conflicts),
        ):
            for text in items:
                metadata = next(
                    (
                        item
                        for item in extracted.values()
                        if item.get("published_text", "").casefold() == text.casefold()
                    ),
                    {},
                )
                key = metadata.get("key") or self._criterion_key(text)
                preference = bool(metadata.get("preference")) or "preference" in text.casefold()
                required = bool(metadata.get("required", status != "matched")) and not preference
                default = question_defaults.get(key)
                criteria.append(
                    ScholarshipCriterionStatus(
                        key=key,
                        status=(
                            "preference_not_met"
                            if status == "unknown"
                            and preference
                            and "does not appear to apply" in text.casefold()
                            else status
                        ),
                        required=required,
                        preference=preference,
                        published_text=text,
                        source_url=scholarship.source_url,
                        expected_answer_type=(metadata.get("expected_answer_type") or (default[1] if default else "derived")),
                        question=(metadata.get("question") or (default[0] if default else None)) if status == "unknown" else None,
                        user_field=(default[2] if default else (key if key in BACKGROUND_FIELDS else None)) if status == "unknown" else None,
                    )
                )
        return criteria

    def next_profile_question(self) -> dict[str, Any] | None:
        """Choose the unresolved official criterion that improves the most promising matches."""
        with self._lock:
            if self.pending_question:
                return dict(self.pending_question)
            matches = list(self.matches)
            asked = self.discovery_questions_asked
        if asked >= self.discovery_question_limit:
            return None
        candidates: dict[str, dict[str, Any]] = {}
        for match in matches:
            if match.match_level not in {"potential", "strong"}:
                continue
            for structured in match.criteria:
                criterion = _model_dump(structured)
                key = criterion["key"]
                if (
                    criterion["status"] != "unknown"
                    or not criterion.get("question")
                    or not criterion.get("user_field")
                ):
                    continue
                item = candidates.setdefault(key, {**criterion, "matches": []})
                item["matches"].append(match)
                item["required"] = item["required"] or criterion["required"]
        if not candidates:
            return None
        candidate = max(candidates.values(), key=lambda item: (item["required"], len(item["matches"]), max(match.scholarship.amount or 0 for match in item["matches"])))
        field = candidate["user_field"]
        affected = candidate["matches"]
        choices = ["Yes", "No", "Prefer not to say"] if candidate["expected_answer_type"] == "boolean" else []
        pending = {
            "field": field,
            "criterion_key": candidate["key"],
            "criterion_label": candidate["key"].replace("_", " "),
            "scholarship_ids": [item.scholarship_id for item in affected],
            "official_requirement_text": candidate["published_text"],
            "source_url": candidate["source_url"],
            "required": candidate["required"],
            "preference": candidate["preference"],
            "expected_answer_type": candidate["expected_answer_type"],
            "allowed_values": choices,
            "question": candidate["question"],
        }
        with self._lock:
            self.pending_question = pending
            self.discovery_questions_asked += 1
        return dict(pending)

    def continue_discovery_interview(self) -> dict[str, Any] | None:
        with self._lock:
            self.discovery_questions_asked = 0
        return self.next_profile_question()

    def resolve_pending_question(self, message: str, snapshot: AcademicSnapshot) -> dict[str, Any] | None:
        with self._lock:
            pending = dict(self.pending_question) if self.pending_question else None
        if not pending:
            return None
        lowered = message.strip().casefold()
        field = pending["field"]
        if field == "gender_identity_criterion" and re.search(r"which|what.*gender|specific gender", lowered):
            return {"resolved": False, "message": "The award specifies female students.", "pending_question": pending}
        if field == "financial_need" and re.search(r"what.*financial need|what.*mean", lowered):
            return {"resolved": False, "message": "Here, financial need means the award requires you to confirm that financial circumstances make funding support relevant.", "pending_question": pending}
        if field == "pei_high_school_graduate" and re.search(r"what.*count|what.*mean", lowered):
            return {"resolved": False, "message": pending["official_requirement_text"], "pending_question": pending}
        if re.search(r"^why\??$|why (?:do|does)|what does that mean", lowered):
            count = len(pending["scholarship_ids"])
            return {"resolved": False, "message": f"{count} of your current scholarship matches list this as an eligibility criterion: {pending['official_requirement_text']}", "pending_question": pending}
        value: bool | None = None
        if pending.get("expected_answer_type") == "text" and lowered:
            saved = self.save_background_answer(field, message.strip(), confirmed=True)
            with self._lock:
                self.pending_question = None
            cached_search = getattr(self.discovery, "cached_search", None)
            search = cached_search() if callable(cached_search) else None
            matches, transitions = self.rank_with_transitions(search, snapshot) if search else ([], [])
            next_question = self.next_profile_question()
            response = next_question["question"] if next_question else self._interview_status_message(matches, transitions)
            return {"resolved": True, "message": response, "saved": saved, "matches": [_model_dump(item) for item in matches], "transitions": transitions, "pending_question": next_question}
        if pending.get("expected_answer_type") == "number" and re.fullmatch(r"\d+", lowered):
            saved = self.save_background_answer(field, int(lowered), confirmed=True)
            with self._lock:
                self.pending_question = None
            cached_search = getattr(self.discovery, "cached_search", None)
            search = cached_search() if callable(cached_search) else None
            matches, transitions = self.rank_with_transitions(search, snapshot) if search else ([], [])
            next_question = self.next_profile_question()
            response = next_question["question"] if next_question else self._interview_status_message(matches, transitions)
            return {"resolved": True, "message": response, "saved": saved, "matches": [_model_dump(item) for item in matches], "transitions": transitions, "pending_question": next_question}
        if re.fullmatch(r"(?:yes|y|true)", lowered):
            value = True
        elif re.fullmatch(r"(?:no|n|false)", lowered):
            value = False
        elif field == "gender_identity_criterion":
            if re.search(r"\b(?:male|man)\b", lowered):
                value = False
            elif re.search(r"\b(?:female|woman)\b", lowered):
                value = True
        if value is None:
            return None
        value_to_save: Any = value
        if field == "province_or_region":
            value_to_save = "Prince Edward Island" if value else "Not Prince Edward Island"
        elif field in LIST_BACKGROUND_FIELDS:
            if field == "faculty_confirmations":
                value_to_save = list(pending["scholarship_ids"]) if value else [f"rejected:{item}" for item in pending["scholarship_ids"]]
            else:
                value_to_save = ["Confirmed" if value else "Not applicable"]
        elif field in {"employment", "career_goals", "family_alumni_relationship", "school_or_community_affiliation", "academic_interests"}:
            value_to_save = "Confirmed" if value else "Not applicable"
        saved = self.save_background_answer(field, value_to_save, confirmed=True)
        with self._lock:
            self.pending_question = None
        cached_search = getattr(self.discovery, "cached_search", None)
        search = cached_search() if callable(cached_search) else None
        if search is None:
            with self._lock:
                cached_matches = list(self.matches)
            if cached_matches:
                search = ScholarshipSearchResult(
                    scholarships=[item.scholarship for item in cached_matches],
                    source_mode="cached",
                    sources=[],
                )
        matches, transitions = self.rank_with_transitions(search, snapshot) if search else ([], [])
        next_question = self.next_profile_question()
        if next_question:
            response = next_question["question"]
        else:
            response = self._interview_status_message(matches, transitions)
        return {"resolved": True, "message": response, "saved": saved, "matches": [_model_dump(item) for item in matches], "transitions": transitions, "pending_question": next_question}

    def rank_with_transitions(
        self, search: ScholarshipSearchResult, snapshot: AcademicSnapshot
    ) -> tuple[list[ScholarshipMatch], list[dict[str, str]]]:
        with self._lock:
            previous = {item.scholarship_id: item.match_level for item in self.matches}
        matches = self.rank(search, snapshot)
        transitions = [
            {
                "scholarship_id": item.scholarship_id,
                "previous_level": previous[item.scholarship_id],
                "new_level": item.match_level,
            }
            for item in matches
            if item.scholarship_id in previous and previous[item.scholarship_id] != item.match_level
        ]
        return matches, transitions

    @staticmethod
    def _unresolved_count(matches: list[ScholarshipMatch]) -> int:
        return sum(
            criterion.status in {"unknown", "preference_not_met"}
            for match in matches
            for criterion in match.criteria
        )

    def _interview_status_message(
        self, matches: list[ScholarshipMatch], transitions: list[dict[str, str]]
    ) -> str:
        remaining = self._unresolved_count(matches)
        if transitions:
            labels = {"excellent": "Excellent Match", "strong": "Strong Match", "potential": "Potential Fit", "unlikely": "Unlikely Fit"}
            by_id = {match.scholarship_id: match for match in matches}
            first = transitions[0]
            name = by_id[first["scholarship_id"]].scholarship.name
            response = f"{name} moved from {labels[first['previous_level']]} to {labels[first['new_level']]} after reranking."
            if remaining:
                noun = "detail" if remaining == 1 else "details"
                response += f" {remaining} additional eligibility {noun} remain."
            return response
        if remaining:
            noun = "detail" if remaining == 1 else "details"
            return f"I've resolved the highest-impact questions. {remaining} additional eligibility {noun} remain."
        return "All currently identified eligibility criteria have been resolved and the matches were reranked."

    def get_missing_information(self) -> list[dict[str, Any]]:
        """Return deterministic unresolved criteria from the current ranked objects."""
        with self._lock:
            matches = list(self.matches)
        return [
            {
                "scholarship_id": match.scholarship_id,
                "name": match.scholarship.name,
                "match_level": match.match_level,
                "unresolved_required": [
                    _model_dump(item)
                    for item in match.criteria
                    if item.status == "unknown" and item.required
                ],
                "unresolved_preferences": [
                    _model_dump(item)
                    for item in match.criteria
                    if item.status in {"unknown", "preference_not_met"} and item.preference
                ],
            }
            for match in matches
            if any(item.status in {"unknown", "preference_not_met"} for item in match.criteria)
        ]

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
        latest_average = next(
            (
                year.weighted_average
                for year in reversed(snapshot.scholarship_summary.years)
                if year.calculation_status == "calculated"
                and year.weighted_average is not None
            ),
            None,
        )
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
            "student_profile_used": {
                "faculty": student.faculty,
                "major": student.majors[0] if student.majors else None,
                "year_of_study": student.year_of_study,
                "completed_credits": student.completed_credits,
                "required_degree_credits": student.required_degree_credits,
                "cumulative_gpa": student.cumulative_gpa,
                "latest_calculated_average": latest_average,
                "confirmed_background": {
                    key: value
                    for key, value in self.get_background().items()
                    if value not in (None, [], "")
                },
            },
            "next_profile_question": self.next_profile_question(),
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
                    known_matches.append(
                        f"{', '.join(sorted(overlap)).title()} major or minor matches the published program requirement."
                    )
                else:
                    conflicts.append("The listed program requirement does not match the connected major or minor.")
            if scholarship.faculty:
                faculty_terms = {faculty.casefold() for faculty in scholarship.faculty}
                is_open_faculty = any("all facult" in term for term in faculty_terms)
                if is_open_faculty:
                    known_matches.append("The award is listed for all faculties.")
                elif any(
                    _faculty_matches(student_faculty, term)
                    for term in faculty_terms
                    if student_faculty
                ):
                    known_matches.append(
                        f"{snapshot.student.faculty} faculty or school matches the published requirement."
                    )
                elif scholarship.id in background.faculty_confirmations:
                    known_matches.append(
                        "Student explicitly confirmed that the connected school satisfies the published faculty wording."
                    )
                elif f"rejected:{scholarship.id}" in background.faculty_confirmations:
                    conflicts.append(
                        "Student reported that the connected school does not satisfy the published faculty wording."
                    )
                else:
                    missing.append("The published faculty wording needs confirmation against the connected school.")
                    eligibility_unknown = True
            elif not scholarship.major:
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
                    year_text = " ".join(scholarship.year_of_study).casefold()
                    explicit_years = _year_numbers(scholarship.year_of_study)
                    if "entering" in year_text:
                        historical = bool(re.search(r"upon entering|at the time of admission|entered upei directly|admitted from", scholarship.description, re.I))
                        if explicit_years and not historical and student_year not in explicit_years:
                            required = " or ".join(f"{_ordinal_word(year)} year" for year in sorted(explicit_years))
                            conflicts.append(
                                f"Published eligibility is for students entering {required}; your connected record shows {_ordinal_word(student_year)}-year standing."
                            )
                        elif explicit_years and not historical:
                            known_matches.append(
                                f"Calculated {_ordinal_word(student_year)}-year standing matches the published entering-year requirement."
                            )
                        else:
                            missing.append("The award uses historical admission wording that needs confirmation from the student.")
                            eligibility_unknown = True
                    elif re.search(r"\bupper[- ]year\b", year_text):
                        if student_year >= 2:
                            known_matches.append(
                                f"Calculated {_ordinal_word(student_year)}-year standing satisfies the published upper-year requirement."
                            )
                        else:
                            conflicts.append(
                                "The award is restricted to upper-year students; calculated standing is first year."
                            )
                    elif student_year in explicit_years:
                        known_matches.append(
                            f"Calculated {_ordinal_word(student_year)}-year standing matches the published year requirement."
                        )
                    else:
                        required = " or ".join(
                            f"{_ordinal_word(year)} year" for year in sorted(explicit_years)
                        ) or "a different year of study"
                        conflicts.append(
                            f"The award is restricted to {required}; calculated standing is {_ordinal_word(student_year)} year."
                        )

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

            handled_criteria = {"financial_need", "gender_identity_criterion", "pei_high_school_graduate", "indigenous_identity", "disability_status"}
            for criterion in self._extract_personal_criteria(scholarship):
                key = criterion["key"]
                if key in handled_criteria:
                    continue
                value = getattr(background, key, None)
                if value in (None, "", []):
                    missing.append(criterion["published_text"])
                    eligibility_unknown = eligibility_unknown or criterion["required"]
                elif criterion["required"] and (isinstance(value, bool) and not value or value == ["Not applicable"] or value == "Not applicable"):
                    conflicts.append(criterion["published_text"])
                else:
                    known_matches.append(f"Student-confirmed {key.replace('_', ' ')} matches the published criterion.")

            if scholarship.personal_statement_required:
                missing.append("A reviewed personal statement is required for the application.")
            if scholarship.reference_required:
                missing.append("A reference is required for the application.")

            if conflicts:
                level = "unlikely"
            elif eligibility_unknown:
                level = "potential"
            elif known_matches:
                level = "excellent"
            else:
                level = "strong"
            known_count = len(known_matches) + len(conflicts)
            total_count = known_count + sum(
                "required for the application" not in item for item in missing
            )
            confidence = round(min(0.98, max(0.2, known_count / max(1, total_count))), 2)
            criteria = self._criteria_for_match(
                scholarship, missing, known_matches, conflicts
            )
            results.append(
                ScholarshipMatch(
                    scholarship_id=scholarship.id,
                    scholarship=scholarship,
                    match_level=level,
                    confidence=confidence,
                    known_matches=[item.published_text for item in criteria if item.status == "matched"],
                    missing_information=[item.published_text for item in criteria if item.status in {"unknown", "preference_not_met"}],
                    known_conflicts=[item.published_text for item in criteria if item.status == "conflict"],
                    criteria=criteria,
                )
            )

        order = {
            "excellent": 0,
            "strong": 1,
            "potential": 2,
            "unlikely": 3,
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
            "match_level": "potential",
            "confidence": 0.2,
            "known_matches": [],
            "missing_information": ["Run scholarship matching against the connected profile."],
            "known_conflicts": [],
        }

    def open_application(
        self, scholarship_id: str, snapshot: AcademicSnapshot
    ) -> ScholarshipApplicationState:
        scholarship = self.discovery.inspect(scholarship_id)
        if scholarship.detail_status == "source_only":
            inspection_status, raw_fields = "unavailable", []
        else:
            inspection_status, raw_fields = self.discovery.inspect_application_fields(scholarship)
        academic_known = {
            "name": snapshot.student.full_name,
            "major": ", ".join(snapshot.student.majors),
            "minor": ", ".join(snapshot.student.minors),
            "cumulative_gpa": snapshot.student.cumulative_gpa,
            "completed_credits": snapshot.student.completed_credits,
            "year_of_study": snapshot.student.year_of_study,
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
        next_missing = next(
            (field for field in fields if field.required and field.known_answer in (None, "")),
            None,
        )
        if scholarship.submission_method == "email":
            next_action = "guided_application"
            destination_url = None
            status_message = "Your email application workspace is ready. Review the draft before opening your mail client."
        elif fields and inspection_status in {"official_form", "criteria_based_preview"}:
            next_action = "guided_application"
            destination_url = None
            status_message = "Application started. Review the known fields and complete one missing detail at a time."
        elif scholarship.application_url:
            next_action = "open_official_application"
            destination_url = scholarship.application_url
            status_message = "The official application is open. I can help you answer its questions."
        elif scholarship.source_url:
            next_action = "open_official_scholarship"
            destination_url = scholarship.source_url
            status_message = "Open the official scholarship page to continue. I can help you answer its questions."
        else:
            next_action = "unavailable"
            destination_url = None
            status_message = "The official application link wasn't available for this award."
        state = ScholarshipApplicationState(
            application_id=uuid4().hex,
            scholarship_id=scholarship.id,
            scholarship_name=scholarship.name,
            application_url=scholarship.application_url,
            submission_method=scholarship.submission_method,
            submission_email=scholarship.submission_email,
            required_documents=scholarship.required_documents,
            deadline_display=scholarship.next_deadline_display or scholarship.deadline_display or "Not found",
            application_status=scholarship.application_status,
            inspection_status=inspection_status,
            next_action=next_action,
            destination_url=destination_url,
            status_message=status_message,
            next_question=next_missing.label if next_missing else None,
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
        state.next_question = next(
            (
                item.label
                for item in state.fields
                if item.required and item.known_answer in (None, "")
            ),
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
        state.next_question = next(
            (
                item.label
                for item in state.fields
                if item.required and item.known_answer in (None, "")
            ),
            None,
        )
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
        if state.next_action != "guided_application":
            warnings.append(
                "Official application fields were not machine-accessible; complete and review the official page."
            )
        state.missing_fields = missing
        state.validation_errors = missing + warnings
        state.ready_for_review = (
            state.next_action == "guided_application"
            and not missing
            and not any("not been explicitly" in warning for warning in warnings)
        )
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

    def prepare_application_email(self, application_id: str) -> ApplicationEmailDraft:
        state = self.get_application(application_id)
        preview = self.prepare_preview(application_id)
        missing = list(preview.missing_required_fields)
        if not state.submission_email:
            missing.append("Official submission email was not found.")
        ready = preview.ready and state.submission_method == "email" and bool(state.submission_email)
        attachments = list(state.required_documents)
        attachments.extend(
            field.label
            for field in state.fields
            if field.required and field.type == "file" and field.label not in attachments
        )
        full_name = str(state.known_fields.get("name") or "Student")
        subject = f"Application — {state.scholarship_name} — {full_name}"
        body = (
            "Hello,\n\n"
            f"Please find attached my application for the {state.scholarship_name}.\n\n"
            "I have included the required application materials for consideration.\n\n"
            "Thank you for your time.\n\n"
            f"Kind regards,\n{full_name}"
        )
        params = urlencode({"subject": subject, "body": body})
        mailto_url = f"mailto:{state.submission_email}?{params}" if state.submission_email else None
        return ApplicationEmailDraft(
            application_id=application_id,
            to=state.submission_email,
            subject=subject,
            body=body,
            attachments_required=attachments,
            scholarship_name=state.scholarship_name,
            deadline=state.deadline_display,
            ready=ready,
            missing_fields=missing,
            mailto_url=mailto_url,
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
            "year": academic_known["year_of_study"],
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
        state.next_question = next(
            (
                item.label
                for item in state.fields
                if item.required and item.known_answer in (None, "")
            ),
            None,
        )
        return state
