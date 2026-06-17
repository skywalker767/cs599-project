"""Configuration consistency tests.

Guarantees that ``.env.example``, the ``Settings`` defaults and the documented
clone-and-run behaviour stay in sync so a fresh checkout works offline.
"""

from __future__ import annotations

from pathlib import Path

from app.config import Settings

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_EXAMPLE = PROJECT_ROOT / ".env.example"


def _parse_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip()
    return values


def test_env_example_exists():
    assert ENV_EXAMPLE.exists(), ".env.example must ship with the repo"


def test_env_example_defaults_to_mock():
    env = _parse_env(ENV_EXAMPLE)
    assert env.get("LLM_PROVIDER") == "mock"
    assert env.get("IMAGE_PROVIDER") == "mock"


def test_env_example_has_no_baked_in_keys():
    env = _parse_env(ENV_EXAMPLE)
    for key in ("OPENAI_API_KEY", "DEEPSEEK_API_KEY", "IMAGE_API_KEY"):
        assert env.get(key, "") == "", f"{key} must be blank in .env.example"


def test_settings_field_defaults_match_env_example():
    """Settings class defaults (no env) must also be the mock providers."""
    fields = Settings.model_fields
    assert fields["llm_provider"].default == "mock"
    assert fields["image_provider"].default == "mock"


def test_env_example_vision_evaluator_off_by_default():
    env = _parse_env(ENV_EXAMPLE)
    assert env.get("VISION_EVALUATOR_PROVIDER", "none") == "none"
