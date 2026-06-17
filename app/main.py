"""VisionFlow FastAPI application."""

from __future__ import annotations

import mimetypes
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.database import get_db, init_db
from app.models.schemas import (
    ClarificationRequest,
    ClarificationResponse,
    DeleteResponse,
    DocumentExtractResponse,
    GenerationRequest,
    GenerationResult,
    HealthResponse,
    StatsResponse,
    TaskListResponse,
)
from app.services.generation_service import get_generation_service
from app.tools.document_extractor import DocumentExtractionError

MAX_UPLOAD_BYTES = 15 * 1024 * 1024  # 15 MB


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    settings.ensure_dirs()
    init_db()
    yield


app = FastAPI(
    title="VisionFlow API",
    description="Multi-agent visual content generation platform",
    version="0.3.0",
    lifespan=lifespan,
)


@app.get("/health", response_model=HealthResponse)
def health_check():
    settings = get_settings()
    return HealthResponse(
        status="ok",
        llm_provider=settings.llm_provider,
        image_provider=settings.image_provider,
    )


@app.get("/stats", response_model=StatsResponse)
def get_stats(db: Session = Depends(get_db)):
    """Aggregate statistics across all generated tasks."""
    service = get_generation_service()
    return service.get_stats(db)


@app.post("/extract", response_model=DocumentExtractResponse)
async def extract_document(file: UploadFile = File(...)):
    """Extract text from an uploaded PDF/text doc and distill a structured overview."""
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="上传文件为空")
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="文件过大（上限 15MB）")

    service = get_generation_service()
    try:
        return service.extract_document(file.filename or "document", data)
    except DocumentExtractionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"文档解析失败：{exc}") from exc


@app.post("/clarify", response_model=ClarificationResponse)
def clarify_requirements(request: ClarificationRequest):
    """Generate clarification multiple-choice questions before generation."""
    service = get_generation_service()
    return service.run_clarify(request)


@app.post("/generate", response_model=GenerationResult)
def generate_visual(
    request: GenerationRequest,
    db: Session = Depends(get_db),
):
    service = get_generation_service()
    try:
        return service.run_generation(db, request)
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/tasks", response_model=TaskListResponse)
def list_tasks(
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
):
    service = get_generation_service()
    page = service.list_tasks(db, limit=limit, offset=offset)
    return TaskListResponse(
        tasks=page.items,
        items=page.items,
        total=page.total,
        limit=page.limit,
        offset=page.offset,
        returned_count=len(page.items),
        has_next=page.has_next,
    )


@app.get("/tasks/{task_id}", response_model=GenerationResult)
def get_task(task_id: str, db: Session = Depends(get_db)):
    service = get_generation_service()
    record = service.get_task(db, task_id)
    if not record:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
    return record


@app.get("/tasks/{task_id}/asset")
def get_task_asset(task_id: str, db: Session = Depends(get_db)):
    """Serve the generated image/SVG asset for a task."""
    service = get_generation_service()
    record = service.get_task(db, task_id)
    if not record:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")

    path = Path(record.output_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Asset file missing: {path.name}")

    media_type = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
    if path.suffix.lower() == ".svg":
        media_type = "image/svg+xml"
    return FileResponse(str(path), media_type=media_type, filename=path.name)


@app.delete("/tasks/{task_id}", response_model=DeleteResponse)
def delete_task(task_id: str, db: Session = Depends(get_db)):
    service = get_generation_service()
    deleted = service.delete_task(db, task_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
    return DeleteResponse(task_id=task_id, deleted=True)
