"""Generate README showcase assets via the full generation pipeline.

Uses configured providers from ``.env`` (typically ``IMAGE_PROVIDER=openai`` for
real PNGs). Academic SVG flowcharts are rendered locally by ``DiagramGenerator``.

Outputs:
  docs/images/examples/<slug>.{png|svg}
  docs/images/examples/manifest.json
"""

from __future__ import annotations

import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import get_settings
from app.graph import visionflow_graph as vg_module
from app.models.database import Base
from app.models.schemas import ClarificationAnswer, GenerationRequest
from app.services import generation_service as svc_module
from app.services.generation_service import GenerationService

EXAMPLES_DIR = _PROJECT_ROOT / "examples"
OUT_DIR = _PROJECT_ROOT / "docs" / "images" / "examples"

ACAD_PNG_ANSWERS: list[tuple[str, str]] = [
    ("output_format", "png"),
    ("figure_type", "method_pipeline"),
    ("academic_style", "journal_clean"),
    ("structure_complexity", "medium"),
]

# Featured: rich prompts from examples/*.json with clarification answers.
# Extended: benchmark-style cases for breadth without huge README.
# Academic cases use PNG (GitHub README renders PNG reliably; SVG often fails).
SHOWCASE_CASES: list[dict] = [
    {
        "slug": "ecommerce_coffee",
        "featured": True,
        "caption": "冰咖啡小红书促销主图",
        "json": "ecommerce_case.json",
        "answers": [
            ("style", "fresh_natural"),
            ("aspect_ratio", "1:1"),
            ("platform", "xiaohongshu"),
            ("compliance_level", "standard"),
        ],
    },
    {
        "slug": "academic_pipeline",
        "featured": True,
        "caption": "五阶段双分支网络方法流程图",
        "json": "academic_case.json",
        "answers": ACAD_PNG_ANSWERS,
    },
    {
        "slug": "ppt_cover",
        "featured": True,
        "caption": "AI 驱动软件开发课程封面",
        "json": "ppt_case.json",
        "answers": [
            ("slide_position", "cover"),
            ("presentation_context", "course_defense"),
            ("layout_blank", "left"),
            ("visual_strength", "strong"),
        ],
    },
    {
        "slug": "ecom_skincare",
        "featured": False,
        "caption": "双11护肤品详情页头图",
        "user_input": "双11护肤品详情页头图，电商主图 product sale discount，突出促销价与购物车 CTA",
        "aspect_ratio": "4:5",
        "skip_clarification": True,
    },
    {
        "slug": "ecom_sneakers",
        "featured": False,
        "caption": "运动鞋新品科技缓震广告",
        "user_input": "运动鞋新品上市电商广告图 banner，强调科技缓震卖点与购买引导",
        "aspect_ratio": "16:9",
        "skip_clarification": True,
    },
    {
        "slug": "acad_graphical",
        "featured": False,
        "caption": "NLP Encoder-Decoder 图形摘要",
        "user_input": "为 NLP 论文生成 graphical abstract，展示 encoder-decoder 架构与数据流 pipeline diagram，学术期刊风格流程图",
        "aspect_ratio": "16:9",
        "task_type": "academic_figure",
        "answers": [
            ("output_format", "png"),
            ("figure_type", "graphical_abstract"),
            ("academic_style", "journal_clean"),
            ("structure_complexity", "medium"),
        ],
    },
    {
        "slug": "acad_cv_pipeline",
        "featured": False,
        "caption": "计算机视觉实验 pipeline",
        "user_input": "计算机视觉实验 pipeline 示意图，数据增强到分类输出，学术 framework diagram，模块箭头清晰",
        "aspect_ratio": "4:3",
        "task_type": "academic_figure",
        "answers": [
            ("output_format", "png"),
            ("figure_type", "experiment_workflow"),
            ("academic_style", "journal_clean"),
            ("structure_complexity", "medium"),
        ],
    },
    {
        "slug": "ppt_business",
        "featured": False,
        "caption": "商业增长复盘章节页",
        "user_input": "商业增长复盘章节页配图 presentation slide，简洁商务汇报风格，数据感与留白",
        "aspect_ratio": "16:9",
        "skip_clarification": True,
    },
    {
        "slug": "ppt_infographic",
        "featured": False,
        "caption": "气候变化科普信息图",
        "user_input": "气候变化教育信息图 infographic，面向中学生科普，三个核心要点与图示",
        "aspect_ratio": "9:16",
        "skip_clarification": True,
    },
]


def _db_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)()


def _load_case(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _ext_for(path: Path) -> str:
    return path.suffix.lower() or ".png"


def _reset_singletons() -> None:
    get_settings.cache_clear()
    vg_module._graph_instance = None
    svc_module._service = None


def _build_request(case: dict) -> GenerationRequest:
    if "json" in case:
        raw = _load_case(EXAMPLES_DIR / case["json"])
        answers = [
            ClarificationAnswer(question_id=qid, selected_value=val)
            for qid, val in case.get("answers", [])
        ]
        return GenerationRequest(
            user_input=raw["user_input"],
            task_type=raw.get("task_type", "auto"),
            style_preference=raw.get("style_preference"),
            target_audience=raw.get("target_audience"),
            aspect_ratio=raw.get("aspect_ratio"),
            enable_revision=False,
            clarification_answers=answers,
            skip_clarification=case.get("skip_clarification", False),
        )
    answers = [
        ClarificationAnswer(question_id=qid, selected_value=val)
        for qid, val in case.get("answers", [])
    ]
    return GenerationRequest(
        user_input=case["user_input"],
        task_type=case.get("task_type", "auto"),
        aspect_ratio=case.get("aspect_ratio"),
        enable_revision=False,
        clarification_answers=answers,
        skip_clarification=case.get("skip_clarification", not answers),
    )


def _enhance_mock_png(path: Path, title: str, task_type: str, subtitle: str) -> None:
    """Label mock placeholders only — never overlay real API images."""
    import io

    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        return

    img = Image.open(io.BytesIO(path.read_bytes())).convert("RGB")
    draw = ImageDraw.Draw(img)
    w, h = img.size
    overlay_h = max(100, h // 7)
    draw.rectangle([0, 0, w, overlay_h], fill=(15, 23, 42))
    try:
        font_l = ImageFont.truetype("arial.ttf", 24)
        font_s = ImageFont.truetype("arial.ttf", 16)
    except OSError:
        font_l = ImageFont.load_default()
        font_s = font_l
    draw.text((20, 16), title[:40], fill="white", font=font_l)
    draw.text((20, 48), f"{task_type} · {subtitle} · mock", fill="#94a3b8", font=font_s)
    img.save(path)


def _cleanup_stale_assets(keep_slugs: set[str]) -> None:
    for path in OUT_DIR.iterdir():
        if not path.is_file():
            continue
        if path.name == "manifest.json":
            continue
        stem = path.stem
        if stem not in keep_slugs:
            path.unlink()


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Generate README showcase images")
    parser.add_argument(
        "--only",
        help="Comma-separated slugs to regenerate (e.g. academic_pipeline,acad_graphical)",
    )
    args = parser.parse_args()
    only_slugs: set[str] | None = None
    if args.only:
        only_slugs = {s.strip() for s in args.only.split(",") if s.strip()}

    _reset_singletons()
    settings = get_settings()
    provider = (settings.image_provider or "mock").lower()
    llm = (settings.llm_provider or "mock").lower()
    is_mock_image = provider == "mock" or settings.demo_mode

    print(f"Image provider: {provider} | LLM: {llm} | mock_image={is_mock_image}")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    service = GenerationService()
    session = _db_session()

    cases = SHOWCASE_CASES
    if only_slugs:
        cases = [c for c in SHOWCASE_CASES if c["slug"] in only_slugs]
        if not cases:
            print(f"No matching slugs in: {args.only}")
            return

    # Merge with existing manifest when regenerating a subset
    manifest_path = OUT_DIR / "manifest.json"
    existing_items: list[dict] = []
    if only_slugs and manifest_path.exists():
        existing_items = json.loads(manifest_path.read_text(encoding="utf-8")).get("items", [])
        existing_items = [i for i in existing_items if i["slug"] not in only_slugs]

    items: list[dict] = list(existing_items)
    keep_slugs = {c["slug"] for c in SHOWCASE_CASES}

    for case in cases:
        slug = case["slug"]
        print(f"\n=== [{len(items)+1}/{len(existing_items)+len(cases)}] {slug} ===")
        try:
            result = service.run_generation(session, _build_request(case))
        except Exception as exc:
            print(f"FAILED {slug}: {exc}")
            continue

        src = Path(result.output_path)
        if not src.exists():
            print(f"FAILED {slug}: missing {src}")
            continue

        ext = _ext_for(src)
        dest = OUT_DIR / f"{slug}{ext}"
        shutil.copy2(src, dest)
        for stale in OUT_DIR.glob(f"{slug}.*"):
            if stale != dest and stale.is_file():
                stale.unlink()

        if ext == ".png" and is_mock_image:
            _enhance_mock_png(
                dest,
                result.visual_spec.title or case.get("caption", slug),
                result.task_type,
                result.visual_spec.aspect_ratio or "",
            )

        meta = {
            "slug": slug,
            "file": f"examples/{slug}{ext}",
            "featured": case.get("featured", False),
            "caption": case.get("caption", result.visual_spec.title),
            "task_type": result.task_type,
            "aspect_ratio": result.visual_spec.aspect_ratio,
            "format": ext.lstrip("."),
            "title": result.visual_spec.title,
            "score": result.evaluation.overall_score,
            "provider": provider if ext == ".png" else "diagram_generator",
        }
        items.append(meta)
        print(f"Saved: {dest.name} score={meta['score']} format={meta['format']}")

    _cleanup_stale_assets(keep_slugs)
    items.sort(
        key=lambda i: next(
            idx for idx, c in enumerate(SHOWCASE_CASES) if c["slug"] == i["slug"]
        )
    )

    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "image_provider": provider,
        "llm_provider": llm,
        "count": len(items),
        "items": items,
    }
    (OUT_DIR / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\nDone: {len(items)} assets → {OUT_DIR / 'manifest.json'}")


if __name__ == "__main__":
    main()
