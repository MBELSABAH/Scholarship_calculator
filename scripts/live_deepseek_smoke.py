"""Run the model-first Academic Copilot demo conversation against demo data."""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from backend.academic_service import build_academic_snapshot, load_demo_record  # noqa: E402
from backend.agent_service import (  # noqa: E402
    AgentConfigurationError,
    AgentService,
    DeepSeekClient,
)


LIVE_CASES: list[tuple[str, set[str] | None]] = [
    ("What is my GPA?", None),
    ("What are my top 3 courses?", {"get_course_extremes"}),
    ("Which subject am I best at?", {"get_subject_performance"}),
    ("Which am I better at, CS, MATH, or MCS?", {"get_subject_performance"}),
    ("Why?", None),
    (
        "What are the courses hurting my academic performance most?",
        {"get_course_extremes"},
    ),
    ("Did I improve over time?", {"get_academic_record", "get_scholarship_summary"}),
    ("How many credits do I have left?", {"get_student_summary"}),
]


async def main() -> int:
    snapshot = build_academic_snapshot(load_demo_record(), source="demo")
    service = AgentService(DeepSeekClient())
    if not os.getenv("DEEPSEEK_API_KEY", "").strip():
        print("DeepSeek is not configured. Set DEEPSEEK_API_KEY or create a local .env file.")
        return 2

    conversation_id = None
    for prompt, useful_tools in LIVE_CASES:
        print(f"\nPrompt: {prompt}")
        try:
            result = await service.chat(
                prompt, snapshot, conversation_id=conversation_id
            )
        except AgentConfigurationError as exc:
            print(str(exc))
            return 2
        conversation_id = result.conversation_id
        print(f"DeepSeek -> {', '.join(result.tools_used) or 'no tool'}")
        if useful_tools and not useful_tools.intersection(result.tools_used):
            print(f"FAILED: expected one useful tool from {', '.join(sorted(useful_tools))}")
            return 1
        print("DeepSeek -> final answer")
        print(f"Final: {result.message}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
