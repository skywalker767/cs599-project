"""Generate showcase assets for README via the full generation pipeline."""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.database import Base
from app.models.schemas import ClarificationAnswer, GenerationRequest
from app.services.generation_service import GenerationService

EXAMPLES_DIR = _PROJECT_ROOT / "examples"
OUT_DIR = _PROJECT_ROOT / "docs" / "images" / "examples"

CASES: list[dict] = [
    {
        "slug": "ecommerce_coffee",
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
        "json": "academic_case.json",
        "answers": [
            ("output_format", "png"),
            ("figure_type", "method_pipeline"),
            ("academic_style", "journal_clean"),
            ("structure_complexity", "medium"),
        ],
    },
    {
        "slug": "ppt_cover",
        "json": "ppt_case.json",
        "answers": [
            ("slide_position", "cover"),
            ("presentation_context", "course_defense"),
            ("layout_blank", "left"),
            ("visual_strength", "strong"),
        ],
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


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    service = GenerationService()
    session = _db_session()
    manifest: list[dict] = []

    for case in CASES:
        slug = case["slug"]
        raw = _load_case(EXAMPLES_DIR / case["json"])
        answers = [
            ClarificationAnswer(question_id=qid, selected_value=val) for qid, val in case["answers"]
        ]
        request = GenerationRequest(
            user_input=raw["user_input"],
            task_type=raw.get("task_type", "auto"),
            style_preference=raw.get("style_preference"),
            target_audience=raw.get("target_audience"),
            aspect_ratio=raw.get("aspect_ratio"),
            enable_revision=False,
            clarification_answers=answers,
            skip_clarification=False,
        )
        print(f"\n=== Generating: {slug} ===")
        result = service.run_generation(session, request)
        src = Path(result.output_path)
        if not src.exists():
            raise FileNotFoundError(f"Asset missing for {slug}: {result.output_path}")

        ext = _ext_for(src)
        dest = OUT_DIR / f"{slug}{ext}"
        shutil.copy2(src, dest)
        print(f"Saved: {dest} (score={result.evaluation.overall_score})")

        manifest.append(
            {
                "slug": slug,
                "file": f"examples/{slug}{ext}",
                "task_type": result.task_type,
                "score": result.evaluation.overall_score,
                "title": result.visual_spec.title,
            }
        )

    (OUT_DIR / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print("\nDone. Manifest written to docs/images/examples/manifest.json")


if __name__ == "__main__":
    main()
