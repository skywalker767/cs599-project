"""Router edge cases: confidence, clarification and uncertain-input handling.

These tests use the deterministic router (no LLM) so the behaviour is fully
reproducible and does not depend on any provider.
"""

from __future__ import annotations

import pytest

from app.agents.router_agent import CLARIFICATION_THRESHOLD, TaskRouterAgent
from app.models.schemas import GenerationRequest, WorkflowState


@pytest.fixture
def router():
    return TaskRouterAgent(auto_llm=False)


def _route(router: TaskRouterAgent, text: str, task_type: str = "auto"):
    state = WorkflowState(
        task_id="t",
        request=GenerationRequest(user_input="placeholder", task_type=task_type),
    )
    state.request.user_input = text
    return router.route(state).route_result


def test_clear_ecommerce_routes_to_ecommerce(router):
    res = _route(router, "为商品设计618促销主图 banner，product sale 折扣")
    assert res.task_type == "ecommerce_banner"
    assert res.confidence >= CLARIFICATION_THRESHOLD
    assert not res.clarification_required
    assert res.matched_signals
    assert res.reasoning


def test_clear_academic_routes_to_academic(router):
    res = _route(router, "绘制论文方法流程图 pipeline architecture diagram 学术")
    assert res.task_type == "academic_figure"
    assert not res.clarification_required


def test_clear_ppt_routes_to_ppt(router):
    res = _route(router, "制作课程汇报PPT封面 presentation slide 教学 infographic")
    assert res.task_type == "ppt_visual"
    assert not res.clarification_required


def test_irrelevant_input_requests_clarification(router):
    res = _route(router, "帮我做一张好看的东西")
    assert res.clarification_required is True
    assert res.clarification_question
    assert res.confidence < CLARIFICATION_THRESHOLD


def test_empty_input_requests_clarification(router):
    res = _route(router, "   ")
    assert res.clarification_required is True
    assert res.confidence == 0.0
    assert res.clarification_question


def test_short_input_is_safe(router):
    res = _route(router, "图")
    assert res.task_type in ("ecommerce_banner", "academic_figure", "ppt_visual")
    assert 0.0 <= res.confidence <= 1.0


def test_conflicting_input_low_confidence_with_reasoning(router):
    res = _route(
        router,
        "为论文答辩制作商品促销风格的 pipeline 汇报图，包含 PPT slide 和 diagram",
    )
    assert res.reasoning
    # Mixed signals should not be over-confident.
    assert res.confidence <= 0.8


def test_unknown_input_not_blindly_ppt(router):
    """Unknown input may keep a best-guess type, but must flag clarification."""
    res = _route(router, "xyzzy qwerty 123")
    assert res.clarification_required is True


def test_manual_override_skips_clarification(router):
    res = _route(router, "anything", task_type="academic_figure")
    assert res.task_type == "academic_figure"
    assert res.method == "manual"
    assert res.clarification_required is False
    assert res.confidence == 1.0


def test_route_result_has_all_fields(router):
    res = _route(router, "电商 banner product")
    for attr in (
        "task_type",
        "confidence",
        "reasoning",
        "matched_signals",
        "clarification_required",
        "clarification_question",
    ):
        assert hasattr(res, attr)


def test_routing_is_deterministic(router):
    a = _route(router, "论文方法流程图 pipeline diagram")
    b = _route(router, "论文方法流程图 pipeline diagram")
    assert a.task_type == b.task_type
    assert a.confidence == b.confidence
