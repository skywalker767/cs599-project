"""Image generator factory – supports OpenAI-compatible API and mock provider."""

from __future__ import annotations

from typing import Protocol

from app.config import get_settings
from app.tools.image_generator import OpenAIImageGenerator
from app.tools.mock_image_generator import MockImageGenerator


class ImageGenerator(Protocol):
    provider_name: str
    mode: str

    def generate(
        self,
        task_id: str,
        task_type: str,
        title: str,
        prompt: str,
        aspect_ratio: str = "1:1",
    ): ...


def get_image_generator() -> ImageGenerator:
    """Return configured image generator (openai or mock). Defaults to mock."""
    settings = get_settings()
    provider = (settings.image_provider or "mock").lower().strip()

    if settings.demo_mode:
        return MockImageGenerator()

    if provider == "mock":
        return MockImageGenerator()
    if provider == "openai":
        return OpenAIImageGenerator()

    raise ValueError(f"Unknown IMAGE_PROVIDER='{provider}'. Supported: openai, mock")
