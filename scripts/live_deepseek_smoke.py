"""Run bounded live DeepSeek tool checks against sanitized demo academic data."""

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


LIVE_CASES = [
    (
        "Find scholarships I should apply for.",
        ["get_student_summary", "search_upei_scholarships", "rank_scholarship_matches"],
    ),
    ("What was my latest acquired scholarship?", ["get_scholarship_summary"]),
    ("What are my lowest five grades?", ["get_academic_record"]),
    (
        "If I get 90 in four more 3-credit courses, what would my GPA be?",
        ["project_gpa"],
    ),
]


def is_ordered_subsequence(expected: list[str], actual: list[str]) -> bool:
    positions = iter(actual)
    return all(any(tool == target for tool in positions) for target in expected)


async def main() -> int:
    snapshot = build_academic_snapshot(load_demo_record(), source="demo")
    service = AgentService(DeepSeekClient())
    if not os.getenv("DEEPSEEK_API_KEY", "").strip():
        print("DeepSeek is not configured. Set DEEPSEEK_API_KEY or create a local .env file.")
        return 2

    for prompt, expected_tools in LIVE_CASES:
        print(f"\nPrompt: {prompt}")
        try:
            result = await service.chat(prompt, snapshot)
        except AgentConfigurationError as exc:
            print(str(exc))
            return 2
        print(f"DeepSeek -> {', '.join(result.tools_used) or 'no tool'}")
        if is_ordered_subsequence(expected_tools, result.tools_used):
            print("Python -> returned allow-listed structured data")
        else:
            print(f"FAILED: expected ordered tools {', '.join(expected_tools)}")
            return 1
        print("DeepSeek -> final answer")
        print(f"Final: {result.message}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
