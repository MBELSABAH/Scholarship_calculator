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
from backend.models import AcademicSnapshot, ConnectRequest


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
    version="0.1.0",
    description="Deterministic academic calculations exposed as structured data.",
)
snapshot_store = SnapshotStore()


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/connect", response_model=AcademicSnapshot)
async def connect(request: ConnectRequest) -> AcademicSnapshot:
    if request.demo:
        snapshot = build_academic_snapshot(load_demo_record(), source="demo")
        snapshot_store.set(snapshot)
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


FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"
app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
