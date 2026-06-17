"""Tests for structured pipeline trace steps."""

from __future__ import annotations

import pytest

from app.config import get_settings
from app.graph import visionflow_graph as vg_module
from app.models.schemas import GenerationRequest
from app.services import generation_service as svc_module
from app.services.generation_service import GenerationService

REQUIRED_PIPELINE_STEPS = {
    "router_decision",
    "clarification_needed",
    "visual_spec_created",
    "prompt_created",
    "provider_selected",
    "output_generated",
    "evaluation_completed",
}


@pytest.fixture
def mock_env(monkeypatch, tmp_path):
    monkeypatch.setenv("DEMO_MODE", "true")
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("IMAGE_PROVIDER", "mock")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'trace.db'}")
    get_settings.cache_clear()
    vg_module._graph_instance = None
    svc_module._service = None
    yield
    get_settings.cache_clear()


def test_trace_contains_pipeline_steps(mock_env, tmp_path):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.models.database import Base

    engine = create_engine(
        f"sqlite:///{tmp_path / 'trace.db'}", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(bind=engine)
    db = sessionmaker(bind=engine)()

    service = GenerationService()
    result = service.run_generation(
        db,
        GenerationRequest(
            user_input="电商促销主图 banner product sale",
            task_type="auto",
            skip_clarification=True,
            enable_revision=False,
        ),
    )
    steps = {t.metadata.get("pipeline_step") for t in result.traces}
    missing = REQUIRED_PIPELINE_STEPS - steps
    assert not missing, f"missing pipeline steps: {missing}"
    for t in result.traces:
        assert t.timestamp
        assert t.input_summary is not None
        assert "api_key" not in str(t.metadata).lower()
    db.close()
