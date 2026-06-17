"""Diagram generation for academic figures using SVG."""

from __future__ import annotations

from pathlib import Path

from app.config import get_settings
from app.models.schemas import VisualSpec


class DiagramGenerator:
    """Generate SVG flowcharts from VisualSpec key elements."""

    def generate(self, task_id: str, visual_spec: VisualSpec) -> Path:
        """Build a simple SVG flowchart with rectangles and arrows."""
        settings = get_settings()
        settings.diagrams_dir.mkdir(parents=True, exist_ok=True)

        elements = visual_spec.key_elements or ["Input", "Process", "Output"]
        title = visual_spec.title.replace("&", "&amp;").replace("<", "&lt;")
        box_w, box_h, gap = 220, 50, 36
        n = len(elements)
        svg_w = 480
        svg_h = 90 + n * (box_h + gap) + 30
        cx = svg_w // 2

        lines = [
            '<?xml version="1.0" encoding="UTF-8"?>',
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{svg_w}" height="{svg_h}">',
            '<rect width="100%" height="100%" fill="#ffffff"/>',
            f'<text x="{cx}" y="36" text-anchor="middle" font-size="16" '
            f'font-family="sans-serif" font-size="18" fill="#111827">{title}</text>',
            '<defs><marker id="arrow" markerWidth="10" markerHeight="10" '
            'refX="5" refY="3" orient="auto">'
            '<path d="M0,0 L0,6 L9,3 z" fill="#111827"/></marker></defs>',
        ]

        y = 60
        for i, elem in enumerate(elements):
            label = elem[:35].replace("&", "&amp;").replace("<", "&lt;")
            x = cx - box_w // 2
            lines.append(
                f'<rect x="{x}" y="{y}" width="{box_w}" height="{box_h}" '
                f'rx="6" fill="#eef2ff" stroke="#111827" stroke-width="2"/>'
            )
            lines.append(
                f'<text x="{cx}" y="{y + box_h // 2 + 5}" text-anchor="middle" '
                f'font-size="14" font-family="sans-serif" fill="#111827">{label}</text>'
            )
            if i < n - 1:
                ay = y + box_h
                lines.append(
                    f'<line x1="{cx}" y1="{ay}" x2="{cx}" y2="{ay + gap}" '
                    f'stroke="#111827" stroke-width="2" marker-end="url(#arrow)"/>'
                )
            y += box_h + gap

        lines.append("</svg>")

        out_path = settings.diagrams_dir / f"{task_id}_flowchart.svg"
        out_path.write_text("\n".join(lines), encoding="utf-8")
        return out_path

    def generate_png(
        self,
        task_id: str,
        visual_spec: VisualSpec,
        *,
        dest_dir: Path | None = None,
        scale: float = 2.5,
    ) -> Path:
        """Render the same flowchart layout as PNG (GitHub README friendly)."""
        from PIL import Image, ImageDraw, ImageFont

        settings = get_settings()
        out_dir = dest_dir or settings.diagrams_dir
        out_dir.mkdir(parents=True, exist_ok=True)

        elements = visual_spec.key_elements or ["Input", "Process", "Output"]
        title = visual_spec.title or "Academic Figure"
        box_w, box_h, gap = int(220 * scale), int(50 * scale), int(36 * scale)
        n = len(elements)
        svg_w = int(480 * scale)
        svg_h = int(90 * scale) + n * (box_h + gap) + int(30 * scale)
        cx = svg_w // 2

        img = Image.new("RGB", (svg_w, svg_h), "#ffffff")
        draw = ImageDraw.Draw(img)
        try:
            font_title = ImageFont.truetype("arial.ttf", int(18 * scale))
            font_label = ImageFont.truetype("arial.ttf", int(14 * scale))
        except OSError:
            font_title = ImageFont.load_default()
            font_label = font_title

        title_bbox = draw.textbbox((0, 0), title, font=font_title)
        draw.text(
            (cx - (title_bbox[2] - title_bbox[0]) // 2, int(16 * scale)),
            title[:60],
            fill="#111827",
            font=font_title,
        )

        y = int(60 * scale)
        for i, elem in enumerate(elements):
            label = elem[:35]
            x = cx - box_w // 2
            draw.rounded_rectangle(
                [x, y, x + box_w, y + box_h],
                radius=int(6 * scale),
                fill="#eef2ff",
                outline="#111827",
                width=max(2, int(2 * scale)),
            )
            label_bbox = draw.textbbox((0, 0), label, font=font_label)
            draw.text(
                (
                    cx - (label_bbox[2] - label_bbox[0]) // 2,
                    y + box_h // 2 - (label_bbox[3] - label_bbox[1]) // 2,
                ),
                label,
                fill="#111827",
                font=font_label,
            )
            if i < n - 1:
                ay = y + box_h
                draw.line(
                    (cx, ay, cx, ay + gap),
                    fill="#111827",
                    width=max(2, int(2 * scale)),
                )
                tip = ay + gap
                draw.polygon(
                    [
                        (cx, tip),
                        (cx - int(5 * scale), tip - int(8 * scale)),
                        (cx + int(5 * scale), tip - int(8 * scale)),
                    ],
                    fill="#111827",
                )
            y += box_h + gap

        out_path = out_dir / f"{task_id}_flowchart.png"
        img.save(out_path, format="PNG")
        return out_path

    def generate_mermaid_spec(self, visual_spec: VisualSpec) -> str:
        """Return a Mermaid flowchart spec string for academic figures."""
        elements = visual_spec.key_elements or ["Input", "Process", "Output"]
        lines = ["flowchart TD"]
        for i, elem in enumerate(elements):
            node_id = f"N{i}"
            safe = elem.replace('"', "'")[:40]
            lines.append(f'    {node_id}["{safe}"]')
            if i > 0:
                lines.append(f"    N{i - 1} --> {node_id}")
        return "\n".join(lines)
