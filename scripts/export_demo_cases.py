"""Export reproducible end-to-end demo artifacts (mock mode, no API keys).

Writes to examples/demo/{ecommerce,academic,ppt}/:
  request.json, visual_spec.json, prompt.txt, evaluation.json,
  trace.json, summary.json, asset.{png|svg}, README.md
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

os.environ.setdefault("IMAGE_PROVIDER", "mock")
os.environ.setdefault("LLM_PROVIDER", "mock")
os.environ.setdefault("DEMO_MODE", "true")

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import get_settings
from app.graph import visionflow_graph as vg_module
from app.models.database import Base
from app.models.schemas import GenerationRequest
from app.services import generation_service as svc_module
from app.services.generation_service import GenerationService

OUT_ROOT = ROOT / "examples" / "demo"

CASES = [
    {
        "dir": "ecommerce",
        "label": "E-commerce product visual",
        "json": ROOT / "examples" / "ecommerce_case.json",
        "skip_clarification": True,
    },
    {
        "dir": "academic",
        "label": "Academic diagram (SVG)",
        "json": ROOT / "examples" / "academic_case.json",
        "skip_clarification": True,
        "task_type": "academic_figure",
    },
    {
        "dir": "ppt",
        "label": "Presentation visual",
        "json": ROOT / "examples" / "ppt_case.json",
        "skip_clarification": True,
    },
]


def _reset() -> None:
    get_settings.cache_clear()
    vg_module._graph_instance = None
    svc_module._service = None


def _export_one(service: GenerationService, session, case: dict) -> None:
    raw = json.loads(case["json"].read_text(encoding="utf-8"))
    out_dir = OUT_ROOT / case["dir"]
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)

    req = GenerationRequest(
        user_input=raw["user_input"],
        task_type=case.get("task_type", raw.get("task_type", "auto")),
        style_preference=raw.get("style_preference"),
        target_audience=raw.get("target_audience"),
        aspect_ratio=raw.get("aspect_ratio"),
        enable_revision=False,
        skip_clarification=case.get("skip_clarification", True),
    )
    (out_dir / "request.json").write_text(
        req.model_dump_json(indent=2), encoding="utf-8"
    )

    result = service.run_generation(session, req)
    src = Path(result.output_path)
    ext = src.suffix or ".png"
    asset_name = f"asset{ext}"
    if src.exists():
        shutil.copy2(src, out_dir / asset_name)

    (out_dir / "visual_spec.json").write_text(
        result.visual_spec.model_dump_json(indent=2), encoding="utf-8"
    )
    (out_dir / "prompt.txt").write_text(result.prompt, encoding="utf-8")
    (out_dir / "evaluation.json").write_text(
        result.evaluation.model_dump_json(indent=2), encoding="utf-8"
    )
    (out_dir / "trace.json").write_text(
        json.dumps([t.model_dump() for t in result.traces], indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    summary = {
        "task_id": result.task_id,
        "task_type": result.task_type,
        "route_reason": result.route_reason,
        "asset_file": asset_name,
        "output_path_original": result.output_path,
        "overall_score": result.evaluation.overall_score,
        "offline_score": result.evaluation.offline_score,
        "provider_mode": "mock",
        "pipeline_steps": [
            t.metadata.get("pipeline_step")
            for t in result.traces
            if t.metadata.get("pipeline_step")
        ],
    }
    (out_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    readme = f"""# Demo: {case["label"]}

Generated offline with `IMAGE_PROVIDER=mock` (deterministic, no API key).

| File | Description |
|------|-------------|
| `request.json` | Input to `/generate` |
| `visual_spec.json` | Structured Visual Spec |
| `prompt.txt` | Final generation prompt |
| `{asset_name}` | Generated asset (mock PNG or local SVG) |
| `evaluation.json` | Heuristic rubric evaluation (not human/VLM judgment) |
| `trace.json` | Agent trace timeline |
| `summary.json` | Quick overview |

Reproduce:

```bash
python benchmark.py --demo examples/{case["json"].name}
```
"""
    (out_dir / "README.md").write_text(readme, encoding="utf-8")
    print(f"Exported {out_dir} (score={result.evaluation.overall_score})")


def main() -> int:
    _reset()
    settings = get_settings()
    settings.ensure_dirs()

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    service = GenerationService()

    for case in CASES:
        _export_one(service, session, case)

    session.close()
    print(f"\nDone → {OUT_ROOT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
