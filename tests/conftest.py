"""Shared pytest fixtures – mock external LLM and image APIs for tests."""

from __future__ import annotations

import base64
import json

import pytest
from PIL import Image, ImageDraw

from app.config import get_settings
from app.graph import visionflow_graph as vg_module
from app.services import generation_service as svc_module


def make_blank_png(
    width: int = 256, height: int = 256, color: tuple[int, int, int] = (255, 255, 255)
) -> bytes:
    img = Image.new("RGB", (width, height), color)
    import io

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def make_low_contrast_png(width: int = 256, height: int = 256) -> bytes:
    return make_blank_png(width, height, (200, 202, 201))


def make_colorful_png(width: int = 256, height: int = 256) -> bytes:
    img = Image.new("RGB", (width, height), (255, 255, 255))
    draw = ImageDraw.Draw(img)
    for x in range(0, width, 32):
        draw.rectangle([x, 0, x + 16, height], fill=(x % 255, 100, 180))
    import io

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def make_chart_png(width: int = 400, height: int = 300) -> bytes:
    img = Image.new("RGB", (width, height), (245, 245, 250))
    draw = ImageDraw.Draw(img)
    draw.rectangle([40, 120, 80, 180], fill=(70, 130, 220))
    draw.rectangle([100, 90, 140, 180], fill=(220, 90, 70))
    draw.rectangle([160, 140, 200, 180], fill=(90, 180, 120))
    draw.line([(30, 200), (360, 200)], fill=(30, 30, 30), width=2)
    import io

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


TINY_PNG_B64 = base64.b64encode(make_colorful_png(256, 256)).decode("ascii")


def _llm_response(system_prompt: str, user_prompt: str) -> str:
    sys = system_prompt.lower()
    if "clarification" in sys:
        return json.dumps(
            {
                "questions": [
                    {
                        "question_id": "llm_scene_mood",
                        "question_text": "您希望画面传达怎样的季节氛围？",
                        "options": [
                            {"label": "清凉夏日", "value": "summer_cool", "description": None},
                            {"label": "温暖治愈", "value": "warm_cozy", "description": None},
                            {"label": "都市摩登", "value": "urban_modern", "description": None},
                        ],
                        "default_value": "summer_cool",
                        "reason": "根据冰咖啡商品描述，季节氛围会影响配色与道具。",
                    }
                ]
            },
            ensure_ascii=False,
        )
    if "agent hint: requirement" in sys or (
        "requirementagent" in sys.replace(" ", "") and "clarification" not in sys
    ):
        return json.dumps(
            {
                "purpose": "推广商品并促进购买",
                "main_subject": "夏季低糖冰咖啡",
                "style": "清新明亮",
                "target_audience": "年轻消费者",
                "aspect_ratio": "1:1",
            },
            ensure_ascii=False,
        )
    if "visualspec" in sys.replace("_", "") or "visual spec" in sys:
        if "academic_figure" in user_prompt:
            return json.dumps(
                {
                    "title": "机器学习方法流程",
                    "style": "学术简洁、白底、标签可读",
                    "purpose": "清晰展示模块关系与处理流程",
                    "key_elements": ["输入模块", "处理模块", "输出模块"],
                },
                ensure_ascii=False,
            )
        return json.dumps(
            {
                "title": "夏季低糖冰咖啡促销图",
                "style": "清新促销风",
                "purpose": "突出商品卖点",
                "key_elements": ["商品主图", "促销标语", "CTA"],
            },
            ensure_ascii=False,
        )
    if "prompt" in sys and "critic" not in sys and "revision" not in sys:
        return json.dumps(
            {"prompt": "Subject: iced coffee. Style: fresh summer promotional banner."},
            ensure_ascii=False,
        )
    if "critic" in sys:
        return json.dumps(
            {"extra_comments": ["API critic note"], "extra_suggestions": ["Add more contrast"]},
            ensure_ascii=False,
        )
    if "revision" in sys:
        return json.dumps(
            {"revised_prompt": "Revised prompt with improved composition and clarity."},
            ensure_ascii=False,
        )
    return json.dumps({"ok": True})


class _FakeResponse:
    def __init__(
        self, data: dict | None = None, content: bytes | None = None, status_code: int = 200
    ):
        self._data = data or {}
        self._content = content or b""
        self.status_code = status_code

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._data

    @property
    def content(self) -> bytes:
        return self._content


class _FakeHttpxClient:
    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def post(self, url, headers=None, json=None, **kwargs):
        url_str = str(url)
        if "chat/completions" in url_str:
            messages = (json or {}).get("messages", [])
            system = next((m["content"] for m in messages if m.get("role") == "system"), "")
            user = next((m["content"] for m in messages if m.get("role") == "user"), "")
            content = _llm_response(system, user)
            return _FakeResponse({"choices": [{"message": {"content": content}}]})
        if "images/generations" in url_str:
            return _FakeResponse({"data": [{"b64_json": TINY_PNG_B64}]})
        raise RuntimeError(f"Unexpected POST in tests: {url}")

    def get(self, url, **kwargs):
        return _FakeResponse(content=base64.b64decode(TINY_PNG_B64))


@pytest.fixture(autouse=True)
def mock_provider_env(monkeypatch):
    """Default test environment: deterministic mock providers, NO API keys.

    This mirrors the shipped ``.env.example`` defaults so the suite proves the
    clone-and-run experience works offline. ``httpx.Client`` is still swapped for
    a fake as a safety net so an accidental real network call fails loudly
    instead of reaching the internet.
    """
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("IMAGE_PROVIDER", "mock")
    monkeypatch.setenv("DEMO_MODE", "false")
    # Empty strings override any key present in a developer's local .env file,
    # keeping the default suite genuinely keyless and offline.
    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "")
    monkeypatch.setenv("IMAGE_API_KEY", "")
    monkeypatch.setenv("VISION_EVALUATOR_PROVIDER", "none")
    get_settings.cache_clear()
    vg_module._graph_instance = None
    svc_module._service = None
    monkeypatch.setattr("httpx.Client", _FakeHttpxClient)
    yield
    get_settings.cache_clear()
    vg_module._graph_instance = None
    svc_module._service = None


@pytest.fixture
def openai_http_env(monkeypatch):
    """Opt-in environment that exercises the OpenAI-compatible API code path.

    Uses mocked ``httpx`` (no real network). Request this fixture explicitly in
    tests that need to verify the provider=openai branch; the default suite runs
    fully on mock providers.
    """
    monkeypatch.setenv("LLM_PROVIDER", "deepseek")
    monkeypatch.setenv("DEMO_MODE", "false")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test-key")
    monkeypatch.setenv("DEEPSEEK_BASE_URL", "https://api.test/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-image-key")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://api.test/v1")
    monkeypatch.setenv("IMAGE_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_IMAGE_MODEL", "gpt-image-1")
    get_settings.cache_clear()
    vg_module._graph_instance = None
    svc_module._service = None
    monkeypatch.setattr("httpx.Client", _FakeHttpxClient)
    yield
    get_settings.cache_clear()
    vg_module._graph_instance = None
    svc_module._service = None
