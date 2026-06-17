"""Tests for layered evaluator with real PNG fixtures."""


import pytest
from PIL import Image

from app.models.schemas import AcademicDiagramFields, VisualSpec
from app.tools.evaluator import Evaluator, HeuristicVisualEvaluator
from tests.conftest import (
    make_blank_png,
    make_chart_png,
    make_colorful_png,
    make_low_contrast_png,
)


@pytest.fixture
def evaluator():
    return Evaluator()


def _base_spec(**kwargs) -> VisualSpec:
    defaults = dict(
        task_type="ecommerce_banner",
        title="Test Banner",
        scenario="电商推广",
        target_audience="消费者",
        purpose="促进购买转化",
        style="促销感",
        aspect_ratio="1:1",
        main_subject="促销商品",
        key_elements=["product", "headline", "CTA"],
        text_requirements=["商品名"],
        constraints=["禁用夸大宣传"],
        avoid=["绝对化用语"],
        output_format="png",
        evaluation_dimensions=["卖点突出"],
    )
    defaults.update(kwargs)
    return VisualSpec(**defaults)


def _good_prompt() -> str:
    return (
        "Subject: 促销商品 product. Scene: 电商 banner sale. Style: 促销感. "
        "Composition: product headline CTA. Aspect ratio: 1:1."
    )


def test_colorful_image_scores_higher_than_blank(evaluator, tmp_path):
    blank = tmp_path / "blank.png"
    blank.write_bytes(make_blank_png(256, 256))
    colorful = tmp_path / "colorful.png"
    colorful.write_bytes(make_colorful_png(256, 256))

    blank_result = evaluator.evaluate(_base_spec(), _good_prompt(), blank, trace_count=8)
    color_result = evaluator.evaluate(_base_spec(), _good_prompt(), colorful, trace_count=8)

    assert color_result.overall_score > blank_result.overall_score
    assert (
        blank_result.score_breakdown["aesthetics"]["score"]
        < color_result.score_breakdown["aesthetics"]["score"]
    )
    assert blank_result.score_breakdown["aesthetics"]["rationale"]


def test_chart_like_image_reasonable_score(evaluator, tmp_path):
    chart = tmp_path / "chart.png"
    chart.write_bytes(make_chart_png())
    result = evaluator.evaluate(_base_spec(), _good_prompt(), chart, trace_count=8)
    assert result.offline_score >= 50
    assert result.evaluator_layers == ["deterministic", "heuristic"]


def test_wrong_aspect_ratio_penalized(evaluator, tmp_path):
    asset = tmp_path / "wrong.png"
    asset.write_bytes(make_colorful_png(1024, 1792))  # 9:16 shape
    spec = _base_spec(aspect_ratio="16:9")
    result = evaluator.evaluate(spec, _good_prompt(), asset, trace_count=8)
    assert result.score_breakdown["spec_compliance"]["score"] < 80
    assert (
        "偏差" in result.score_breakdown["spec_compliance"]["rationale"]
        or "符合" in result.score_breakdown["spec_compliance"]["rationale"]
    )


def test_blank_png_detected_by_heuristic(tmp_path):
    path = tmp_path / "b.png"
    path.write_bytes(make_blank_png())
    stats = HeuristicVisualEvaluator().analyze_png(path)
    assert stats.is_blank_like
    scores = HeuristicVisualEvaluator().evaluate_png(path)
    assert scores["aesthetics"].score <= 20


def test_low_contrast_lower_than_colorful(tmp_path):
    low = tmp_path / "low.png"
    low.write_bytes(make_low_contrast_png())
    hi = tmp_path / "hi.png"
    hi.write_bytes(make_colorful_png())
    ev = HeuristicVisualEvaluator()
    assert ev.evaluate_png(hi)["aesthetics"].score > ev.evaluate_png(low)["aesthetics"].score


def test_png_dimensions_verified(evaluator, tmp_path):
    w, h = 512, 288
    path = tmp_path / "sized.png"
    path.write_bytes(make_colorful_png(w, h))
    with Image.open(path) as img:
        assert img.size == (w, h)
    result = evaluator.evaluate(
        _base_spec(aspect_ratio="16:9"), _good_prompt(), path, trace_count=6
    )
    assert result.score_breakdown
    assert all("rationale" in v for v in result.score_breakdown.values())


def test_bad_missing_output(evaluator):
    result = evaluator.evaluate(_base_spec(), _good_prompt(), None, trace_count=1)
    assert result.score_breakdown["format_validity"]["score"] <= 20
    assert result.overall_score <= 70


def test_svg_academic_evaluation(evaluator, tmp_path):
    svg = tmp_path / "diagram.svg"
    svg.write_text(
        '<?xml version="1.0"?><svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
        '<rect x="10" y="10" width="50" height="30"/>'
        '<text x="20" y="30">Input</text></svg>',
        encoding="utf-8",
    )
    spec = _base_spec(
        task_type="academic_figure",
        output_format="svg",
        academic=AcademicDiagramFields(
            entities=["Input", "Output"],
            relationships=["Input → Output"],
            labels=["Input", "Output"],
            caption="Pipeline",
        ),
    )
    result = evaluator.evaluate(spec, "diagram flowchart pipeline", svg, trace_count=8)
    assert result.score_breakdown["format_validity"]["score"] >= 70


def test_risk_words_generate_warnings(evaluator, tmp_path):
    asset = tmp_path / "r.png"
    asset.write_bytes(make_colorful_png())
    risky = _good_prompt() + " 最好 第一 绝对 guaranteed"
    result = evaluator.evaluate(_base_spec(), risky, asset, trace_count=8)
    assert result.risk_count > 0
    assert result.warnings
