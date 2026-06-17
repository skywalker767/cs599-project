"""Tests for the explainable rubric layer of the evaluator."""

from __future__ import annotations

import pytest

from app.models.schemas import (
    AcademicDiagramFields,
    AgentTrace,
    ProductPosterFields,
    VisualSpec,
)
from app.tools.evaluator import Evaluator
from tests.conftest import make_chart_png, make_colorful_png

RUBRIC_KEYS = {
    "visual_validity",
    "spec_completeness",
    "requirement_alignment",
    "domain_fit",
    "traceability",
    "reproducibility",
}


def _full_ecom_spec() -> VisualSpec:
    return VisualSpec(
        task_type="ecommerce_banner",
        title="夏季冰咖啡促销主图",
        scenario="电商促销 banner 投放小红书平台",
        target_audience="年轻消费者",
        purpose="促进商品购买转化",
        style="清新促销风，构图突出商品",
        aspect_ratio="1:1",
        main_subject="夏季低糖冰咖啡 product",
        key_elements=["product 商品主图", "促销标语 cta", "背景 background"],
        text_requirements=["立即购买", "限时折扣"],
        constraints=["禁用绝对化用语"],
        avoid=["夸大宣传"],
        output_format="png",
        evaluation_dimensions=["卖点突出", "平台适配"],
        product_poster=ProductPosterFields(product_name="冰咖啡", cta="立即购买"),
    )


def _minimal_spec() -> VisualSpec:
    return VisualSpec(
        task_type="ecommerce_banner",
        title="",
        scenario="",
        target_audience="",
        purpose="",
        style="",
        aspect_ratio="1:1",
        main_subject="",
        key_elements=[],
        text_requirements=[],
        constraints=[],
        avoid=[],
        output_format="png",
        evaluation_dimensions=[],
    )


def _full_traces() -> list[AgentTrace]:
    steps = [
        ("TaskRouterAgent", "router_decision", {"provider": "mock"}),
        ("ClarificationAgent", "clarification_needed", {}),
        ("VisualSpecAgent", "visual_spec_created", {}),
        ("PromptAgent", "prompt_created", {}),
        ("AssetManagerAgent", "output_generated", {"provider": "mock", "generation_mode": "mock"}),
        ("CriticAgent", "evaluation_completed", {}),
    ]
    return [
        AgentTrace(
            step=name,
            agent_name=agent,
            input_summary="in",
            output_summary="out",
            metadata={"pipeline_step": step, **meta},
        )
        for agent, step, meta in steps
        for name in [step]
    ]


@pytest.fixture
def evaluator():
    return Evaluator()


def _good_prompt() -> str:
    return (
        "Subject: 夏季低糖冰咖啡 product. Scene: 电商 banner sale 小红书平台. "
        "Composition: product 商品主图 促销标语 cta background 背景. 立即购买 折扣."
    )


def test_rubric_keys_present(evaluator, tmp_path):
    asset = tmp_path / "a.png"
    asset.write_bytes(make_colorful_png(1024, 1024))
    report = evaluator.evaluate(_full_ecom_spec(), _good_prompt(), asset, 6, _full_traces())
    assert set(report.rubric.keys()) == RUBRIC_KEYS


def test_each_dimension_has_evidence_and_deductions(evaluator, tmp_path):
    asset = tmp_path / "a.png"
    asset.write_bytes(make_colorful_png(1024, 1024))
    report = evaluator.evaluate(_full_ecom_spec(), _good_prompt(), asset, 6, _full_traces())
    for key, dim in report.rubric.items():
        assert "score" in dim and 0 <= dim["score"] <= 100, key
        assert "rationale" in dim and dim["rationale"], key
        assert "evidence" in dim and isinstance(dim["evidence"], list), key
        assert "deductions" in dim and isinstance(dim["deductions"], list), key


def test_full_spec_scores_higher_than_minimal(evaluator, tmp_path):
    asset = tmp_path / "a.png"
    asset.write_bytes(make_colorful_png(1024, 1024))
    full = evaluator.evaluate(_full_ecom_spec(), _good_prompt(), asset, 6, _full_traces())
    minimal = evaluator.evaluate(_minimal_spec(), "图", asset, 6, _full_traces())
    assert (
        full.rubric["spec_completeness"]["score"]
        > minimal.rubric["spec_completeness"]["score"]
    )
    assert minimal.rubric["spec_completeness"]["deductions"]


def test_missing_file_low_visual_validity(evaluator):
    report = evaluator.evaluate(_full_ecom_spec(), _good_prompt(), None, 6, _full_traces())
    assert report.rubric["visual_validity"]["score"] <= 20
    assert report.rubric["visual_validity"]["deductions"]


def test_missing_trace_stages_deducted(evaluator, tmp_path):
    asset = tmp_path / "a.png"
    asset.write_bytes(make_colorful_png(1024, 1024))
    partial = [
        AgentTrace(
            step="route_task",
            agent_name="TaskRouterAgent",
            input_summary="in",
            output_summary="out",
            metadata={"pipeline_step": "router_decision"},
        )
    ]
    report = evaluator.evaluate(_full_ecom_spec(), _good_prompt(), asset, 1, partial)
    trace_dim = report.rubric["traceability"]
    assert trace_dim["score"] < 100
    assert any("missing_stage" in d for d in trace_dim["deductions"])


def test_different_task_types_use_different_rubric(evaluator, tmp_path):
    png = tmp_path / "p.png"
    png.write_bytes(make_chart_png())
    svg = tmp_path / "d.svg"
    svg.write_text(
        '<?xml version="1.0"?><svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
        '<rect x="10" y="10" width="50" height="30"/><text x="20" y="30">Input</text></svg>',
        encoding="utf-8",
    )
    ecom = evaluator.evaluate(_full_ecom_spec(), _good_prompt(), png, 6, _full_traces())

    academic_spec = VisualSpec(
        task_type="academic_figure",
        title="方法流程",
        scenario="论文配图",
        target_audience="审稿人",
        purpose="展示方法 pipeline",
        style="学术蓝灰，清晰可读",
        aspect_ratio="16:9",
        main_subject="method pipeline diagram",
        key_elements=["输入模块", "处理模块", "输出模块"],
        text_requirements=["标签 labels"],
        constraints=["清晰标注"],
        avoid=[],
        output_format="svg",
        evaluation_dimensions=["可读性"],
        academic=AcademicDiagramFields(
            entities=["Input", "Output"],
            labels=["Input", "Output"],
            caption="Pipeline overview",
        ),
    )
    academic = evaluator.evaluate(
        academic_spec, "diagram flowchart pipeline labels caption 数据", svg, 6, _full_traces()
    )
    # The covered/missing rubric items differ per task type.
    ecom_items = set(ecom.rubric["domain_fit"]["evidence"] + ecom.rubric["domain_fit"]["deductions"])
    acad_items = set(
        academic.rubric["domain_fit"]["evidence"] + academic.rubric["domain_fit"]["deductions"]
    )
    assert ecom_items != acad_items


def test_rubric_is_deterministic(evaluator, tmp_path):
    asset = tmp_path / "a.png"
    asset.write_bytes(make_colorful_png(1024, 1024))
    r1 = evaluator.evaluate(_full_ecom_spec(), _good_prompt(), asset, 6, _full_traces())
    r2 = evaluator.evaluate(_full_ecom_spec(), _good_prompt(), asset, 6, _full_traces())
    assert r1.rubric == r2.rubric
    assert r1.overall_score == r2.overall_score


def test_report_evidence_aggregated(evaluator, tmp_path):
    asset = tmp_path / "a.png"
    asset.write_bytes(make_colorful_png(1024, 1024))
    report = evaluator.evaluate(_full_ecom_spec(), _good_prompt(), asset, 6, _full_traces())
    assert report.evidence
    assert isinstance(report.evidence, list)
