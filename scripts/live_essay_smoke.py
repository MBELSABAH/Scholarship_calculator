"""Use real DeepSeek to draft and approve a demo scholarship statement safely."""

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
from backend.scholarship_models import ScholarshipRecord  # noqa: E402


async def main() -> int:
    if not os.getenv("DEEPSEEK_API_KEY", "").strip():
        print("DeepSeek is not configured. Set DEEPSEEK_API_KEY or create a local .env file.")
        return 2

    snapshot = build_academic_snapshot(load_demo_record(), source="demo")
    SCHOLARSHIP_SESSION.clear_student_state()
    scholarship = ScholarshipRecord(
        id="demo-live-essay",
        name="Demo Community Statement Award",
        amount=1000,
        deadline="Demo only",
        description="A fake demo award requiring a personal statement about community involvement.",
        personal_statement_required=True,
        application_required=True,
        source_url="https://www.upei.ca/scholarships-and-awards",
        source_title="Demo fixture — not a current UPEI award",
        is_demo=True,
    )
    with SCHOLARSHIP_SESSION.discovery._lock:
        SCHOLARSHIP_SESSION.discovery._details[scholarship.id] = scholarship
    application = SCHOLARSHIP_SESSION.open_application(scholarship.id, snapshot)
    statement_field = next(field for field in application.fields if field.essay)
    statement_field.max_length = 500

    raw_story = (
        "At a weekly community coding club, I help high-school students debug Python "
        "projects and explain basic algorithms. I started this semester."
    )
    service = AgentService(DeepSeekClient())
    context = {
        "current_view": "application",
        "current_scholarship_id": scholarship.id,
        "current_application_id": application.application_id,
    }
    draft_result = await service.chat(
        f"Use only these facts to draft the personal statement: {raw_story}",
        snapshot,
        ui_context=context,
    )
    print(f"Draft tools: {', '.join(draft_result.tools_used)}")
    state = SCHOLARSHIP_SESSION.get_application(application.application_id)
    draft = state.drafted_answers.get(statement_field.field_id)
    if draft is None or "draft_personal_statement" not in draft_result.tools_used:
        print("FAILED: DeepSeek did not save a reviewable statement draft")
        return 1
    print(f"Draft ({draft.character_count}/{draft.max_length} characters): {draft.draft_text}")
    if draft.character_count > 500 or draft.user_approved:
        print("FAILED: draft exceeded the limit or bypassed review")
        return 1

    approval = await service.chat(
        "Use this answer.",
        snapshot,
        conversation_id=draft_result.conversation_id,
        ui_context=context,
    )
    print(f"Approval tools: {', '.join(approval.tools_used)}")
    state = SCHOLARSHIP_SESSION.get_application(application.application_id)
    if statement_field.field_id not in state.user_approved_answers:
        print("FAILED: explicit answer approval was not recorded")
        return 1
    print("PASS: the draft stayed within the limit and required an explicit Use this answer turn")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
