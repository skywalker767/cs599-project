"""API error-path and mock-default integration tests.

Everything here runs on the default mock providers (no API keys, no network),
proving the documented clone-and-run experience and exercising error handling.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import get_settings
from app.main import app
from app.models.database import Base, get_db
from app.tools.image_factory import get_image_generator
from app.tools.image_generator import ImageProviderError


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


# ── Happy path on the default mock providers ───────────────────────────────


def test_full_generate_flow_on_mock(client):
    resp = client.post(
        "/generate",
        json={
            "user_input": "为夏季冰咖啡制作电商促销主图 banner product sale",
            "task_type": "auto",
            "skip_clarification": True,
            "enable_revision": False,
        },
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["task_id"]
    assert data["task_type"] == "ecommerce_banner"
    assert data["visual_spec"]["title"]
    assert data["prompt"]
    assert data["evaluation"]["score_breakdown"]
    assert data["evaluation"]["rubric"]
    assert data["traces"]

    # Output file actually exists and is downloadable.
    output = Path(data["output_path"])
    assert output.exists()
    asset = client.get(f"/tasks/{data['task_id']}/asset")
    assert asset.status_code == 200
    assert len(asset.content) > 0


def test_health_reports_mock_providers(client):
    body = client.get("/health").json()
    assert body["status"] == "ok"
    assert body["image_provider"] == "mock"
    assert body["llm_provider"] == "mock"


# ── Low-confidence / clarification handling ────────────────────────────────


def test_ambiguous_input_surfaces_clarification(client):
    """An ambiguous request must not be silently classified as ppt_visual."""
    resp = client.post(
        "/clarify",
        json={"user_input": "帮我做一张好看的东西", "task_type": "auto"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # Clarification questions are offered to resolve the ambiguity.
    assert body["questions"]
    assert "clarification_required=true" in body["route_reason"]


# ── Error paths ────────────────────────────────────────────────────────────


def test_openai_missing_key_clear_error(monkeypatch):
    monkeypatch.setenv("IMAGE_PROVIDER", "openai")
    monkeypatch.setenv("DEMO_MODE", "false")
    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.setenv("IMAGE_API_KEY", "")
    get_settings.cache_clear()
    with pytest.raises(ImageProviderError) as exc:
        get_image_generator().generate("t1", "ecommerce_banner", "title", "prompt")
    msg = str(exc.value)
    assert "Image API key required" in msg
    assert "OPENAI_API_KEY" in msg


def test_invalid_task_id_returns_404(client):
    assert client.get("/tasks/does-not-exist").status_code == 404
    assert client.get("/tasks/does-not-exist/asset").status_code == 404


def test_delete_missing_task_returns_404(client):
    assert client.delete("/tasks/does-not-exist").status_code == 404


def test_malformed_request_returns_422(client):
    # Empty user_input with no document_context fails validation.
    assert client.post("/generate", json={"user_input": ""}).status_code == 422
    # Completely missing body.
    assert client.post("/generate", json={}).status_code == 422


def test_extract_empty_upload_rejected(client):
    resp = client.post("/extract", files={"file": ("empty.txt", b"", "text/plain")})
    assert resp.status_code == 400


def test_extract_unsupported_type_rejected(client):
    resp = client.post(
        "/extract",
        files={"file": ("deck.pptx", b"fake-bytes", "application/octet-stream")},
    )
    assert resp.status_code == 422


def test_extract_oversized_upload_rejected(client, monkeypatch):
    import app.main as main_module

    monkeypatch.setattr(main_module, "MAX_UPLOAD_BYTES", 10)
    resp = client.post(
        "/extract",
        files={"file": ("big.txt", b"x" * 100, "text/plain")},
    )
    assert resp.status_code == 413
