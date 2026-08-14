"""Exercise live DeepSeek discovery and one-question scholarship interview flow."""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from backend.academic_service import build_academic_snapshot, load_demo_record  # noqa: E402
from backend.agent_service import AgentService, DeepSeekClient  # noqa: E402
from backend.agent_tools import SCHOLARSHIP_SESSION  # noqa: E402


async def main() -> int:
    if not os.getenv("DEEPSEEK_API_KEY", "").strip():
        print("DeepSeek is not configured. Set DEEPSEEK_API_KEY or create a local .env file.")
        return 2

    SCHOLARSHIP_SESSION.clear_student_state()
    snapshot = build_academic_snapshot(load_demo_record(), source="demo")
    service = AgentService(DeepSeekClient())
    discovery = await service.chat("Find scholarships I should apply for.", snapshot)
    print(f"Discovery tools: {', '.join(discovery.tools_used)}")

    candidate = next(
        (
            match
            for match in SCHOLARSHIP_SESSION.matches
            if match.scholarship.financial_need_required
        ),
        None,
    )
    if candidate is None:
        print("SKIPPED: no returned live award had a parsed financial-need criterion")
        return 0

    context = {
        "current_view": "scholarship_detail",
        "current_scholarship_id": candidate.scholarship_id,
        "current_application_id": None,
    }
    interview = await service.chat(
        "Help me apply for this scholarship.",
        snapshot,
        ui_context=context,
    )
    print(f"Application tools: {', '.join(interview.tools_used)}")
    print(f"Question: {interview.message}")
    application = next(reversed(SCHOLARSHIP_SESSION.applications.values()), None)
    if application is None or application.pending_background_field is None:
        print("FAILED: the application did not preserve a pending background question")
        return 1

    follow_up = await service.chat(
        "Yes.",
        snapshot,
        conversation_id=interview.conversation_id,
        ui_context={
            "current_view": "application",
            "current_scholarship_id": candidate.scholarship_id,
            "current_application_id": application.application_id,
        },
    )
    print(f"Follow-up tools: {', '.join(follow_up.tools_used)}")
    print(f"Follow-up: {follow_up.message}")
    if SCHOLARSHIP_SESSION.background.financial_need is not True:
        print("FAILED: the one-word answer was not stored as the pending financial-need fact")
        return 1
    print("PASS: pending financial_need=true was stored from the one-word follow-up")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
