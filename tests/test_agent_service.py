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

    async def test_course_list_and_pronoun_follow_up_are_deterministic(self):
        client = FakeModelClient([])
        service = AgentService(client)
        first = await service.chat("What are my three lowest grades?", self.snapshot)

        follow_up = await service.chat(
            "What years did I take those?",
            self.snapshot,
            conversation_id=first.conversation_id,
        )

        self.assertIn("CS-1910-01 — 78% — 2023-2024", first.message)
        self.assertIn("CS-1910-01 — 2023-2024", follow_up.message)
        self.assertEqual(client.calls, [])

    async def test_common_academic_facts_bypass_model(self):
        client = FakeModelClient([])
        service = AgentService(client)

        gpa = await service.chat("What is my GPA?", self.snapshot)
        subjects = await service.chat("Which subject do I score highest in?", self.snapshot)

        self.assertEqual(gpa.message, "Your cumulative GPA is 4.094.")
        self.assertIn("CS —", subjects.message)
        self.assertEqual(client.calls, [])

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

    async def test_prior_assistant_hallucination_is_not_authority(self):
        client = FakeModelClient([])
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
            result.message, "I can't verify that course in your connected academic record."
        )
        self.assertEqual(client.calls, [])

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
