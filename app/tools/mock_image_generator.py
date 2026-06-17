"""Deterministic offline image provider for demo and test mode."""

from __future__ import annotations

import hashlib
import json
import struct
import zlib
from pathlib import Path

from app.config import get_settings
from app.tools.aspect_ratio import resolve_aspect_ratio


def _png_chunk(chunk_type: bytes, data: bytes) -> bytes:
    crc = zlib.crc32(chunk_type + data) & 0xFFFFFFFF
    return struct.pack(">I", len(data)) + chunk_type + data + struct.pack(">I", crc)


def _solid_png(width: int, height: int, rgb: tuple[int, int, int]) -> bytes:
    """Build a minimal valid PNG without external dependencies."""
    raw_rows = []
    r, g, b = rgb
    row = bytes([0, r, g, b] * width)
    for _ in range(height):
        raw_rows.append(row)
    compressed = zlib.compress(b"".join(raw_rows), 9)
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", ihdr)
        + _png_chunk(b"IDAT", compressed)
        + _png_chunk(b"IEND", b"")
    )


class MockImageGenerator:
    """Generate deterministic placeholder PNGs with embedded metadata sidecar."""

    provider_name = "mock"
    mode = "mock"

    def generate(
        self,
        task_id: str,
        task_type: str,
        title: str,
        prompt: str,
        aspect_ratio: str = "1:1",
    ) -> Path:
        settings = get_settings()
        settings.generated_dir.mkdir(parents=True, exist_ok=True)
        out_path = settings.generated_dir / f"{task_id}_{task_type}.png"
        meta_path = settings.generated_dir / f"{task_id}_{task_type}.mock.json"

        resolution = resolve_aspect_ratio(aspect_ratio)
        digest = hashlib.sha256(f"{task_id}:{task_type}:{title}".encode()).hexdigest()
        hue = int(digest[:6], 16) % 200
        rgb = (40 + hue % 80, 80 + (hue // 2) % 80, 120 + hue % 60)

        png_bytes = _solid_png(resolution.width, resolution.height, rgb)
        out_path.write_bytes(png_bytes)

        meta = {
            "provider": self.provider_name,
            "mode": self.mode,
            "task_id": task_id,
            "task_type": task_type,
            "title": title,
            "prompt_preview": prompt[:200],
            "requested_aspect_ratio": resolution.requested_ratio,
            "resolved_width": resolution.width,
            "resolved_height": resolution.height,
            "ideal_width": resolution.ideal_width,
            "ideal_height": resolution.ideal_height,
            "aspect_ratio": resolution.requested_ratio,
            "normalized_size": resolution.size,
            "width": resolution.width,
            "height": resolution.height,
            "orientation": resolution.orientation,
            "normalized": resolution.normalized,
            "normalization_reason": resolution.normalization_reason,
            "visible_label": f"MOCK::{task_type}::{title[:40]}",
        }
        meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
        return out_path
