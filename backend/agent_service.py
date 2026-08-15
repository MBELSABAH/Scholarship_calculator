"""DeepSeek tool-calling loop and lightweight academic chat history."""

from __future__ import annotations

import json
import logging
import os
import re
import time
import asyncio
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Any, Protocol
from uuid import uuid4

import httpx
from dotenv import load_dotenv

from backend.agent_tools import (
    SCHOLARSHIP_SESSION,
    TOOL_DEFINITIONS,
    TOOL_FUNCTIONS,
    ToolExecutionError,
    current_completed_course_records,
    execute_tool,
)
from backend.models import AcademicSnapshot


PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env", override=False)

DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEEPSEEK_MODEL = "deepseek-v4-flash"
MAX_AGENT_ROUNDS = 6
MAX_TOOL_CALLS_PER_ROUND = 8
MAX_HISTORY_MESSAGES = 12

ACADEMIC_COPILOT_SYSTEM_PROMPT = """You are Academic Copilot, an academic and scholarship assistant.
Use deterministic tools for academic facts and official UPEI web tools for scholarship information.
Every named course, grade, academic year, GPA value, credit count, and subject-performance claim must be supported by a current-request AcademicSnapshot tool result or deterministic state tied to the same snapshot_id. For any question about courses, grades, highest/lowest results, subjects, or when a course was taken, call get_academic_record, get_course_extremes, or get_subject_performance as appropriate; otherwise say you cannot find it in the connected record.
For “Find scholarships I should apply for,” use get_student_summary, search_upei_scholarships, then rank_scholarship_matches in that order. Do not call get_student_background during discovery because ranking already reads the confirmed session profile.
Official UPEI scholarship data, AcademicSnapshot academic facts, and student-confirmed background facts are authoritative.
Never invent scholarships, eligibility criteria, financial circumstances, citizenship, identity, leadership, volunteering, awards, dates, or personal stories.
If a mandatory personal criterion is unknown, say the match is potential, ask exactly one concise question, then stop and wait. Do not list, preview, or mention other unanswered personal questions in that reply.
Use known academic information automatically instead of asking for it again.
For essays, first gather the student's real experience, then draft only from those facts and respect the stated limit. Copy source_notes exactly from a user message; never add inferred emotions, outcomes, motivations, dates, awards, or effects.
Never treat a draft as approved and never submit an application without the explicit Approve & Submit UI action.
For “latest scholarship,” use only latest_acquired_year and latest_acquired_amount; do not conflate them with current-year eligibility.
If current_application_id is present in UI context, continue that application with inspect_application_form; do not open a duplicate application.
When answering deadline questions, use the structured deadline fields from the scholarship tool result. Say “Deadline not found” or direct the student to the official page when precision is unknown; never infer “no deadline.” If sources conflict, state the preferred specific/application deadline and briefly preserve the other source.
After prepare_application_preview, use prepare_application_email when the application's submission_method is email. Present the draft for review; never send it.
When the user asks for help applying and current_application_id is absent, call open_scholarship_application before asking any application question; inspecting a scholarship alone is not enough.
When the user says “Use this answer” for an existing draft, inspect the current application and call save_application_answer with the exact draft_text and user_approved=true. Do not draft again.
Do not claim an official university determination.
Never request or reveal passwords, portal cookies, login credentials, or API keys.

Answer directly and briefly in normal chat:
- Prefer one to three short sentences. Use short bullets only when they make the answer clearer.
- If one sentence is enough, give one sentence.
- Do not use emojis, congratulations, motivational filler, or repeat the question.
- Do not add an introduction such as “Here’s what I found.”
- Do not add a conclusion such as “Let me know if you need anything else.”
- Do not speculate beyond tool results.
- Use Markdown sparingly. Bold only the most important value when useful. Never use a Markdown table unless the user specifically requests one.
Essay and personal-statement drafting is exempt from the short-answer limit. When the user requests longer writing or a word count, provide the requested length while following the factual drafting safeguards above."""

SCHOLARSHIP_AGENT_SYSTEM_PROMPT = """For scholarship discovery and matching responses:
- Keep ranked results compact and grounded only in scholarship tool results.
- For scholarship discovery, show at most the top three matches with one short line each; the dashboard already shows the full ranked list. Do not restate the student's profile.
- For “Why am I a match?”, use exactly the heading “Strong match because:” followed by at most four short bullets covering confirmed matches, missing information, and conflicts. Do not repeat the award title, amount, criteria paragraph, or source URL, and add no prose before or after the bullets.
- Never fabricate criteria or a detail page when extraction is unavailable. Say that some details are available only on the official UPEI page and provide the preserved official source.
- Distinguish a source-only scholarship page from a successfully extracted detail record.
- Keep the exact official scholarship source URL available for verification."""

SYSTEM_PROMPT = (
    ACADEMIC_COPILOT_SYSTEM_PROMPT
    + "\n\n"
    + SCHOLARSHIP_AGENT_SYSTEM_PROMPT
)

logger = logging.getLogger(__name__)


class AgentServiceError(RuntimeError):
    """A controlled agent failure safe to expose at the API boundary."""

    def __init__(self, message: str, *, http_status: int = 502) -> None:
        super().__init__(message)
        self.http_status = http_status


class AgentConfigurationError(AgentServiceError):
    def __init__(self, message: str = "DeepSeek is not configured.") -> None:
        super().__init__(message, http_status=503)


class NoAcademicSnapshotError(AgentServiceError):
    def __init__(self) -> None:
        super().__init__("Connect your academic record first.", http_status=409)


class AgentRoundsExceededError(AgentServiceError):
    def __init__(self) -> None:
        super().__init__(
            "The academic assistant could not finish this request. Try a more specific question."
        )


class ModelClient(Protocol):
    async def create_chat_completion(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> dict[str, Any]: ...


class DeepSeekClient:
    """Small HTTP client for DeepSeek's OpenAI-compatible chat endpoint."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str = DEEPSEEK_BASE_URL,
        model: str = DEEPSEEK_MODEL,
        timeout_seconds: float = 30.0,
    ) -> None:
        self._api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_seconds = timeout_seconds

    def _get_api_key(self) -> str:
        api_key = (self._api_key or os.getenv("DEEPSEEK_API_KEY", "")).strip()
        if not api_key:
            raise AgentConfigurationError()
        return api_key

    async def create_chat_completion(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> dict[str, Any]:
        payload = {
            "model": self.model,
            "thinking": {"type": "disabled"},
            "messages": messages,
            "tools": tools,
            "tool_choice": "auto",
        }
        headers = {
            "Authorization": f"Bearer {self._get_api_key()}",
            "Content-Type": "application/json",
        }
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                response = await client.post(
                    f"{self.base_url}/chat/completions", headers=headers, json=payload
                )
        except httpx.TimeoutException as exc:
            raise AgentServiceError(
                "The AI service took too long. Try again.", http_status=504
            ) from exc
        except httpx.HTTPError as exc:
            raise AgentServiceError(
                "The AI service is temporarily unavailable. Try again."
            ) from exc

        logger.info("DeepSeek chat completion returned HTTP %s", response.status_code)
        if response.status_code == 401:
            raise AgentConfigurationError(
                "DeepSeek authentication failed. Check DEEPSEEK_API_KEY."
            )
        if response.status_code == 402:
            raise AgentServiceError(
                "The DeepSeek account has insufficient balance. Add credit and try again."
            )
        if response.status_code == 429:
            raise AgentServiceError(
                "DeepSeek is rate-limited or at its concurrency limit. Try again shortly.",
                http_status=429,
            )
        if response.status_code >= 400:
            raise AgentServiceError(
                f"DeepSeek returned an unexpected HTTP {response.status_code} error."
            )
        try:
            body = response.json()
        except ValueError as exc:
            raise AgentServiceError("DeepSeek returned an unreadable response.") from exc
        if not isinstance(body, dict):
            raise AgentServiceError("DeepSeek returned an unreadable response.")
        return body


class ConversationStore:
    """In-memory user/assistant transcripts; internal tool payloads are not persisted."""

    def __init__(self, max_messages: int = MAX_HISTORY_MESSAGES) -> None:
        self._conversations: dict[str, list[dict[str, str]]] = {}
        self._modes: dict[str, str] = {}
        self._snapshots: dict[str, str] = {}
        self._max_messages = max_messages
        self._lock = Lock()

    def open(self, requested_id: str | None = None, *, mode: str, snapshot_id: str) -> tuple[str, list[dict[str, str]]]:
        with self._lock:
            if requested_id and requested_id in self._conversations and self._modes.get(requested_id) == mode and self._snapshots.get(requested_id) == snapshot_id:
                conversation_id = requested_id
            else:
                conversation_id = uuid4().hex
                self._conversations[conversation_id] = []
                self._modes[conversation_id] = mode
                self._snapshots[conversation_id] = snapshot_id
            return conversation_id, deepcopy(self._conversations[conversation_id])

    def append_turn(self, conversation_id: str, user: str, assistant: str) -> None:
        with self._lock:
            history = self._conversations.setdefault(conversation_id, [])
            history.extend(
                [
                    {"role": "user", "content": user},
                    {"role": "assistant", "content": assistant},
                ]
            )
            self._conversations[conversation_id] = history[-self._max_messages :]

    def clear(self) -> None:
        with self._lock:
            self._conversations.clear()
            self._modes.clear()
            self._snapshots.clear()


@dataclass(frozen=True)
class AgentResult:
    message: str
    conversation_id: str
    tools_used: list[str]
    suggested_replies: list[str]
    sources: list[dict[str, str]]
    ui_updates: list[str]
    pending_question: dict[str, Any] | None = None


def contextual_suggestions(question: str, tools_used: list[str]) -> list[str]:
    """Return two reliable follow-ups without depending on model-generated JSON."""
    lowered = question.casefold()
    tools = set(tools_used)

    if "prepare_application_email" in tools:
        return ["Preview email", "What attachments are needed?"]
    if "prepare_application_preview" in tools:
        return ["Review application", "What is still missing?"]
    if "draft_personal_statement" in tools:
        return ["Rewrite it", "Use this answer"]
    if "open_scholarship_application" in tools or "inspect_application_form" in tools:
        return ["What should I answer next?", "Review the application requirements"]
    if "save_student_background_answer" in tools:
        return ["Continue the application", "What else is missing?"]
    if "inspect_scholarship" in tools:
        return ["Why am I a match?", "Help me apply"]
    if "rank_scholarship_matches" in tools or "search_upei_scholarships" in tools:
        return ["Show my best match", "Which applications need more information?"]
    if "project_gpa" in tools:
        return ["What if each grade were 85?", "How is the projected GPA calculated?"]
    if "get_scholarship_summary" in tools:
        if "best" in lowered or "strong" in lowered:
            return ["Show my yearly averages", "What scholarship did that year earn?"]
        if "average" in lowered or "year" in lowered:
            return ["Which academic year was strongest?", "Why did each amount differ?"]
        return ["Why do I qualify?", "Show my yearly averages"]
    if "get_academic_record" in tools:
        if "five" in lowered or "5" in lowered:
            return ["Which year was strongest?", "How do these grades affect my GPA?"]
        if any(year_word in lowered for year_word in ("2023-", "2024-", "2025-")):
            return ["What was my lowest grade overall?", "Which year was strongest?"]
        if "lowest" in lowered:
            return ["Show my five lowest grades", "Which year was strongest?"]
        return ["What are my lowest grades?", "Compare my academic years"]
    if "get_student_summary" in tools:
        if "credit" in lowered:
            return ["What is my cumulative GPA?", "Which courses count toward my GPA?"]
        return ["How is my GPA calculated?", "What if I get 90 next term?"]
    return ["What scholarship do I qualify for?", "What are my lowest grades?"]


class AgentService:
    def __init__(
        self,
        model_client: ModelClient,
        *,
        conversations: ConversationStore | None = None,
        max_rounds: int = MAX_AGENT_ROUNDS,
    ) -> None:
        self.model_client = model_client
        self.conversations = conversations or ConversationStore()
        self.max_rounds = max_rounds
        self._last_academic_courses: dict[tuple[str, str], list[dict[str, Any]]] = {}

    def clear_student_context(self) -> None:
        """Clear all conversation and entity state when the connected record changes."""
        self.conversations.clear()
        self._last_academic_courses.clear()

    async def chat(
        self,
        message: str,
        snapshot: AcademicSnapshot | None,
        *,
        conversation_id: str | None = None,
        mode: str = "academic",
        ui_context: dict[str, str | None] | None = None,
    ) -> AgentResult:
        if snapshot is None:
            raise NoAcademicSnapshotError()
        question = message.strip()
        if not question:
            raise AgentServiceError("Enter a question for Academic Copilot.", http_status=422)

        active_id, history = self.conversations.open(conversation_id, mode=mode, snapshot_id=snapshot.snapshot_id)
        refers_to_courses = bool(re.search(r"\b(?:which|what) years?\b.*\b(?:those|them|these)\b|\b(?:those|them|these)\b.*\b(?:years?|taken)\b", question, re.I))
        if mode == "academic" and refers_to_courses:
            courses = self._last_academic_courses.get((active_id, snapshot.snapshot_id), [])
            if courses:
                answer = "\n".join(f"{course['code']} — {course['academic_year']}" for course in courses)
                self.conversations.append_turn(active_id, question, answer)
                return AgentResult(message=answer, conversation_id=active_id, tools_used=[], suggested_replies=["Show my lowest courses"], sources=[], ui_updates=[])
        if mode == "academic":
            routed = self._route_academic_fact(question, snapshot, active_id)
            if routed is not None:
                answer, tools_used, suggestions = routed
                self.conversations.append_turn(active_id, question, answer)
                return AgentResult(
                    message=answer,
                    conversation_id=active_id,
                    tools_used=tools_used,
                    suggested_replies=suggestions,
                    sources=[],
                    ui_updates=[],
                )
            # A new unrelated academic request must not retain an old "those" list.
            self._last_academic_courses.pop((active_id, snapshot.snapshot_id), None)
        if mode == "scholarship" and re.search(r"\bcontinue eligibility questions?\b", question, re.I):
            pending = SCHOLARSHIP_SESSION.continue_discovery_interview()
            if pending:
                answer = pending["question"]
            else:
                remaining = sum(
                    len(item["unresolved_required"]) + len(item["unresolved_preferences"])
                    for item in SCHOLARSHIP_SESSION.get_missing_information()
                )
                answer = (
                    f"No additional interview question is available, but {remaining} eligibility detail{'s' if remaining != 1 else ''} remain."
                    if remaining
                    else "All currently identified eligibility criteria have been resolved."
                )
            self.conversations.append_turn(active_id, question, answer)
            return AgentResult(
                message=answer,
                conversation_id=active_id,
                tools_used=[],
                suggested_replies=pending.get("allowed_values", []) if pending else ["Show best match"],
                sources=[],
                ui_updates=[],
                pending_question=pending,
            )
        if mode == "scholarship":
            pending_result = SCHOLARSHIP_SESSION.resolve_pending_question(question, snapshot)
            if pending_result:
                answer = pending_result["message"]
                self.conversations.append_turn(active_id, question, answer)
                return AgentResult(
                    message=answer,
                    conversation_id=active_id,
                    tools_used=[],
                    suggested_replies=(pending_result.get("pending_question") or {}).get("allowed_values", ["Continue eligibility questions"] if pending_result.get("resolved") and SCHOLARSHIP_SESSION.discovery_questions_asked >= SCHOLARSHIP_SESSION.discovery_question_limit else ["Show best match"]),
                    sources=[],
                    ui_updates=["refresh_scholarships"] if pending_result.get("resolved") else [],
                    pending_question=pending_result.get("pending_question"),
                )
            if re.search(r"\b(?:which|what) (?:applications?|scholarships?|awards?) (?:still )?need(?:s)? (?:more )?information\b|\bmissing (?:information|criteria)\b", question, re.I):
                missing = SCHOLARSHIP_SESSION.get_missing_information()
                pending = SCHOLARSHIP_SESSION.emit_next_profile_question()
                if not missing:
                    answer = "No currently ranked scholarship has unresolved eligibility information."
                else:
                    lines: list[str] = []
                    for item in missing:
                        criteria = item["unresolved_required"] + item["unresolved_preferences"]
                        labels = ", ".join(criterion["key"].replace("_", " ") for criterion in criteria)
                        lines.append(f"{item['name']} ({item['match_level'].title()}) — {labels}")
                    answer = "\n".join(lines)
                if pending:
                    answer += f"\n\n{pending['question']}"
                self.conversations.append_turn(active_id, question, answer)
                return AgentResult(
                    message=answer,
                    conversation_id=active_id,
                    tools_used=["get_scholarship_missing_information"],
                    suggested_replies=pending.get("allowed_values", []) if pending else ["Continue eligibility questions"],
                    sources=[],
                    ui_updates=[],
                    pending_question=pending,
                )
            if re.fullmatch(r"(?:i(?:'m| am)? )?in (?:the )?(?:faculty|school)", question.strip(), re.I):
                missing = SCHOLARSHIP_SESSION.get_missing_information()
                unresolved = [
                    criterion
                    for item in missing
                    for criterion in item["unresolved_required"] + item["unresolved_preferences"]
                    if criterion.get("question") and criterion.get("user_field")
                ]
                pending = SCHOLARSHIP_SESSION.emit_next_profile_question() if len(unresolved) == 1 else None
                answer = pending["question"] if pending else "I don't have one unambiguous pending eligibility criterion to attach that answer to. Please choose the scholarship or criterion you mean."
                self.conversations.append_turn(active_id, question, answer)
                return AgentResult(
                    message=answer,
                    conversation_id=active_id,
                    tools_used=[],
                    suggested_replies=pending.get("allowed_values", []) if pending else ["Which applications need more information?"],
                    sources=[],
                    ui_updates=[],
                    pending_question=pending,
                )
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "system", "content": "Conversation mode: scholarship. Keep scholarship workflow context active." if mode == "scholarship" else "Conversation mode: academic. Answer only academic-record questions; do not start scholarship workflows."},
        ]
        if mode == "academic":
            messages.append(
                {
                    "role": "system",
                    "content": (
                        "AUTHORITATIVE CURRENT SNAPSHOT FACTS:\n"
                        + json.dumps(self._academic_fact_block(snapshot), ensure_ascii=False, separators=(",", ":"))
                        + "\nRULE: You may mention only academic facts present in this block. "
                        "Conversation history and prior assistant messages are not factual authority. "
                        "If a number, course, grade, or year is absent, say it cannot be found in the connected record."
                    ),
                }
            )
        if ui_context:
            messages.append(
                {
                    "role": "system",
                    "content": (
                        "Current UI context (navigation context only, not a student fact): "
                        + json.dumps(ui_context, separators=(",", ":"))
                    ),
                }
            )
        messages.extend([*history, {"role": "user", "content": question}])
        tools_used: list[str] = []
        sources: list[dict[str, str]] = []
        run_cache: dict[str, dict[str, Any]] = {}
        scholarship_transitions: list[dict[str, str]] = []
        active_application_id = (
            ui_context.get("current_application_id") if ui_context else None
        )
        logger.info(
            "Academic agent request started (conversation=%s, message_chars=%s)",
            active_id[:8],
            len(question),
        )

        for round_number in range(1, self.max_rounds + 1):
            logger.info("Academic agent round %s", round_number)
            body = await self.model_client.create_chat_completion(messages, TOOL_DEFINITIONS)
            model_message = self._extract_message(body)
            tool_calls = model_message.get("tool_calls") or []

            if tool_calls:
                if round_number >= self.max_rounds:
                    raise AgentRoundsExceededError()
                if not isinstance(tool_calls, list) or len(tool_calls) > MAX_TOOL_CALLS_PER_ROUND:
                    raise AgentServiceError("DeepSeek returned too many tool calls.")
                assistant_message = {
                    "role": "assistant",
                    "content": model_message.get("content"),
                    "tool_calls": tool_calls,
                }
                messages.append(assistant_message)
                for tool_call in tool_calls:
                    tool_id, name, arguments = self._parse_tool_call(tool_call)
                    started = time.monotonic()
                    try:
                        if (
                            mode == "scholarship"
                            and name == "open_scholarship_application"
                            and not self._has_explicit_apply_intent(question)
                        ):
                            raise ToolExecutionError(
                                "Application state can start only after an explicit apply request."
                            )
                        self._validate_draft_source(
                            name,
                            arguments,
                            [
                                item["content"]
                                for item in [*history, {"role": "user", "content": question}]
                                if item.get("role") == "user"
                            ],
                        )
                        cache_key = self._read_cache_key(name, arguments)
                        if cache_key and cache_key in run_cache:
                            result = deepcopy(run_cache[cache_key])
                        else:
                            result = await asyncio.to_thread(
                                execute_tool, name, arguments, snapshot
                            )
                            if cache_key:
                                run_cache[cache_key] = deepcopy(result)
                    except ToolExecutionError as exc:
                        result = {"error": str(exc)}
                    else:
                        if name in TOOL_FUNCTIONS and name not in tools_used:
                            tools_used.append(name)
                        self._collect_sources(result, sources)
                        if name == "rank_scholarship_matches" and isinstance(result.get("transitions"), list):
                            scholarship_transitions = [item for item in result["transitions"] if isinstance(item, dict)]
                        if name in {"get_course_extremes", "get_academic_record"}:
                            courses = list(result.get("courses") or [])
                            if name == "get_academic_record":
                                courses = [
                                    {**course, "academic_year": year["year"]}
                                    for year in result.get("academic_years", [])
                                    for course in year.get("courses", [])
                                ]
                            if courses:
                                self._last_academic_courses[(active_id, snapshot.snapshot_id)] = courses
                        result_application_id = result.get("application_id")
                        if isinstance(result_application_id, str):
                            active_application_id = result_application_id
                    logger.info(
                        "Academic tool %s finished in %.1fms",
                        name,
                        (time.monotonic() - started) * 1000,
                    )
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tool_id,
                            "content": json.dumps(
                                result, ensure_ascii=False, separators=(",", ":")
                            ),
                        }
                    )
                continue

            content = model_message.get("content")
            if not isinstance(content, str) or not content.strip():
                raise AgentServiceError(
                    "DeepSeek returned neither an answer nor a tool request. Try again."
                )
            answer = content.strip()
            if mode == "academic" and not self._academic_answer_is_verified(answer, snapshot):
                answer = "I can't verify that course or grade in your connected academic record."
            if mode == "scholarship" and re.search(
                r"\b(?:now (?:an? )?(?:excellent|strong)|matches? (?:are |were )?updated|you now qualify|this resolves)\b",
                answer,
                re.I,
            ):
                if scholarship_transitions:
                    transition = scholarship_transitions[0]
                    labels = {"excellent": "Excellent Match", "strong": "Strong Match", "potential": "Potential Fit", "unlikely": "Unlikely Fit"}
                    current = next(
                        (item for item in SCHOLARSHIP_SESSION.get_matches() if item["scholarship_id"] == transition.get("scholarship_id")),
                        None,
                    )
                    name = current["scholarship"]["name"] if current else transition.get("scholarship_id", "The scholarship")
                    answer = f"{name} moved from {labels[transition['previous_level']]} to {labels[transition['new_level']]} after the confirmed save and deterministic rerank."
                else:
                    answer = "I have not changed any scholarship rating because no verified backend rating transition occurred."
            pending_question = self._pending_application_question(active_application_id)
            suggestions = contextual_suggestions(question, tools_used)
            if pending_question:
                answer = (
                    "This application needs one confirmed personal detail before I continue: "
                    f"{pending_question['label']}"
                )
                if pending_question["type"] == "boolean":
                    suggestions = ["Yes", "No", "I'm not sure"]
            discovery_question = (
                SCHOLARSHIP_SESSION.emit_next_profile_question()
                if mode == "scholarship"
                and set(tools_used)
                & {
                    "search_upei_scholarships",
                    "rank_scholarship_matches",
                    "get_scholarship_missing_information",
                }
                else None
            )
            if discovery_question and discovery_question["question"] not in answer:
                answer = f"{answer}\n\n{discovery_question['question']}"
            if mode == "scholarship" and not self._has_explicit_apply_intent(question):
                answer = re.sub(
                    r"(?:^|(?<=[.!?])\s+)Open the official scholarship page to continue\.[^\n]*",
                    "",
                    answer,
                    flags=re.I,
                ).strip() or "Scholarship discovery remains active; no application was started."
            self.conversations.append_turn(active_id, question, answer)
            return AgentResult(
                message=answer,
                conversation_id=active_id,
                tools_used=tools_used,
                suggested_replies=suggestions,
                sources=sources,
                ui_updates=self._ui_updates(tools_used),
                pending_question=discovery_question,
            )

        raise AgentRoundsExceededError()

    @staticmethod
    def _academic_fact_block(snapshot: AcademicSnapshot) -> dict[str, Any]:
        return {
            "snapshot_id": snapshot.snapshot_id,
            "student": {
                "faculty": snapshot.student.faculty,
                "majors": list(snapshot.student.majors),
                "minors": list(snapshot.student.minors),
                "year_of_study": snapshot.student.year_of_study,
                "cumulative_gpa": snapshot.student.cumulative_gpa,
                "completed_credits": snapshot.student.completed_credits,
                "required_degree_credits": snapshot.student.required_degree_credits,
            },
            "academic_years": [
                {
                    "year": year.year,
                    "weighted_average": year.weighted_average,
                    "courses": [
                        {
                            "code": course.code,
                            "base_code": course.base_code,
                            "grade": course.grade,
                            "gpa": course.gpa,
                            "credits": course.credits,
                        }
                        for course in year.courses
                    ],
                }
                for year in snapshot.academic_years
            ],
            "scholarship_summary": {
                "latest_acquired_year": snapshot.scholarship_summary.latest_acquired_year,
                "latest_acquired_amount": snapshot.scholarship_summary.latest_acquired_amount,
                "years": [
                    {
                        "year": year.year,
                        "weighted_average": year.weighted_average,
                        "amount": year.amount,
                        "calculation_status": year.calculation_status,
                    }
                    for year in snapshot.scholarship_summary.years
                ],
            },
        }

    def _route_academic_fact(
        self, question: str, snapshot: AcademicSnapshot, conversation_id: str
    ) -> tuple[str, list[str], list[str]] | None:
        """Answer common current-student fact requests without involving the model."""
        lowered = question.casefold()
        year_match = re.search(r"\b(20\d{2}-20\d{2})\b", question)
        course_code_match = re.search(r"\b([A-Za-z]{2,8}[- ]\d{3,4}(?:-\d{1,3})?)\b", question)

        extreme_direction = None
        if re.search(r"\b(?:lowest|worst|weakest|bottom)\b", lowered) and re.search(
            r"\b(?:course|grade|mark|result)s?\b", lowered
        ):
            extreme_direction = "lowest"
        elif re.search(r"\b(?:highest|best|strongest|top)\b", lowered) and re.search(r"\b(?:course|grade|mark|result)s?\b", lowered):
            extreme_direction = "highest"
        if extreme_direction:
            count = self._requested_count(lowered, default=5)
            result = execute_tool(
                "get_course_extremes",
                {"count": 20 if year_match else count, "direction": extreme_direction},
                snapshot,
            )
            courses = [
                course
                for course in result["courses"]
                if not year_match or course["academic_year"] == year_match.group(1)
            ][:count]
            self._last_academic_courses[(conversation_id, snapshot.snapshot_id)] = courses
            if not courses:
                return "No graded courses match that request in your connected record.", ["get_course_extremes"], []
            answer = "\n".join(
                f"{index}. {course['code']} — {course['grade']}% — {course['academic_year']}"
                for index, course in enumerate(courses, start=1)
            )
            return answer, ["get_course_extremes"], ["What years did I take those?", "Compare my subjects"]

        available_subjects = {
            course.base_code.split("-")[0]
            for year in snapshot.academic_years
            for course in year.courses
        }
        requested_subject = next(
            (
                subject
                for subject in sorted(available_subjects)
                if re.search(rf"\b{re.escape(subject)}\b", question, re.I)
            ),
            None,
        )
        if (
            re.search(r"\bsubject(?:s| performance)?\b|\bdepartment(?:s)?\b", lowered)
            or requested_subject
        ) and re.search(r"\b(?:doing|score|perform|highest|lowest|best|strong|weak|average)", lowered):
            result = execute_tool("get_subject_performance", {}, snapshot)
            subjects = [
                item
                for item in result["subjects"]
                if not requested_subject or item["subject"] == requested_subject
            ]
            if not subjects:
                answer = "No graded subject results are available in your connected record."
            else:
                leading_subject = requested_subject or (
                    subjects[-1]["subject"]
                    if re.search(r"\b(?:lowest|weak)", lowered)
                    else subjects[0]["subject"]
                )
                contextual_courses = [
                    course
                    for course in current_completed_course_records(snapshot)
                    if course["base_code"].split("-")[0] == leading_subject
                ]
                self._last_academic_courses[(conversation_id, snapshot.snapshot_id)] = contextual_courses
                answer = "\n".join(
                    f"{item['subject']} — {item['average_grade']:.2f}% across {item['course_count']} course{'s' if item['course_count'] != 1 else ''}"
                    for item in subjects
                )
            return answer, ["get_subject_performance"], ["Show my lowest courses", "Which subject is strongest?"]

        if re.search(r"\b(?:cumulative\s+)?gpa\b", lowered) and not re.search(r"\b(?:project|what if|future|next term)\b", lowered):
            value = snapshot.student.cumulative_gpa
            answer = "Your cumulative GPA is unavailable in the connected record." if value is None else f"Your cumulative GPA is {value:.3f}."
            return answer, ["get_student_summary"], ["How many credits have I completed?", "What if I get 90 next term?"]

        if re.search(
            r"\b(?:credits? (?:left|remaining)|how many more credits?|credits? (?:until|till) graduation)\b",
            lowered,
        ):
            completed = snapshot.student.completed_credits
            required = snapshot.student.required_degree_credits
            remaining = max(required - completed, 0)
            return (
                f"You have {remaining:g} credits remaining to reach {required:g} credits. You've completed {completed:g}.",
                ["get_student_summary"],
                ["What is my cumulative GPA?", "What year of study am I in?"],
            )

        if re.search(r"\b(?:completed\s+)?credits?|credit hours?\b", lowered) and not re.search(r"\b(?:course|each)\b", lowered):
            return (
                f"You have completed {snapshot.student.completed_credits:g} of {snapshot.student.required_degree_credits:g} required credits.",
                ["get_student_summary"],
                ["What is my cumulative GPA?", "What year of study am I in?"],
            )

        if re.search(r"\b(?:major|minor|faculty|school|year of study)\b", lowered):
            pieces: list[str] = []
            if "major" in lowered:
                pieces.append("Majors: " + (", ".join(snapshot.student.majors) or "none listed"))
            if "minor" in lowered:
                pieces.append("Minors: " + (", ".join(snapshot.student.minors) or "none listed"))
            if "faculty" in lowered or "school" in lowered:
                pieces.append("Faculty/school: " + (snapshot.student.faculty or "not listed"))
            if "year of study" in lowered:
                pieces.append("Year of study: " + (str(snapshot.student.year_of_study) if snapshot.student.year_of_study else "not available"))
            return "; ".join(pieces) + ".", ["get_student_summary"], []

        if re.search(r"\b(?:latest|most recent) scholarship\b", lowered):
            summary = snapshot.scholarship_summary
            if summary.latest_acquired_amount is None:
                answer = "You have no acquired scholarship recorded yet."
            else:
                answer = f"Your most recent acquired scholarship was ${summary.latest_acquired_amount:,.0f} for {summary.latest_acquired_year}."
            return answer, ["get_scholarship_summary"], ["Show my yearly averages"]

        if year_match and "scholarship" in lowered:
            year = next(
                (
                    item
                    for item in snapshot.scholarship_summary.years
                    if item.year == year_match.group(1)
                ),
                None,
            )
            if year is None or year.calculation_status != "calculated":
                answer = f"No scholarship result was calculated for {year_match.group(1)}."
            elif year.amount:
                answer = f"The calculated scholarship for {year.year} was ${year.amount:,.0f}."
            else:
                answer = f"The completed {year.year} calculation produced a $0 scholarship."
            return answer, ["get_scholarship_summary"], []

        if re.search(r"\b(?:best|strongest|highest) academic year\b", lowered):
            calculated = [
                year
                for year in snapshot.scholarship_summary.years
                if year.calculation_status == "calculated"
                and year.weighted_average is not None
            ]
            if not calculated:
                answer = "No completed academic year has a calculated weighted average."
            else:
                best = max(calculated, key=lambda item: item.weighted_average or 0)
                answer = f"Your strongest calculated academic year was {best.year} at {best.weighted_average:.2f}%."
            return answer, ["get_scholarship_summary"], []

        if re.search(r"\b(?:scholarship history|yearly averages?|academic averages?|scholarships? by year)\b", lowered):
            answer = "\n".join(
                f"{year.year} — "
                + (f"{year.weighted_average:.2f}%" if year.weighted_average is not None else "not calculated")
                + (f" — ${year.amount:,.0f}" if year.amount is not None else " — no result")
                for year in snapshot.scholarship_summary.years
            )
            return answer, ["get_scholarship_summary"], []

        history_request = bool(
            re.search(
                r"\b(?:all|every|each) (?:my )?.*attempts?\b|\b(?:first|earliest|previous|prior)\b.*\b(?:grade|attempt)\b|\bdid i ever fail\b|\brepeated courses?\b|\bretak(?:e|en|ing)\b",
                lowered,
            )
        )
        if history_request:
            attempts: dict[str, list[dict[str, Any]]] = {}
            for year in snapshot.academic_years:
                for course in year.courses:
                    if course_code_match:
                        requested = course_code_match.group(1).replace(" ", "-").upper()
                        if requested not in {course.code.upper(), course.base_code.upper()}:
                            continue
                    attempts.setdefault(course.base_code, []).append({**course.model_dump(), "academic_year": year.year})
            if "fail" in lowered:
                repeated = [
                    course
                    for courses in attempts.values()
                    for course in courses
                    if isinstance(course["grade"], int) and course["grade"] < 50
                ]
            elif re.search(r"\b(?:first|earliest)\b", lowered):
                repeated = [courses[0] for courses in attempts.values() if courses]
            else:
                repeated = [course for courses in attempts.values() if len(courses) > 1 or course_code_match for course in courses]
            self._last_academic_courses[(conversation_id, snapshot.snapshot_id)] = repeated
            if repeated:
                answer = "\n".join(
                    f"{course['code']} — {course['grade']}{'%' if isinstance(course['grade'], int) else ''} — {course['academic_year']}"
                    for course in repeated
                )
            elif "fail" in lowered:
                answer = "No failed numeric course attempts are present in your connected record."
            elif course_code_match:
                answer = "I can't find that course attempt in your connected academic record."
            else:
                answer = "No repeated courses are present in your connected record."
            return answer, ["get_academic_record"], []

        if re.search(r"\b(?:how many|number of|course count)\b.*\bcourses?\b", lowered):
            courses = [course for year in snapshot.academic_years for course in year.courses]
            return f"Your connected record contains {len(courses)} course records.", ["get_academic_record"], []

        if year_match and re.search(r"\b(?:take|took|courses?|grades?|marks?|results?|average)\b", lowered):
            year = next((item for item in snapshot.academic_years if item.year == year_match.group(1)), None)
            if year is None:
                return f"I can't find {year_match.group(1)} in your connected academic record.", ["get_academic_record"], []
            courses = [{**course.model_dump(), "academic_year": year.year} for course in year.courses]
            self._last_academic_courses[(conversation_id, snapshot.snapshot_id)] = courses
            answer = "No courses are recorded for that academic year." if not courses else "\n".join(
                f"{course['code']} — {course['grade']}{'%' if isinstance(course['grade'], int) else ''}" for course in courses
            )
            return answer, ["get_academic_record"], ["What years did I take those?"]

        if course_code_match:
            requested = course_code_match.group(1).replace(" ", "-").upper()
            found = [
                course
                for course in current_completed_course_records(snapshot)
                if requested in {course["code"].upper(), course["base_code"].upper()}
            ]
            self._last_academic_courses[(conversation_id, snapshot.snapshot_id)] = found
            if not found:
                return "I can't verify that course in your connected academic record.", ["get_academic_record"], []
            return "\n".join(
                f"{course['code']} — {course['grade']}{'%' if isinstance(course['grade'], int) else ''} — {course['academic_year']}" for course in found
            ), ["get_academic_record"], ["What year did I take that?"]

        if re.search(r"\b(?:what|which|show|list)\b.*\b(?:courses?|grades?|marks?)\b", lowered) and not re.search(r"\b(?:why|compare|explain|how am i)\b", lowered):
            courses = [
                {**course.model_dump(), "academic_year": year.year}
                for year in snapshot.academic_years
                for course in year.courses
            ]
            self._last_academic_courses[(conversation_id, snapshot.snapshot_id)] = courses
            answer = "No courses are available in your connected record." if not courses else "\n".join(
                f"{course['code']} — {course['grade']}{'%' if isinstance(course['grade'], int) else ''} — {course['academic_year']}"
                for course in courses
            )
            return answer, ["get_academic_record"], ["What years did I take those?"]

        return None

    @staticmethod
    def _requested_count(question: str, *, default: int) -> int:
        match = re.search(r"\b(\d{1,2})\b", question)
        if match:
            return min(20, max(1, int(match.group(1))))
        words = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10}
        return next((count for word, count in words.items() if re.search(rf"\b{word}\b", question)), default)

    @staticmethod
    def _academic_answer_is_verified(answer: str, snapshot: AcademicSnapshot) -> bool:
        courses = [course for year in snapshot.academic_years for course in year.courses]
        by_code: dict[str, list[Any]] = {}
        for course in courses:
            by_code.setdefault(course.code.upper(), []).append(course.grade)
            by_code.setdefault(course.base_code.upper(), []).append(course.grade)
        for match in re.finditer(r"\b([A-Za-z]{2,8}[- ]\d{3,4}(?:-\d{1,3})?)\b", answer):
            code = match.group(1).replace(" ", "-").upper()
            if code not in by_code:
                return False
            line_start = answer.rfind("\n", 0, match.start()) + 1
            line_end = answer.find("\n", match.end())
            line = answer[line_start : None if line_end == -1 else line_end]
            percentages = [int(value) for value in re.findall(r"\b(\d{1,3})(?:\.\d+)?%", line)]
            numeric_grades = {int(value) for value in by_code[code] if isinstance(value, int) and not isinstance(value, bool)}
            if percentages and any(value not in numeric_grades for value in percentages):
                return False
        allowed_percentages = {
            round(float(value), 2)
            for value in [
                *(course.grade for course in courses),
                *(year.weighted_average for year in snapshot.academic_years),
            ]
            if isinstance(value, (int, float)) and not isinstance(value, bool)
        }
        for value in re.findall(r"\b(\d{1,3}(?:\.\d+)?)%", answer):
            if round(float(value), 2) not in allowed_percentages:
                return False
        allowed_gpas = {
            round(float(value), 3)
            for value in [snapshot.student.cumulative_gpa, *(course.gpa for course in courses)]
            if isinstance(value, (int, float)) and not isinstance(value, bool)
        }
        for value in re.findall(r"\bGPA\b[^\d]{0,20}(\d(?:\.\d+)?)", answer, re.I):
            if round(float(value), 3) not in allowed_gpas:
                return False
        allowed_credits = {
            round(float(value), 2)
            for value in (
                snapshot.student.completed_credits,
                snapshot.student.total_credit_hours,
                snapshot.student.required_degree_credits,
                *(course.credits for course in courses),
            )
        }
        for value in re.findall(r"\b(\d+(?:\.\d+)?)\s+(?:completed\s+)?(?:credit|credit hours?)\b", answer, re.I):
            if round(float(value), 2) not in allowed_credits:
                return False
        allowed_amounts = {
            float(year.amount)
            for year in snapshot.scholarship_summary.years
            if year.amount is not None
        }
        for value in re.findall(r"\$\s*([\d,]+(?:\.\d+)?)", answer):
            if float(value.replace(",", "")) not in allowed_amounts:
                return False
        valid_years = {year.year for year in snapshot.academic_years}
        if any(year not in valid_years for year in re.findall(r"\b20\d{2}-20\d{2}\b", answer)):
            return False
        return True

    @staticmethod
    def _has_explicit_apply_intent(question: str) -> bool:
        return bool(
            re.search(
                r"\b(?:apply(?:ing)?(?: for)?|start (?:an? )?application|help me apply|open (?:an? )?application)\b",
                question,
                re.I,
            )
        )

    @staticmethod
    def _pending_application_question(
        application_id: str | None,
    ) -> dict[str, str] | None:
        if not application_id:
            return None
        try:
            state = SCHOLARSHIP_SESSION.get_application(application_id)
        except ValueError:
            return None
        if not state.pending_background_field:
            return None
        field = next(
            (
                item
                for item in state.fields
                if item.field_id == state.pending_background_field
            ),
            None,
        )
        if field is None:
            return None
        return {"label": field.label, "type": field.type}

    @staticmethod
    def _validate_draft_source(
        tool_name: str,
        arguments: Any,
        user_messages: list[str],
    ) -> None:
        if tool_name != "draft_personal_statement":
            return
        try:
            parsed = json.loads(arguments) if isinstance(arguments, str) else arguments
        except json.JSONDecodeError as exc:
            raise ToolExecutionError("Draft tool arguments were not valid JSON.") from exc
        source_notes = parsed.get("source_notes") if isinstance(parsed, dict) else None
        if not isinstance(source_notes, str) or not source_notes.strip():
            raise ToolExecutionError("Draft source_notes must copy the student's raw facts.")
        if not any(source_notes.strip() in message for message in user_messages):
            raise ToolExecutionError(
                "source_notes must be copied exactly from a student message; do not summarize or add facts."
            )

    @staticmethod
    def _extract_message(body: dict[str, Any]) -> dict[str, Any]:
        choices = body.get("choices")
        if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
            raise AgentServiceError("DeepSeek returned a response without a choice.")
        message = choices[0].get("message")
        if not isinstance(message, dict):
            raise AgentServiceError("DeepSeek returned a response without a message.")
        return message

    @staticmethod
    def _parse_tool_call(tool_call: Any) -> tuple[str, str, Any]:
        if not isinstance(tool_call, dict):
            raise AgentServiceError("DeepSeek returned an invalid tool request.")
        tool_id = tool_call.get("id")
        function = tool_call.get("function")
        if (
            not isinstance(tool_id, str)
            or not tool_id
            or not isinstance(function, dict)
            or not isinstance(function.get("name"), str)
        ):
            raise AgentServiceError("DeepSeek returned an invalid tool request.")
        return tool_id, function["name"], function.get("arguments", "{}")

    @staticmethod
    def _read_cache_key(name: str, arguments: Any) -> str | None:
        if name not in {
            "get_student_summary",
            "get_scholarship_summary",
            "get_academic_record",
            "get_student_background",
            "inspect_scholarship",
            "inspect_application_form",
        }:
            return None
        return f"{name}:{arguments if isinstance(arguments, str) else json.dumps(arguments, sort_keys=True)}"

    @staticmethod
    def _collect_sources(result: dict[str, Any], sources: list[dict[str, str]]) -> None:
        candidates: list[dict[str, Any]] = []
        if isinstance(result.get("sources"), list):
            candidates.extend(item for item in result["sources"] if isinstance(item, dict))
        if isinstance(result.get("source"), dict):
            candidates.append(result["source"])
        scholarship = result.get("scholarship")
        if isinstance(scholarship, dict) and scholarship.get("source_url"):
            candidates.append(
                {
                    "title": scholarship.get("source_title") or "UPEI Scholarships and Awards",
                    "url": scholarship["source_url"],
                }
            )
        for candidate in candidates:
            title = candidate.get("title")
            url = candidate.get("url")
            if (
                isinstance(title, str)
                and isinstance(url, str)
                and not any(source["url"] == url for source in sources)
            ):
                sources.append({"title": title, "url": url})

    @staticmethod
    def _ui_updates(tools_used: list[str]) -> list[str]:
        tools = set(tools_used)
        updates: list[str] = []
        if tools & {"search_upei_scholarships", "rank_scholarship_matches"}:
            updates.append("refresh_scholarships")
        if tools & {
            "open_scholarship_application",
            "inspect_application_form",
            "save_application_answer",
            "draft_personal_statement",
            "prepare_application_preview",
            "prepare_application_email",
            "submit_application",
        }:
            updates.append("refresh_application")
        return updates
