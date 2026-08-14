"""FastAPI application for the Academic Copilot dashboard."""

from __future__ import annotations

import asyncio
from pathlib import Path
from threading import Lock

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles

from backend.academic_service import (
    AcademicScrapeError,
    build_academic_snapshot,
    load_demo_record,
    run_academic_scrape,
)
from backend.agent_service import AgentService, AgentServiceError, DeepSeekClient
from backend.agent_tools import SCHOLARSHIP_SESSION
from backend.models import (
    AcademicSnapshot,
    ApplicationAnswerRequest,
    ApproveSubmissionRequest,
    BackgroundAnswerRequest,
    ChatRequest,
    ChatResponse,
    ConnectRequest,
    ScholarshipSearchRequest,
)


class SnapshotStore:
    def __init__(self) -> None:
        self._snapshot: AcademicSnapshot | None = None
        self._lock = Lock()

    def set(self, snapshot: AcademicSnapshot) -> None:
        with self._lock:
            self._snapshot = snapshot

    def get(self) -> AcademicSnapshot | None:
        with self._lock:
            return self._snapshot

    def clear(self) -> None:
        with self._lock:
            self._snapshot = None


app = FastAPI(
    title="Academic Copilot API",
    version="0.2.0",
    description="Deterministic academic calculations with a tool-grounded DeepSeek assistant.",
)
snapshot_store = SnapshotStore()
agent_service = AgentService(DeepSeekClient())


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/connect", response_model=AcademicSnapshot)
async def connect(request: ConnectRequest) -> AcademicSnapshot:
    if request.demo:
        snapshot = build_academic_snapshot(load_demo_record(), source="demo")
        snapshot_store.set(snapshot)
        agent_service.conversations.clear()
        SCHOLARSHIP_SESSION.clear_student_state()
        return snapshot

    username = request.username.strip()
    password = request.password.get_secret_value()
    if not username or not password:
        raise HTTPException(status_code=422, detail="Enter both your UPEI username and password.")

    try:
        scraped_record = await asyncio.to_thread(
            run_academic_scrape,
            username,
            password,
            browser=request.browser,
        )
        snapshot = build_academic_snapshot(scraped_record, source="live")
    except AcademicScrapeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from None
    finally:
        password = ""

    snapshot_store.set(snapshot)
    agent_service.conversations.clear()
    SCHOLARSHIP_SESSION.clear_student_state()
    return snapshot


@app.get("/api/snapshot", response_model=AcademicSnapshot)
def get_snapshot() -> AcademicSnapshot:
    snapshot = snapshot_store.get()
    if snapshot is None:
        raise HTTPException(status_code=404, detail="No academic record is connected yet.")
    return snapshot


@app.delete("/api/snapshot", status_code=204)
def clear_snapshot() -> None:
    snapshot_store.clear()
    agent_service.conversations.clear()
    SCHOLARSHIP_SESSION.clear_student_state()


@app.post("/api/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    try:
        result = await agent_service.chat(
            request.message,
            snapshot_store.get(),
            conversation_id=request.conversation_id,
            ui_context={
                "current_view": request.current_view,
                "current_scholarship_id": request.current_scholarship_id,
                "current_application_id": request.current_application_id,
            },
        )
    except AgentServiceError as exc:
        raise HTTPException(status_code=exc.http_status, detail=str(exc)) from None
    return ChatResponse(
        message=result.message,
        conversation_id=result.conversation_id,
        suggested_replies=result.suggested_replies,
        tools_used=result.tools_used,
        sources=result.sources,
        ui_updates=result.ui_updates,
    )


def _connected_snapshot() -> AcademicSnapshot:
    snapshot = snapshot_store.get()
    if snapshot is None:
        raise HTTPException(status_code=409, detail="Connect your academic record first.")
    return snapshot


@app.get("/api/scholarships")
def scholarship_matches() -> dict:
    _connected_snapshot()
    return {"matches": SCHOLARSHIP_SESSION.get_matches()}


@app.post("/api/scholarships/search")
async def search_scholarships(request: ScholarshipSearchRequest) -> dict:
    snapshot = _connected_snapshot()
    try:
        return await asyncio.to_thread(
            SCHOLARSHIP_SESSION.search_and_rank,
            snapshot,
            faculty=request.faculty,
            major=request.major,
            year_of_study=request.year_of_study,
            keyword=request.keyword,
            refresh=request.refresh,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None


@app.get("/api/scholarships/{scholarship_id}")
def scholarship_detail(scholarship_id: str) -> dict:
    _connected_snapshot()
    try:
        return SCHOLARSHIP_SESSION.inspect_match(scholarship_id)
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None


@app.get("/api/student-background")
def student_background() -> dict:
    _connected_snapshot()
    return SCHOLARSHIP_SESSION.get_background()


@app.put("/api/student-background")
def save_student_background(request: BackgroundAnswerRequest) -> dict:
    _connected_snapshot()
    try:
        return SCHOLARSHIP_SESSION.save_background_answer(
            request.field, request.value, confirmed=request.confirmed
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None


@app.post("/api/scholarships/{scholarship_id}/applications")
async def open_application(scholarship_id: str) -> dict:
    snapshot = _connected_snapshot()
    try:
        state = await asyncio.to_thread(
            SCHOLARSHIP_SESSION.open_application, scholarship_id, snapshot
        )
        return state.model_dump()
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None


@app.get("/api/applications/{application_id}")
def application_state(application_id: str) -> dict:
    _connected_snapshot()
    try:
        return SCHOLARSHIP_SESSION.get_application(application_id).model_dump()
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None


@app.put("/api/applications/{application_id}/answers")
def save_application_answer(application_id: str, request: ApplicationAnswerRequest) -> dict:
    _connected_snapshot()
    try:
        return SCHOLARSHIP_SESSION.save_application_answer(
            application_id,
            request.field_id,
            request.value,
            user_approved=request.user_approved,
        ).model_dump()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None


@app.post("/api/applications/{application_id}/preview")
def prepare_application(application_id: str) -> dict:
    _connected_snapshot()
    try:
        return SCHOLARSHIP_SESSION.prepare_preview(application_id).model_dump()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None


@app.post("/api/applications/{application_id}/approve-submit")
def approve_and_submit(
    application_id: str, request: ApproveSubmissionRequest
) -> dict:
    _connected_snapshot()
    try:
        return SCHOLARSHIP_SESSION.approve_and_submit(
            application_id, request.explicit_action
        ).model_dump()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None


FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"
app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
