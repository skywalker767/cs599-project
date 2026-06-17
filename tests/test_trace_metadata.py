"""Tests for accurate trace provider metadata."""

from __future__ import annotations

import pytest

from app.config import get_settings
from app.graph import visionflow_graph as vg_module
from app.models.schemas import GenerationRequest
from app.services import generation_service as svc_module
from app.services.generation_service import GenerationService


@pytest.fixture
def mock_env(monkeypatch, tmp_path):
    monkeypatch.setenv("DEMO_MODE", "true")
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("IMAGE_PROVIDER", "mock")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'meta.db'}")
    get_settings.cache_clear()
    vg_module._graph_instance = None
    svc_module._service = None
    yield
    get_settings.cache_clear()


def test_trace_provider_metadata_mock(mock_env, tmp_path):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.models.database import Base

    engine = create_engine(
        f"sqlite:///{tmp_path / 'meta.db'}", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(bind=engine)
    db = sessionmaker(bind=engine)()

    service = GenerationService()
    result = service.run_generation(
        db,
        GenerationRequest(
            user_input="绘制论文 pipeline 方法流程图 diagram",
            task_type="auto",
            skip_clarification=True,
            enable_revision=False,
        ),
    )
    gen_traces = [t for t in result.traces if t.step == "generate_asset"]
    assert gen_traces
    meta = gen_traces[0].metadata
    assert meta.get("generation_mode") == "svg"
    assert meta.get("provider") == "diagram_generator"
    db.close()


def test_trace_provider_metadata_mock_image(mock_env, tmp_path):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.models.database import Base

    engine = create_engine(
        f"sqlite:///{tmp_path / 'meta2.db'}", connect_args={"check_same_thread": False}
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
    gen_traces = [t for t in result.traces if t.step == "generate_asset"]
    meta = gen_traces[0].metadata
    assert meta.get("generation_mode") == "mock"
    assert meta.get("provider") == "mock"
    db.close()
