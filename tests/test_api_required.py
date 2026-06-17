"""Tests for API provider configuration."""

from __future__ import annotations

import pytest

from app.config import get_settings
from app.llm.llm_factory import LLMProviderError, get_llm
from app.tools.image_factory import get_image_generator
from app.tools.image_generator import ImageProviderError
from app.tools.mock_image_generator import MockImageGenerator


def test_llm_requires_api_key(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.setenv("DEMO_MODE", "false")
    get_settings.cache_clear()

    with pytest.raises(LLMProviderError, match="OPENAI_API_KEY"):
        get_llm()


def test_mock_llm_enabled_in_demo_mode(monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "true")
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "")
    get_settings.cache_clear()

    llm, provider = get_llm()
    assert provider == "mock"
    assert llm.provider_name == "mock"


def test_image_mock_enabled(monkeypatch):
    monkeypatch.setenv("IMAGE_PROVIDER", "mock")
    monkeypatch.setenv("DEMO_MODE", "false")
    get_settings.cache_clear()

    gen = get_image_generator()
    assert isinstance(gen, MockImageGenerator)


def test_image_default_mock_without_env(monkeypatch):
    monkeypatch.setenv("IMAGE_PROVIDER", "")
    monkeypatch.setenv("DEMO_MODE", "false")
    get_settings.cache_clear()
    assert isinstance(get_image_generator(), MockImageGenerator)


def test_image_requires_api_key_when_openai(monkeypatch):
    monkeypatch.setenv("IMAGE_PROVIDER", "openai")
    monkeypatch.setenv("DEMO_MODE", "false")
    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.setenv("IMAGE_API_KEY", "")
    get_settings.cache_clear()

    with pytest.raises(ImageProviderError, match="Image API key required"):
        get_image_generator().generate("t1", "ecommerce_banner", "title", "prompt")


def test_unknown_image_provider_value_error(monkeypatch):
    monkeypatch.setenv("IMAGE_PROVIDER", "azure")
    monkeypatch.setenv("DEMO_MODE", "false")
    get_settings.cache_clear()
    with pytest.raises(ValueError, match="Unknown IMAGE_PROVIDER"):
        get_image_generator()
