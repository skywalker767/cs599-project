#!/usr/bin/env python3
"""Spec2Vision CLI: run a single demo case or the benchmark suite.

Examples:
  python benchmark.py --demo examples/ecommerce_case.json
  python benchmark.py --benchmark
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

# Default offline reproducibility for teachers / CI-like local runs
os.environ.setdefault("IMAGE_PROVIDER", "mock")
os.environ.setdefault("LLM_PROVIDER", "mock")
os.environ.setdefault("DEMO_MODE", "true")


def _run_demo(case_path: Path) -> int:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from app.config import get_settings
    from app.graph import visionflow_graph as vg_module
    from app.models.database import Base
    from app.models.schemas import GenerationRequest
    from app.services import generation_service as svc_module
    from app.services.generation_service import GenerationService

    get_settings.cache_clear()
    vg_module._graph_instance = None
    svc_module._service = None

    raw = json.loads(case_path.read_text(encoding="utf-8"))
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    db = sessionmaker(bind=engine)()

    req = GenerationRequest(
        user_input=raw["user_input"],
        task_type=raw.get("task_type", "auto"),
        style_preference=raw.get("style_preference"),
        target_audience=raw.get("target_audience"),
        aspect_ratio=raw.get("aspect_ratio"),
        enable_revision=raw.get("enable_revision", False),
        skip_clarification=True,
    )
    result = GenerationService().run_generation(db, req)
    db.close()

    print(
        json.dumps(
            {
                "task_id": result.task_id,
                "task_type": result.task_type,
                "output_path": result.output_path,
                "overall_score": result.evaluation.overall_score,
                "offline_score": result.evaluation.offline_score,
                "image_provider": get_settings().image_provider,
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    print(f"\nAsset: {result.output_path}")
    return 0


def _run_benchmark() -> int:
    from app.tools.benchmark import run_benchmark

    report = run_benchmark(save=True)
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Spec2Vision demo & benchmark CLI")
    parser.add_argument(
        "--demo",
        metavar="CASE_JSON",
        type=Path,
        help="Run one example case through the full pipeline (mock by default)",
    )
    parser.add_argument(
        "--benchmark",
        action="store_true",
        help="Run JSONL benchmark smoke suite (see docs/fix_report.md)",
    )
    args = parser.parse_args()

    if args.demo:
        if not args.demo.exists():
            print(f"Case file not found: {args.demo}", file=sys.stderr)
            return 1
        return _run_demo(args.demo.resolve())
    if args.benchmark:
        return _run_benchmark()

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
