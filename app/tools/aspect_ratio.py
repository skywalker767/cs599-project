"""Aspect-ratio to image size mapping with normalization metadata.

OpenAI-compatible image APIs (gpt-image-1 / gpt-image-2) only accept a small set
of discrete sizes. We first map each requested ratio to an *ideal* pixel size,
then snap to the closest API-supported size via ``_API_SIZE_MAP``.

Ideal sizes (design intent):
  1:1 -> 1024x1024 | 16:9 -> 1536x864 | 9:16 -> 864x1536
  4:3 -> 1280x960  | 3:4 -> 960x1280  | 4:5 -> 1024x1280
  A4 portrait -> 1024x1448 | A4 landscape -> 1448x1024

API-supported sizes (gpt-image-1 style):
  1024x1024, 1792x1024, 1024x1792, 1536x1024, 1024x1536
"""

from __future__ import annotations

from dataclasses import dataclass

# Provider-accepted size strings -> (width, height)
_SUPPORTED_SIZES: dict[str, tuple[int, int]] = {
    "1024x1024": (1024, 1024),
    "1792x1024": (1792, 1024),
    "1024x1792": (1024, 1792),
    "1536x1024": (1536, 1024),
    "1024x1536": (1024, 1536),
}

# Design-intent ideal dimensions per normalized ratio key
_IDEAL_DIMENSIONS: dict[str, tuple[int, int]] = {
    "1:1": (1024, 1024),
    "16:9": (1536, 864),
    "9:16": (864, 1536),
    "4:3": (1280, 960),
    "3:4": (960, 1280),
    "4:5": (1024, 1280),
    "a4": (1024, 1448),
    "a4_portrait": (1024, 1448),
    "a4_landscape": (1448, 1024),
}

# Closest API size per ratio (may differ from ideal – documented in normalization_reason)
_ASPECT_TO_API_SIZE: dict[str, str] = {
    "1:1": "1024x1024",
    "16:9": "1792x1024",
    "9:16": "1024x1792",
    "4:3": "1536x1024",
    "3:4": "1024x1536",
    "4:5": "1024x1536",
    "a4": "1024x1536",
    "a4_portrait": "1024x1536",
    "a4_landscape": "1536x1024",
}


@dataclass(frozen=True)
class AspectRatioResolution:
    requested_ratio: str
    normalized_ratio: str
    size: str
    width: int
    height: int
    ideal_width: int
    ideal_height: int
    orientation: str
    normalized: bool
    normalization_reason: str | None = None


def _normalize_ratio_key(aspect_ratio: str) -> str:
    key = (aspect_ratio or "1:1").strip().lower().replace(" ", "_")
    aliases = {
        "a4": "a4_portrait",
        "a4-portrait": "a4_portrait",
        "a4-landscape": "a4_landscape",
    }
    return aliases.get(key, key)


def _orientation_from_size(size: str) -> str:
    w, h = _SUPPORTED_SIZES.get(size, (1024, 1024))
    if w == h:
        return "square"
    return "landscape" if w > h else "portrait"


def _closest_api_size(target_w: int, target_h: int) -> str:
    target_ratio = target_w / max(target_h, 1)
    best_size = "1024x1024"
    best_delta = float("inf")
    for size, (w, h) in _SUPPORTED_SIZES.items():
        delta = abs((w / h) - target_ratio)
        if delta < best_delta:
            best_delta = delta
            best_size = size
    return best_size


def resolve_aspect_ratio(aspect_ratio: str = "1:1") -> AspectRatioResolution:
    """Map a requested aspect ratio to the closest supported provider size."""
    key = _normalize_ratio_key(aspect_ratio)
    ideal_w, ideal_h = _IDEAL_DIMENSIONS.get(key, (1024, 1024))

    if key in _ASPECT_TO_API_SIZE:
        api_size = _ASPECT_TO_API_SIZE[key]
        w, h = _SUPPORTED_SIZES[api_size]
        normalized = (w, h) != (ideal_w, ideal_h)
        reason = None
        if normalized:
            reason = (
                f"ideal {ideal_w}x{ideal_h} snapped to API size {api_size} "
                f"(provider supports {_SUPPORTED_SIZES.keys()})"
            )
        return AspectRatioResolution(
            requested_ratio=aspect_ratio or "1:1",
            normalized_ratio=key,
            size=api_size,
            width=w,
            height=h,
            ideal_width=ideal_w,
            ideal_height=ideal_h,
            orientation=_orientation_from_size(api_size),
            normalized=normalized,
            normalization_reason=reason,
        )

    # Unknown ratio: pick closest API size by numeric aspect ratio
    def _ratio_value(r: str) -> float:
        if ":" in r:
            a, b = r.split(":", 1)
            try:
                return float(a) / float(b)
            except ValueError:
                return 1.0
        return 1.0

    target = _ratio_value(aspect_ratio.replace("x", ":") if "x" in aspect_ratio else aspect_ratio)
    best_size = _closest_api_size(int(target * 1024), 1024)
    w, h = _SUPPORTED_SIZES[best_size]
    return AspectRatioResolution(
        requested_ratio=aspect_ratio or "1:1",
        normalized_ratio=aspect_ratio or "1:1",
        size=best_size,
        width=w,
        height=h,
        ideal_width=int(target * 1024),
        ideal_height=1024,
        orientation=_orientation_from_size(best_size),
        normalized=True,
        normalization_reason=(
            f"unsupported ratio '{aspect_ratio}' mapped to closest API size {best_size}"
        ),
    )
