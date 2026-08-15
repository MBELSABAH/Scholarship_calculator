from __future__ import annotations

import json
import unittest
from copy import deepcopy

from backend.academic_service import build_academic_snapshot, load_demo_record
from backend.agent_service import (
    ACADEMIC_COPILOT_SYSTEM_PROMPT,
    AgentRoundsExceededError,
    AgentService,
    NoAcademicSnapshotError,
    SCHOLARSHIP_AGENT_SYSTEM_PROMPT,
    SYSTEM_PROMPT,
    contextual_suggestions,
    ConversationStore,
    SCHOLARSHIP_SESSION,
)
from backend.agent_tools import get_course_extremes, get_subject_performance
from backend.scholarship_models import (
    ScholarshipCriterionStatus,
    ScholarshipMatch,
    ScholarshipRecord,
)


def model_response(*, content=None, tool_calls=None):
    message = {"role": "assistant", "content": content}
    if tool_calls is not None:
        message["tool_calls"] = tool_calls
    return {"choices": [{"message": message, "finish_reason": "tool_calls" if tool_calls else "stop"}]}


def tool_call(call_id, name, arguments="{}"):
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": arguments},
    }


class FakeModelClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    async def create_chat_completion(self, messages, tools):
        self.calls.append({"messages": deepcopy(messages), "tools": deepcopy(tools)})
        return self.responses.pop(0)


class AcademicAgentServiceTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.snapshot = build_academic_snapshot(load_demo_record(), source="demo")

    async def test_null_content_tool_call_and_matching_tool_call_id(self):
        client = FakeModelClient(
            [
                model_response(
                    content=None,
                    tool_calls=[tool_call("call_summary", "get_student_summary")],
                ),
                model_response(content="You have completed exactly 54 credit hours."),
            ]
        )
        service = AgentService(client)

        result = await service.chat("Summarize my connected profile in one sentence.", self.snapshot)

        self.assertEqual(result.tools_used, ["get_student_summary"])
        second_request = client.calls[1]["messages"]
        self.assertIsNone(second_request[-2]["content"])
        self.assertEqual(second_request[-1]["role"], "tool")
        self.assertEqual(second_request[-1]["tool_call_id"], "call_summary")
        self.assertEqual(json.loads(second_request[-1]["content"])["total_credit_hours"], 54)

    async def test_unknown_tool_returns_safe_tool_error_without_execution(self):
        client = FakeModelClient(
            [
                model_response(
                    content=None,
                    tool_calls=[tool_call("call_unknown", "run_python")],
                ),
                model_response(content="That information is unavailable."),
            ]
        )
        service = AgentService(client)

        result = await service.chat("Run arbitrary Python", self.snapshot)

        self.assertEqual(result.tools_used, [])
        tool_message = client.calls[1]["messages"][-1]
        self.assertEqual(tool_message["tool_call_id"], "call_unknown")
        self.assertIn("Unknown academic tool", json.loads(tool_message["content"])["error"])

    async def test_max_agent_rounds_are_enforced(self):
        client = FakeModelClient(
            [
                model_response(
                    content=None,
                    tool_calls=[tool_call(f"call_{index}", "get_student_summary")],
                )
                for index in range(6)
            ]
        )
        service = AgentService(client, max_rounds=6)

        with self.assertRaises(AgentRoundsExceededError):
            await service.chat("Keep checking forever", self.snapshot)

        self.assertEqual(len(client.calls), 6)

    async def test_no_snapshot_prevents_model_call(self):
        client = FakeModelClient([model_response(content="Should not be used")])
        service = AgentService(client)

        with self.assertRaisesRegex(NoAcademicSnapshotError, "Connect your academic record"):
            await service.chat("What is my GPA?", None)

        self.assertEqual(client.calls, [])

    async def test_simple_fact_goes_to_model_with_full_sanitized_current_record(self):
        client = FakeModelClient(
            [model_response(content="Your cumulative GPA is 4.094.")]
        )
        service = AgentService(client)

        result = await service.chat("What is my GPA?", self.snapshot)

        self.assertEqual(result.message, "Your cumulative GPA is 4.094.")
        self.assertEqual(result.tools_used, [])
        context_message = next(
            item["content"]
            for item in client.calls[0]["messages"]
            if item["role"] == "system"
            and item["content"].startswith("CURRENT CONNECTED ACADEMIC RECORD")
        )
        serialized = context_message.split("\n", 1)[1].split("\nUse this current record", 1)[0]
        context = json.loads(serialized)
        self.assertEqual(context["snapshot_provenance"], {
            "snapshot_id": self.snapshot.snapshot_id,
            "source": "demo",
        })
        self.assertEqual(context["student"]["cumulative_gpa"], 4.094)
        course = context["academic_years"][0]["courses"][0]
        self.assertTrue({"code", "base_code", "name", "grade", "gpa", "credits", "academic_year"} <= set(course))
        self.assertIn("scholarship_history", context)
        self.assertNotIn("password", context_message.casefold())
        self.assertNotIn("username", context_message.casefold())
        self.assertNotIn("api_key", context_message.casefold())

    async def test_model_selected_course_tool_and_natural_follow_up(self):
        top = get_course_extremes(
            self.snapshot, {"count": 3, "direction": "highest"}
        )["courses"]
        ranked_answer = "\n".join(
            f"{item['code']} — {item['grade']}% — {item['academic_year']}"
            for item in top
        )
        client = FakeModelClient(
            [
                model_response(
                    tool_calls=[
                        tool_call(
                            "call_top",
                            "get_course_extremes",
                            '{"count":3,"direction":"highest"}',
                        )
                    ]
                ),
                model_response(content=ranked_answer),
                model_response(
                    content="Because those are your three highest latest-attempt numeric course grades."
                ),
            ]
        )
        service = AgentService(client)

        first = await service.chat("What are my top 3 courses?", self.snapshot)
        follow_up = await service.chat(
            "Why?", self.snapshot, conversation_id=first.conversation_id
        )

        self.assertEqual(first.tools_used, ["get_course_extremes"])
        self.assertEqual(first.message, ranked_answer)
        self.assertIn("three highest", follow_up.message)
        follow_up_messages = client.calls[2]["messages"]
        self.assertIn(
            {"role": "user", "content": "What are my top 3 courses?"},
            follow_up_messages,
        )
        self.assertIn(
            {"role": "assistant", "content": ranked_answer}, follow_up_messages
        )

    async def test_natural_subject_comparison_selects_subject_tool(self):
        record = load_demo_record()
        record["courses"] = [
            *record["courses"],
            {"academic_year": "2025-2026", "code": "MCS-1000-01", "name": "MCS I", "grade": "99", "credits": 3},
            {"academic_year": "2025-2026", "code": "MCS-2000-01", "name": "MCS II", "grade": "98", "credits": 3},
        ]
        snapshot = build_academic_snapshot(record, source="demo")
        subjects = get_subject_performance(snapshot)["subjects"]
        strongest = subjects[0]
        answer = (
            f"{strongest['subject']} is strongest of CS, MATH, and MCS at "
            f"{strongest['average_grade']:.2f}%."
        )
        client = FakeModelClient(
            [
                model_response(
                    tool_calls=[
                        tool_call("call_subjects", "get_subject_performance")
                    ]
                ),
                model_response(content=answer),
            ]
        )
        service = AgentService(client)

        result = await service.chat(
            "Which am I better at, CS, MATH, or MCS?", snapshot
        )

        self.assertEqual(result.tools_used, ["get_subject_performance"])
        self.assertIn("MCS", result.message)

    async def test_full_experimental_academic_sequence_uses_one_conversation(self):
        top = get_course_extremes(
            self.snapshot, {"count": 3, "direction": "highest"}
        )["courses"]
        low = get_course_extremes(
            self.snapshot, {"count": 3, "direction": "lowest"}
        )["courses"]
        strongest = get_subject_performance(self.snapshot)["subjects"][0]
        top_answer = "\n".join(
            f"{item['code']} — {item['grade']}% — {item['academic_year']}"
            for item in top
        )
        low_answer = "\n".join(
            f"{item['code']} — {item['grade']}% — {item['academic_year']}"
            for item in low
        )
        subject_answer = (
            f"{strongest['subject']} is your strongest subject at "
            f"{strongest['average_grade']:.2f}%."
        )
        client = FakeModelClient(
            [
                model_response(content="Your cumulative GPA is 4.094."),
                model_response(tool_calls=[tool_call("top", "get_course_extremes", '{"count":3,"direction":"highest"}')]),
                model_response(content=top_answer),
                model_response(tool_calls=[tool_call("best_subject", "get_subject_performance")]),
                model_response(content=subject_answer),
                model_response(tool_calls=[tool_call("compare_subjects", "get_subject_performance")]),
                model_response(content="CS is stronger than MATH in your current record; no MCS courses are recorded."),
                model_response(content="Because the latest-attempt CS grades aggregate higher than the MATH grades."),
                model_response(tool_calls=[tool_call("hurting", "get_course_extremes", '{"count":3,"direction":"lowest"}')]),
                model_response(content=low_answer),
                model_response(tool_calls=[tool_call("trend", "get_academic_record")]),
                model_response(content="Yes—your later academic years are stronger overall than your earliest year."),
                model_response(tool_calls=[tool_call("credits", "get_student_summary")]),
                model_response(content="You have 66 credits left to reach 120."),
            ]
        )
        service = AgentService(client)
        prompts = [
            "What is my GPA?",
            "What are my top 3 courses?",
            "Which subject am I best at?",
            "Which am I better at, CS, MATH, or MCS?",
            "Why?",
            "What are the courses hurting my academic performance most?",
            "Did I improve over time?",
            "How many credits do I have left?",
        ]
        expected_tools = [
            [],
            ["get_course_extremes"],
            ["get_subject_performance"],
            ["get_subject_performance"],
            [],
            ["get_course_extremes"],
            ["get_academic_record"],
            ["get_student_summary"],
        ]
        conversation_id = None
        results = []

        for prompt in prompts:
            result = await service.chat(
                prompt, self.snapshot, conversation_id=conversation_id
            )
            conversation_id = result.conversation_id
            results.append(result)

        self.assertEqual([result.tools_used for result in results], expected_tools)
        self.assertEqual(len({result.conversation_id for result in results}), 1)
        why_request = client.calls[7]["messages"]
        self.assertIn(
            {"role": "user", "content": prompts[3]}, why_request
        )
        self.assertIn(
            {"role": "assistant", "content": results[3].message}, why_request
        )

    async def test_discovery_cannot_open_application_without_explicit_apply_intent(self):
        SCHOLARSHIP_SESSION.clear_student_state()
        client = FakeModelClient(
            [
                model_response(
                    content=None,
                    tool_calls=[
                        tool_call(
                            "call_apply",
                            "open_scholarship_application",
                            '{"scholarship_id":"invented"}',
                        )
                    ],
                ),
                model_response(content="Open the official scholarship page to continue."),
            ]
        )
        service = AgentService(client)

        result = await service.chat("Find scholarships", self.snapshot, mode="scholarship")

        self.assertEqual(result.tools_used, [])
        self.assertEqual(SCHOLARSHIP_SESSION.applications, {})
        self.assertNotIn("Open the official scholarship page", result.message)
        self.assertFalse(
            service._has_explicit_apply_intent(
                "Which applications need more information?"
            )
        )
        self.assertTrue(service._has_explicit_apply_intent("Help me apply"))

    async def test_unverified_model_course_never_reaches_user(self):
        client = FakeModelClient([model_response(content="ANTH-1010 was 84%.")])
        service = AgentService(client)

        result = await service.chat("Give me one short academic observation.", self.snapshot)

        self.assertNotIn("ANTH-1010", result.message)
        self.assertEqual(
            result.message,
            "I can't verify that course or grade in your connected academic record.",
        )

    async def test_model_cannot_attach_wrong_grade_to_real_course(self):
        client = FakeModelClient(
            [model_response(content="CS-1910-01 was 84%.")]
        )
        service = AgentService(client)

        result = await service.chat("Give me one short academic observation.", self.snapshot)

        self.assertEqual(
            result.message,
            "I can't verify that course or grade in your connected academic record.",
        )

    async def test_model_cannot_attach_wrong_grade_without_percent_sign(self):
        client = FakeModelClient(
            [model_response(content="CS-1910-01 grade was 84.")]
        )
        service = AgentService(client)

        result = await service.chat(
            "What grade did I get in CS-1910?", self.snapshot
        )

        self.assertEqual(
            result.message,
            "I can't verify that course or grade in your connected academic record.",
        )

    async def test_scholarship_model_cannot_claim_unverified_rating_update(self):
        client = FakeModelClient(
            [model_response(content="Both potential matches are now Excellent Match.")]
        )
        service = AgentService(client)

        result = await service.chat(
            "Tell me what changed.", self.snapshot, mode="scholarship"
        )

        self.assertIn("no verified backend rating transition", result.message)
        self.assertNotIn("now Excellent", result.message)

    async def test_scholarship_mode_receives_structured_current_match_context(self):
        SCHOLARSHIP_SESSION.clear_student_state()
        SCHOLARSHIP_SESSION.save_background_answer(
            "financial_need", True, confirmed=True
        )
        SCHOLARSHIP_SESSION.matches = [
            ScholarshipMatch(
                scholarship_id="demo-award",
                scholarship=ScholarshipRecord(
                    id="demo-award",
                    name="Demo Academic Award",
                    amount=2500,
                    description="A demo award.",
                    source_url="https://example.edu/award",
                    source_title="Official award page",
                ),
                match_level="potential",
                confidence=0.6,
                known_matches=["Faculty matches"],
                criteria=[
                    ScholarshipCriterionStatus(
                        key="leadership",
                        status="unknown",
                        published_text="Demonstrated leadership",
                        question="Have you held a leadership role?",
                        user_field="leadership",
                        expected_answer_type="text",
                    )
                ],
            )
        ]
        SCHOLARSHIP_SESSION.pending_question = {
            "field": "leadership",
            "question": "Have you held a leadership role?",
        }
        client = FakeModelClient(
            [
                model_response(
                    content="It remains potential because leadership is still unconfirmed."
                )
            ]
        )
        service = AgentService(client)
        direct_context = service._scholarship_context_block(
            self.snapshot, {"current_application_id": "app-123"}
        )
        self.assertEqual(
            direct_context["pending_question"]["field"], "leadership"
        )
        SCHOLARSHIP_SESSION.pending_question = None

        await service.chat(
            "Why is that one potential?",
            self.snapshot,
            mode="scholarship",
            ui_context={"current_application_id": "app-123"},
        )

        context_message = next(
            item["content"]
            for item in client.calls[0]["messages"]
            if item["role"] == "system"
            and item["content"].startswith("CURRENT SCHOLARSHIP CONTEXT")
        )
        serialized = context_message.split("\n", 1)[1].split(
            "\nUse this context", 1
        )[0]
        context = json.loads(serialized)
        self.assertTrue(context["confirmed_personal_background"]["financial_need"])
        self.assertEqual(context["ranked_scholarships"][0]["amount"], 2500.0)
        self.assertEqual(
            context["ranked_scholarships"][0]["unresolved_criteria"][0]["key"],
            "leadership",
        )
        self.assertEqual(context["current_application_id"], "app-123")
        self.assertEqual(context["snapshot_provenance"]["source"], "demo")
        SCHOLARSHIP_SESSION.clear_student_state()

    async def test_prior_assistant_hallucination_is_not_authority(self):
        client = FakeModelClient(
            [model_response(content="ANTH-1010 was 84%.")]
        )
        service = AgentService(client)
        conversation_id, _ = service.conversations.open(
            mode="academic", snapshot_id=self.snapshot.snapshot_id
        )
        service.conversations.append_turn(
            conversation_id, "Invent a course", "ANTH-1010 was 84%."
        )

        result = await service.chat(
            "What grade did I get in ANTH-1010?",
            self.snapshot,
            conversation_id=conversation_id,
        )

        self.assertEqual(
            result.message,
            "I can't verify that course or grade in your connected academic record.",
        )
        self.assertEqual(len(client.calls), 1)
        self.assertIn(
            {"role": "assistant", "content": "ANTH-1010 was 84%."},
            client.calls[0]["messages"],
        )

    def test_contextual_suggestions_change_with_tool_and_question(self):
        scholarship = contextual_suggestions(
            "What scholarship do I qualify for?", ["get_scholarship_summary"]
        )
        grades = contextual_suggestions(
            "What are my lowest five grades?", ["get_academic_record"]
        )
        projection = contextual_suggestions(
            "What if I get 90 next term?", ["project_gpa"]
        )

        self.assertNotEqual(scholarship, grades)
        self.assertNotEqual(grades, projection)
        self.assertLessEqual(len(scholarship), 3)
        self.assertIn("Why do I qualify?", scholarship)

    def test_system_prompts_require_brief_plain_normal_answers_but_allow_essays(self):
        self.assertIn("one to three short sentences", ACADEMIC_COPILOT_SYSTEM_PROMPT)
        self.assertIn("Do not use emojis", ACADEMIC_COPILOT_SYSTEM_PROMPT)
        self.assertIn("exempt from the short-answer limit", ACADEMIC_COPILOT_SYSTEM_PROMPT)
        self.assertIn("Never fabricate criteria or a detail page", SCHOLARSHIP_AGENT_SYSTEM_PROMPT)
        self.assertIn(SCHOLARSHIP_AGENT_SYSTEM_PROMPT, SYSTEM_PROMPT)

    def test_conversation_ids_are_mode_scoped(self):
        store = ConversationStore()
        scholarship_id, _ = store.open(mode="scholarship", snapshot_id="demo-one")
        store.append_turn(scholarship_id, "Find scholarships", "Does financial need apply?")
        academic_id, _ = store.open(scholarship_id, mode="academic", snapshot_id="demo-one")
        self.assertNotEqual(scholarship_id, academic_id)
        reopened_id, history = store.open(scholarship_id, mode="scholarship", snapshot_id="demo-one")
        self.assertEqual(reopened_id, scholarship_id)
        self.assertEqual(history[-1]["content"], "Does financial need apply?")

    def test_conversation_ids_cannot_cross_snapshot_provenance(self):
        store = ConversationStore()
        first_id, _ = store.open(mode="academic", snapshot_id="demo-snapshot")
        store.append_turn(first_id, "What is my GPA?", "4.0")
        replacement_id, history = store.open(first_id, mode="academic", snapshot_id="live-snapshot")
        self.assertNotEqual(first_id, replacement_id)
        self.assertEqual(history, [])


if __name__ == "__main__":
    unittest.main()
