"""Render README academic showcase images as PNG (GitHub displays PNG reliably)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.models.schemas import VisualSpec
from app.tools.diagram_generator import DiagramGenerator

OUT_DIR = ROOT / "docs" / "images" / "examples"
MANIFEST = OUT_DIR / "manifest.json"

SHOWCASE: dict[str, dict] = {
    "academic_pipeline": {
        "title": "五阶段机器学习方法流水线图",
        "key_elements": [
            "数据预处理",
            "特征提取",
            "双分支网络",
            "特征融合",
            "分类输出",
        ],
        "aspect_ratio": "4:3",
    },
    "acad_graphical": {
        "title": "编码器-解码器架构数据流管道图",
        "key_elements": ["输入序列", "Encoder", "Context", "Decoder", "输出序列"],
        "aspect_ratio": "16:9",
    },
    "acad_cv_pipeline": {
        "title": "计算机视觉实验pipeline示意图",
        "key_elements": [
            "数据增强",
            "Backbone",
            "特征池化",
            "分类头",
            "Softmax 输出",
        ],
        "aspect_ratio": "4:3",
    },
}


def main() -> int:
    gen = DiagramGenerator()
    items: list[dict] = []
    if MANIFEST.exists():
        items = json.loads(MANIFEST.read_text(encoding="utf-8")).get("items", [])

    for slug, spec_data in SHOWCASE.items():
        vs = VisualSpec(
            task_type="academic_figure",
            title=spec_data["title"],
            scenario="学术论文方法说明",
            target_audience="研究人员",
            purpose="清晰展示模块关系与处理流程",
            style="学术简洁、白底、标签可读",
            main_subject=spec_data["title"],
            key_elements=spec_data["key_elements"],
            aspect_ratio=spec_data["aspect_ratio"],
            output_format="png",
            text_requirements=["模块标签", "数据流向"],
            constraints=["箭头方向明确"],
            avoid=["过度装饰"],
            evaluation_dimensions=["模块关系", "流程逻辑"],
        )
        png_path = gen.generate_png(slug, vs, dest_dir=OUT_DIR, scale=2.8)
        dest = OUT_DIR / f"{slug}.png"
        if png_path != dest:
            dest.write_bytes(png_path.read_bytes())
            png_path.unlink(missing_ok=True)

        stale_svg = OUT_DIR / f"{slug}.svg"
        if stale_svg.exists():
            stale_svg.unlink()

        updated = False
        for item in items:
            if item.get("slug") == slug:
                item["file"] = f"examples/{slug}.png"
                item["format"] = "png"
                item["provider"] = "diagram_generator_png"
                item["title"] = spec_data["title"]
                item["aspect_ratio"] = spec_data["aspect_ratio"]
                updated = True
                break
        if not updated:
            items.append(
                {
                    "slug": slug,
                    "file": f"examples/{slug}.png",
                    "featured": slug == "academic_pipeline",
                    "caption": spec_data["title"],
                    "task_type": "academic_figure",
                    "aspect_ratio": spec_data["aspect_ratio"],
                    "format": "png",
                    "title": spec_data["title"],
                    "provider": "diagram_generator_png",
                }
            )
        print(f"Rendered {dest.name}")

    if MANIFEST.exists():
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        manifest["items"] = items
        MANIFEST.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
