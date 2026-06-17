"""Quick offline demo – one generation in mock mode."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Ensure mock mode unless caller overrides
os.environ.setdefault("IMAGE_PROVIDER", "mock")
os.environ.setdefault("LLM_PROVIDER", "mock")
os.environ.setdefault("DEMO_MODE", "true")

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import get_settings
from app.models.database import Base
from app.models.schemas import GenerationRequest
from app.services.generation_service import GenerationService


def main() -> int:
    settings = get_settings()
    settings.ensure_dirs()
    db_path = settings.storage_root / "demo_run.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    db = sessionmaker(bind=engine)()

    service = GenerationService()
    req = GenerationRequest(
        user_input="为夏季冰咖啡制作电商促销主图 banner，突出商品与限时优惠",
        task_type="auto",
        aspect_ratio="1:1",
        skip_clarification=True,
        enable_revision=False,
    )
    result = service.run_generation(db, req)
    db.close()

    summary = {
        "task_id": result.task_id,
        "task_type": result.task_type,
        "output_path": result.output_path,
        "overall_score": result.evaluation.overall_score,
        "offline_score": result.evaluation.offline_score,
        "image_provider": settings.image_provider,
        "llm_provider": settings.llm_provider,
        "pipeline_steps": [
            t.metadata.get("pipeline_step")
            for t in result.traces
            if t.metadata.get("pipeline_step")
        ],
    }
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    print(f"\nDemo complete. Open output: {result.output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
