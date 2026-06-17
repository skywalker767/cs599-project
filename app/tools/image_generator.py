"""OpenAI-compatible image generation via API."""

from __future__ import annotations

import base64
import json
import logging
import time
from pathlib import Path

from app.config import get_settings
from app.tools.aspect_ratio import resolve_aspect_ratio

logger = logging.getLogger(__name__)

_RETRYABLE_STATUS = {429, 502, 503, 524}
_MAX_ATTEMPTS = 3


class ImageProviderError(RuntimeError):
    """Raised when image API is missing or misconfigured."""


def _compact_image_prompt(prompt: str, title: str, max_len: int = 800) -> str:
    """Keep image prompts concise to reduce gateway timeouts."""
    text = " ".join(prompt.split())
    if len(text) <= max_len:
        return text
    head = text[: max_len // 2]
    tail = text[-(max_len // 2) :]
    return f"{title}. {head} ... {tail}"[:max_len]


class OpenAIImageGenerator:
    """Generate images via OpenAI-compatible /v1/images/generations."""

    provider_name = "openai"
    mode = "real"

    def generate(
        self,
        task_id: str,
        task_type: str,
        title: str,
        prompt: str,
        aspect_ratio: str = "1:1",
    ) -> Path:
        settings = get_settings()
        api_key = (settings.image_api_key or settings.openai_api_key).strip()
        if not api_key:
            raise ImageProviderError(
                "Image API key required. Set IMAGE_API_KEY or OPENAI_API_KEY in .env"
            )

        provider = (settings.image_provider or "openai").lower().strip()
        if provider == "mock":
            raise ImageProviderError(
                "Use get_image_generator() for mock provider; OpenAIImageGenerator is API-only."
            )
        if provider != "openai":
            raise ImageProviderError(f"Unknown IMAGE_PROVIDER='{provider}'. Supported: openai")

        try:
            import httpx
        except ImportError as exc:
            raise RuntimeError("httpx not installed") from exc

        http_timeout = httpx.Timeout(30.0, read=300.0)
        base = settings.openai_base_url.rstrip("/")
        url = f"{base}/images/generations"
        models = self._model_candidates(settings.openai_image_model or "gpt-image-1")

        settings.generated_dir.mkdir(parents=True, exist_ok=True)
        out_path = settings.generated_dir / f"{task_id}_{task_type}.png"

        last_error: Exception | None = None
        image_prompt = _compact_image_prompt(prompt, title)

        for attempt in range(_MAX_ATTEMPTS):
            resolution = resolve_aspect_ratio(aspect_ratio)
            size = resolution.size
            if attempt > 0:
                image_prompt = _compact_image_prompt(prompt, title, max_len=500)
                size = "1024x1024"
                time.sleep(3 * attempt)

            for model in models:
                try:
                    image_bytes = self._request_image(
                        httpx,
                        http_timeout,
                        url,
                        api_key,
                        model,
                        image_prompt,
                        size,
                    )
                    out_path.write_bytes(image_bytes)
                    meta_path = out_path.with_suffix(".openai.json")
                    meta_path.write_text(
                        json.dumps(
                            {
                                "provider": self.provider_name,
                                "requested_aspect_ratio": resolution.requested_ratio,
                                "resolved_width": resolution.width,
                                "resolved_height": resolution.height,
                                "ideal_width": resolution.ideal_width,
                                "ideal_height": resolution.ideal_height,
                                "api_size": resolution.size,
                                "normalized": resolution.normalized,
                                "normalization_reason": resolution.normalization_reason,
                                "model": model,
                            },
                            indent=2,
                            ensure_ascii=False,
                        ),
                        encoding="utf-8",
                    )
                    logger.info(
                        "Image saved via API: %s (model=%s, attempt=%s)",
                        out_path,
                        model,
                        attempt + 1,
                    )
                    return out_path
                except ImageProviderError as exc:
                    last_error = exc
                    if self._is_retryable(exc):
                        logger.warning(
                            "Image API retryable error (model=%s, attempt=%s): %s",
                            model,
                            attempt + 1,
                            exc,
                        )
                        continue
                    raise

        raise ImageProviderError(
            f"Image generation failed after {_MAX_ATTEMPTS} attempts: {last_error}"
        )

    @staticmethod
    def _model_candidates(primary: str) -> list[str]:
        models = [primary.strip(), "gpt-image-2", "gpt-image-1"]
        seen: list[str] = []
        for m in models:
            if m and m not in seen:
                seen.append(m)
        return seen

    @staticmethod
    def _is_retryable(exc: ImageProviderError) -> bool:
        msg = str(exc)
        return any(
            f" {code} " in f" {msg} " or f"({code})" in msg for code in _RETRYABLE_STATUS
        ) or ("timeout" in msg.lower() or "524" in msg)

    @staticmethod
    def _request_image(
        httpx_module,
        http_timeout,
        url: str,
        api_key: str,
        model: str,
        prompt: str,
        size: str,
    ) -> bytes:
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": model,
            "prompt": prompt[:2000],
            "n": 1,
            "size": size,
        }

        with httpx_module.Client(timeout=http_timeout) as client:
            resp = client.post(url, headers=headers, json=payload)
            if resp.status_code >= 400:
                detail = resp.text[:500]
                raise ImageProviderError(f"Image API {resp.status_code} (model={model}): {detail}")
            data = resp.json()

        item = (data.get("data") or [{}])[0]
        if item.get("b64_json"):
            return base64.b64decode(item["b64_json"])
        if item.get("url"):
            with httpx_module.Client(timeout=http_timeout) as client:
                img_resp = client.get(item["url"])
                img_resp.raise_for_status()
                return img_resp.content
        raise ImageProviderError("Image API returned no url or b64_json")
