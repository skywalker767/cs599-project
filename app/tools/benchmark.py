"""Benchmark runner for Spec2Vision – reads benchmarks/examples.jsonl.

This is a **smoke / regression suite**, not a rigorous ML benchmark.
Metrics (routing accuracy, offline evaluator score) depend on heuristic
rules and mock placeholder images; interpret results accordingly.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import PROJECT_ROOT, get_settings
from app.models.database import Base
from app.models.schemas import GenerationRequest, GenerationResult, VisualSpec
from app.services.generation_service import GenerationService
from app.tools.aspect_ratio import resolve_aspect_ratio

BENCHMARK_JSONL = PROJECT_ROOT / "benchmarks" / "examples.jsonl"
BENCHMARK_RESULTS_DIR = PROJECT_ROOT / "benchmarks" / "results"

# Legacy file-based cases (optional extras)
LEGACY_CASE_FILES = [
    "ecommerce_case.json",
    "academic_case.json",
    "ppt_case.json",
]


def load_benchmark_cases(path: Path | None = None) -> list[dict]:
    """Load benchmark cases from JSONL manifest."""
    jsonl_path = path or BENCHMARK_JSONL
    if not jsonl_path.exists():
        return []
    cases: list[dict] = []
    for line in jsonl_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        cases.append(json.loads(line))
    return cases


def _visual_spec_completeness(spec: VisualSpec) -> float:
    data = spec.model_dump()
    fields = [
        "task_type",
        "title",
        "scenario",
        "target_audience",
        "purpose",
        "style",
        "aspect_ratio",
        "main_subject",
        "key_elements",
        "text_requirements",
        "constraints",
        "avoid",
        "output_format",
        "evaluation_dimensions",
    ]
    filled = 0
    for field in fields:
        val = data.get(field)
        if isinstance(val, list) and val:
            filled += 1
        elif isinstance(val, str) and val.strip():
            filled += 1
    return round(filled / len(fields), 3)


def _spec_compliance_score(spec: VisualSpec, result: GenerationResult) -> float:
    """0-1 score: aspect ratio + key requirements in prompt."""
    score = 0.0
    if spec.aspect_ratio:
        expected = resolve_aspect_ratio(spec.aspect_ratio)
        gen_traces = [t for t in result.traces if t.step == "generate_asset"]
        if gen_traces:
            meta = gen_traces[0].metadata
            w = meta.get("resolved_width") or meta.get("width")
            h = meta.get("resolved_height") or meta.get("height")
            if w == expected.width and h == expected.height:
                score += 0.5
    prompt_l = (result.prompt or "").lower()
    reqs = spec.key_elements or []
    if reqs:
        hits = sum(1 for r in reqs[:5] if r.lower() in prompt_l)
        score += 0.5 * (hits / min(len(reqs), 5))
    else:
        score += 0.25
    return round(min(1.0, score), 3)


def _evaluate_case(case: dict, result: GenerationResult) -> dict:
    expected_type = case.get("expected_task_type", "")
    output_path = Path(result.output_path) if result.output_path else None
    spec = result.visual_spec
    spec_score = _spec_compliance_score(spec, result)

    return {
        "id": case.get("id", ""),
        "input_preview": case.get("input", "")[:80],
        "expected_task_type": expected_type,
        "actual_task_type": result.task_type,
        "routing_correct": result.task_type == expected_type,
        "expected_aspect_ratio": case.get("expected_aspect_ratio"),
        "spec_compliance": spec_score,
        "visual_spec_completeness": _visual_spec_completeness(spec),
        "offline_evaluator_score": result.evaluation.offline_score,
        "vlm_evaluator_score": result.evaluation.vlm_score,
        "overall_score": result.evaluation.overall_score,
        "evaluator_layers": result.evaluation.evaluator_layers,
        "output_exists": bool(output_path and output_path.exists()),
        "generation_success": bool(output_path and output_path.exists()),
        "trace_steps": len(result.traces),
        "pipeline_steps": [
            t.metadata.get("pipeline_step")
            for t in result.traces
            if t.metadata.get("pipeline_step")
        ],
        "passed": (
            result.task_type == expected_type
            and bool(output_path and output_path.exists())
            and result.evaluation.offline_score >= 40
        ),
    }


def _per_task_type_scores(results: list[dict]) -> dict[str, float]:
    buckets: dict[str, list[int]] = {}
    for r in results:
        t = r.get("actual_task_type", "unknown")
        buckets.setdefault(t, []).append(r.get("offline_evaluator_score", 0))
    return {t: round(sum(v) / len(v), 1) for t, v in buckets.items()}


def run_benchmark(save: bool = True, case_files: list[str] | None = None) -> dict:
    """Run benchmark cases and produce JSON report."""
    settings = get_settings()
    settings.ensure_dirs()
    BENCHMARK_RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    engine = create_engine(
        settings.database_url,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    db = sessionmaker(bind=engine)()

    service = GenerationService()
    cases = load_benchmark_cases()
    if case_files:
        # Legacy subset mode for tests
        from app.tools.benchmark_legacy import load_legacy_cases

        cases = load_legacy_cases(case_files)

    results: list[dict] = []
    started_at = datetime.now(timezone.utc).isoformat()

    try:
        for case in cases:
            user_input = case.get("input") or case.get("user_input", "")
            request = GenerationRequest(
                user_input=user_input,
                task_type=case.get("task_type", "auto"),
                aspect_ratio=case.get("aspect_ratio"),
                enable_revision=False,
                skip_clarification=True,
            )
            gen_result = service.run_generation(db, request)
            row = _evaluate_case(case, gen_result)
            row["key_requirements"] = case.get("key_requirements", [])
            results.append(row)
    finally:
        db.close()

    n = max(len(results), 1)
    routing_hits = sum(1 for r in results if r["routing_correct"])
    gen_ok = sum(1 for r in results if r["generation_success"])
    report = {
        "generated_at": started_at,
        "mode": (
            "mock"
            if settings.demo_mode or settings.image_provider == "mock"
            else settings.image_provider
        ),
        "total_cases": len(results),
        "passed_cases": sum(1 for r in results if r["passed"]),
        "pass_rate": round(sum(1 for r in results if r["passed"]) / n, 3),
        "routing_accuracy": round(routing_hits / n, 3),
        "spec_compliance_avg": round(sum(r["spec_compliance"] for r in results) / n, 3),
        "evaluator_avg_score": round(sum(r["offline_evaluator_score"] for r in results) / n, 1),
        "generation_success_rate": round(gen_ok / n, 3),
        "per_task_type_score": _per_task_type_scores(results),
        "results": results,
        "summary": {
            "avg_overall_score": round(sum(r["overall_score"] for r in results) / n, 1),
            "avg_offline_score": round(sum(r["offline_evaluator_score"] for r in results) / n, 1),
            "avg_visual_spec_completeness": round(
                sum(r["visual_spec_completeness"] for r in results) / n,
                3,
            ),
            "avg_trace_steps": round(sum(r["trace_steps"] for r in results) / n, 1),
        },
    }

    if save:
        latest_path = BENCHMARK_RESULTS_DIR / "latest.json"
        latest_path.write_text(
            json.dumps(report, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        report["report_path"] = str(latest_path)

        # Also write legacy path for backward compatibility
        legacy_json = settings.reports_dir / "benchmark_report.json"
        legacy_json.write_text(
            json.dumps(report, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        legacy_md = settings.reports_dir / "benchmark_report.md"
        legacy_md.write_text(_markdown_summary(report), encoding="utf-8")
        report["markdown_report_path"] = str(legacy_md)

    return report


def _markdown_summary(report: dict) -> str:
    lines = [
        "# Spec2Vision Benchmark Report",
        "",
        f"- Generated at: {report.get('generated_at', '')}",
        f"- Mode: {report.get('mode', '')}",
        f"- Total cases: {report.get('total_cases', 0)}",
        f"- Routing accuracy: {report.get('routing_accuracy', 0):.1%}",
        f"- Spec compliance avg: {report.get('spec_compliance_avg', 0):.3f}",
        f"- Offline evaluator avg: {report.get('evaluator_avg_score', 0)}",
        f"- Generation success: {report.get('generation_success_rate', 0):.1%}",
        "",
        "## Per task type",
        "",
    ]
    for t, s in report.get("per_task_type_score", {}).items():
        lines.append(f"- {t}: {s}")
    lines.extend(["", "## Results", ""])
    for r in report.get("results", []):
        status = "PASS" if r.get("passed") else "FAIL"
        lines.append(
            f"- [{status}] {r.get('id', '')}: type={r.get('actual_task_type')} "
            f"offline={r.get('offline_evaluator_score')} routing={'ok' if r.get('routing_correct') else 'miss'}"
        )
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    r = run_benchmark()
    print(json.dumps(r, indent=2, ensure_ascii=False))
