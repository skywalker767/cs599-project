"""Tests for document extraction and the /extract endpoint."""

from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.models.database import Base, get_db
from app.tools.document_extractor import (
    DocumentExtractionError,
    DocumentExtractionResult,
    extract_document,
    extract_text,
    summarize_document,
)


@pytest.fixture
def client():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(bind=engine)
    TestSession = sessionmaker(bind=engine)

    def override_get_db():
        db = TestSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _make_blank_pdf() -> bytes:
    pytest.importorskip("pypdf")
    from pypdf import PdfWriter

    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def test_extract_text_from_plain_text():
    data = "Deep Learning Method\nWe propose a two-branch network.".encode("utf-8")
    text = extract_text("paper.txt", data)
    assert "two-branch network" in text


def test_extract_document_text_pdf():
    try:
        from reportlab.pdfgen import canvas  # type: ignore

        buf = io.BytesIO()
        c = canvas.Canvas(buf)
        c.drawString(72, 720, "VisionFlow academic paper on multi-agent pipelines.")
        c.save()
        pdf_bytes = buf.getvalue()
    except ImportError:
        pytest.skip("reportlab not installed for PDF text fixture")

    result = extract_document("paper.pdf", pdf_bytes)
    assert isinstance(result, DocumentExtractionResult)
    assert not result.needs_ocr
    assert "multi-agent" in result.extracted_text


def test_extract_empty_pdf_raises():
    with pytest.raises(DocumentExtractionError):
        extract_text("broken.pdf", b"not-a-pdf")


def test_scanned_pdf_needs_ocr():
    result = extract_document("scan.pdf", _make_blank_pdf())
    assert result.needs_ocr is True
    assert result.extracted_text == ""
    assert result.warning
    assert "OCR" in result.warning or "扫描" in result.warning


def test_scanned_pdf_endpoint_returns_warning(client):
    resp = client.post(
        "/extract",
        files={"file": ("scan.pdf", _make_blank_pdf(), "application/pdf")},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["summary"]["needs_ocr"] is True
    assert body["summary"]["extraction_warning"]
    assert body["document_context"] == ""


def test_unsupported_file_type_raises():
    with pytest.raises(DocumentExtractionError, match="不支持"):
        extract_document("slides.pptx", b"fake")


def test_summarize_document_fallback_without_llm():
    class _BoomLLM:
        provider_name = "test"

        def generate_text(self, system, user):  # noqa: ARG002
            raise RuntimeError("no api")

    summary = summarize_document("Some Paper Title\nMethod and experiments.", _BoomLLM())
    assert summary["title"]
    assert summary["method_steps"]
    assert summary["suggested_input"]


def test_extract_endpoint_with_text_upload(client):
    content = "VisionFlow Paper\nWe present a multi-agent pipeline for figures.".encode("utf-8")
    resp = client.post(
        "/extract",
        files={"file": ("paper.txt", content, "text/plain")},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["filename"] == "paper.txt"
    assert body["document_context"]
    assert body["summary"]["method_steps"]
    assert body["suggested_task_type"] == "academic_figure"


def test_generate_with_document_context_only(client):
    payload = {
        "user_input": "",
        "task_type": "academic_figure",
        "document_context": "【文档标题】Test Paper\n【方法流程】A → B → C",
        "skip_clarification": True,
        "enable_revision": False,
    }
    resp = client.post("/generate", json=payload)
    assert resp.status_code == 200, resp.text
    assert resp.json()["task_type"] == "academic_figure"


def test_extract_endpoint_rejects_empty(client):
    resp = client.post("/extract", files={"file": ("empty.txt", b"", "text/plain")})
    assert resp.status_code == 400
