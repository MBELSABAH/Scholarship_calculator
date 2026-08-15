"""DeepSeek tool-calling loop and lightweight academic chat history."""

from __future__ import annotations

import json
import logging
import os
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
        self._max_messages = max_messages
        self._lock = Lock()

    def open(self, requested_id: str | None = None) -> tuple[str, list[dict[str, str]]]:
        with self._lock:
            if requested_id and requested_id in self._conversations:
                conversation_id = requested_id
            else:
                conversation_id = uuid4().hex
                self._conversations[conversation_id] = []
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


@dataclass(frozen=True)
class AgentResult:
    message: str
    conversation_id: str
    tools_used: list[str]
    suggested_replies: list[str]
    sources: list[dict[str, str]]
    ui_updates: list[str]


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

    async def chat(
        self,
        message: str,
        snapshot: AcademicSnapshot | None,
        *,
        conversation_id: str | None = None,
        ui_context: dict[str, str | None] | None = None,
    ) -> AgentResult:
        if snapshot is None:
            raise NoAcademicSnapshotError()
        question = message.strip()
        if not question:
            raise AgentServiceError("Enter a question for Academic Copilot.", http_status=422)

        active_id, history = self.conversations.open(conversation_id)
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": SYSTEM_PROMPT},
        ]
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
            pending_question = self._pending_application_question(active_application_id)
            suggestions = contextual_suggestions(question, tools_used)
            if pending_question:
                answer = (
                    "This application needs one confirmed personal detail before I continue: "
                    f"{pending_question['label']}"
                )
                if pending_question["type"] == "boolean":
                    suggestions = ["Yes", "No", "I'm not sure"]
            self.conversations.append_turn(active_id, question, answer)
            return AgentResult(
                message=answer,
                conversation_id=active_id,
                tools_used=tools_used,
                suggested_replies=suggestions,
                sources=sources,
                ui_updates=self._ui_updates(tools_used),
            )

        raise AgentRoundsExceededError()

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
