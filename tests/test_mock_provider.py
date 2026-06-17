"""Tests for mock image provider and demo mode."""

from __future__ import annotations

import json

import pytest
from PIL import Image

from app.config import get_settings
from app.graph import visionflow_graph as vg_module
from app.models.schemas import GenerationRequest
from app.services import generation_service as svc_module
from app.services.generation_service import GenerationService
from app.tools.aspect_ratio import resolve_aspect_ratio
from app.tools.image_factory import get_image_generator
from app.tools.image_generator import ImageProviderError, OpenAIImageGenerator
from app.tools.mock_image_generator import MockImageGenerator


@pytest.fixture
def mock_env(monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "true")
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("IMAGE_PROVIDER", "mock")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    get_settings.cache_clear()
    vg_module._graph_instance = None
    svc_module._service = None
    yield
    get_settings.cache_clear()
    vg_module._graph_instance = None
    svc_module._service = None


@pytest.mark.parametrize(
    "ratio,expected_w,expected_h",
    [
        ("1:1", 1024, 1024),
        ("16:9", 1792, 1024),
        ("9:16", 1024, 1792),
        ("4:3", 1536, 1024),
    ],
)
def test_mock_png_dimensions_match_spec(
    mock_env, tmp_path, monkeypatch, ratio, expected_w, expected_h
):
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path))
    get_settings.cache_clear()
    gen = get_image_generator()
    path = gen.generate("dim01", "ecommerce_banner", "Title", "prompt", ratio)
    with Image.open(path) as img:
        assert img.size == (expected_w, expected_h)


def test_mock_image_generator_creates_valid_png(mock_env, tmp_path, monkeypatch):
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path))
    get_settings.cache_clear()
    gen = get_image_generator()
    assert isinstance(gen, MockImageGenerator)
    path = gen.generate("abc12345", "ecommerce_banner", "Test Title", "prompt text", "16:9")
    assert path.exists()
    meta = json.loads(path.with_suffix(".mock.json").read_text(encoding="utf-8"))
    assert meta["provider"] == "mock"
    assert meta["requested_aspect_ratio"] == "16:9"
    assert meta["resolved_width"] == 1792
    assert meta["resolved_height"] == 1024


def test_factory_defaults_to_mock_provider(monkeypatch):
    """Factory maps empty/unknown provider string to mock via `or 'mock'`."""
    monkeypatch.setenv("IMAGE_PROVIDER", "mock")
    monkeypatch.setenv("DEMO_MODE", "false")
    get_settings.cache_clear()
    assert isinstance(get_image_generator(), MockImageGenerator)


def test_unknown_provider_raises_value_error(monkeypatch):
    monkeypatch.setenv("IMAGE_PROVIDER", "unknown_xyz")
    monkeypatch.setenv("DEMO_MODE", "false")
    get_settings.cache_clear()
    with pytest.raises(ValueError, match="Unknown IMAGE_PROVIDER"):
        get_image_generator()


def test_openai_missing_key_clear_error(monkeypatch):
    monkeypatch.setenv("IMAGE_PROVIDER", "openai")
    monkeypatch.setenv("DEMO_MODE", "false")
    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.setenv("IMAGE_API_KEY", "")
    get_settings.cache_clear()
    with pytest.raises(ImageProviderError, match="Image API key required"):
        OpenAIImageGenerator().generate("t1", "ecommerce_banner", "title", "prompt")


def test_unsupported_aspect_ratio_fallback_warning():
    res = resolve_aspect_ratio("21:9")
    assert res.normalized is True
    assert res.normalization_reason


def test_mock_end_to_end_generation(mock_env, tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")
    get_settings.cache_clear()
    vg_module._graph_instance = None
    svc_module._service = None

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.models.database import Base

    engine = create_engine(
        f"sqlite:///{tmp_path / 'test.db'}", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(bind=engine)
    db = sessionmaker(bind=engine)()

    service = GenerationService()
    req = GenerationRequest(
        user_input="为夏季冰咖啡制作电商促销主图 banner",
        task_type="auto",
        skip_clarification=True,
        enable_revision=False,
    )
    result = service.run_generation(db, req)
    assert result.output_path
    assert result.evaluation.offline_score >= 0
    assert result.evaluation.score_breakdown
    gen_traces = [t for t in result.traces if t.metadata.get("pipeline_step") == "output_generated"]
    assert gen_traces
    assert gen_traces[0].metadata.get("generation_mode") == "mock"
    db.close()
