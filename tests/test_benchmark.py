"""Tests for benchmark runner."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.config import PROJECT_ROOT, get_settings
from app.tools.benchmark import BENCHMARK_JSONL, load_benchmark_cases, run_benchmark


@pytest.fixture(autouse=True)
def clear_cache():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_benchmark_jsonl_has_twelve_cases():
    cases = load_benchmark_cases()
    assert len(cases) == 12
    types = {c["expected_task_type"] for c in cases}
    assert types == {"ecommerce_banner", "academic_figure", "ppt_visual"}


def test_run_benchmark_subset_generates_report():
    report = run_benchmark(save=True, case_files=["ecommerce_case.json", "ppt_case.json"])

    assert report["total_cases"] == 2
    assert len(report["results"]) == 2
    assert "routing_accuracy" in report
    assert "spec_compliance_avg" in report
    assert "evaluator_avg_score" in report
    assert "generation_success_rate" in report
    assert report["report_path"]

    report_path = Path(report["report_path"])
    assert report_path.exists()
    assert report_path == PROJECT_ROOT / "benchmarks" / "results" / "latest.json"

    for row in report["results"]:
        assert "routing_correct" in row
        assert "spec_compliance" in row
        assert "offline_evaluator_score" in row
        assert row["generation_success"] is True


def test_benchmark_offline_mock_mode(monkeypatch, tmp_path):
    monkeypatch.setenv("DEMO_MODE", "true")
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("IMAGE_PROVIDER", "mock")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'bench.db'}")
    get_settings.cache_clear()

    report = run_benchmark(
        save=False,
        case_files=["ecommerce_case.json", "academic_case.json", "ppt_case.json"],
    )
    assert report["mode"] == "mock"
    assert report["total_cases"] == 3
    assert all(r["generation_success"] for r in report["results"])


def test_benchmark_full_jsonl_mock(monkeypatch, tmp_path):
    monkeypatch.setenv("DEMO_MODE", "true")
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("IMAGE_PROVIDER", "mock")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'bench2.db'}")
    get_settings.cache_clear()

    report = run_benchmark(save=False)
    assert report["total_cases"] == 12
    # Smoke suite: expect strong routing on curated JSONL (not a rigorous ML benchmark).
    assert report["routing_accuracy"] >= 0.75, (
        f"routing_accuracy {report['routing_accuracy']} below smoke threshold 0.75"
    )
    assert BENCHMARK_JSONL.exists()


def test_benchmark_report_default_path():
    report = run_benchmark(save=True, case_files=["ecommerce_case.json"])
    latest = PROJECT_ROOT / "benchmarks" / "results" / "latest.json"
    assert Path(report["report_path"]) == latest
    data = json.loads(latest.read_text(encoding="utf-8"))
    assert "per_task_type_score" in data
