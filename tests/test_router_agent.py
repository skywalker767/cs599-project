"""Tests for hybrid router agent."""

import pytest

from app.agents.router_agent import TaskRouterAgent
from app.llm.mock_llm import MockLLM
from app.models.schemas import GenerationRequest, WorkflowState

ECOMMERCE_INPUT = "为商品设计一张618促销主图，突出限时优惠和电商banner广告，product poster"
ACADEMIC_INPUT = "绘制论文方法流程图，展示模型pipeline和实验framework架构 diagram"
PPT_INPUT = "制作课程汇报PPT封面，educational infographic 教学演示 presentation slide"
AMBIGUOUS_INPUT = "帮我做一张好看的图，要有标题和三个要点"
MIXED_INPUT = "为论文答辩制作商品促销风格的 pipeline 汇报图，包含 PPT slide 和 algorithm diagram"
EMPTY_INPUT = "   "


@pytest.fixture
def router():
    return TaskRouterAgent()


def _state(text: str, task_type: str = "auto") -> WorkflowState:
    return WorkflowState(
        task_id="test01",
        request=GenerationRequest(user_input=text, task_type=task_type),
    )


def test_route_ecommerce_poster(router):
    result = router.route(_state(ECOMMERCE_INPUT))
    assert result.task_type == "ecommerce_banner"
    assert result.route_result is not None
    assert result.route_result.confidence > 0
    assert result.route_result.task_type == "ecommerce_banner"
    assert result.traces[0].agent_name == "TaskRouterAgent"


def test_route_educational_infographic(router):
    result = router.route(_state(PPT_INPUT))
    assert result.task_type == "ppt_visual"
    assert result.route_result.confidence > 0


def test_route_academic_diagram(router):
    result = router.route(_state(ACADEMIC_INPUT))
    assert result.task_type == "academic_figure"


def test_route_ambiguous_triggers_low_confidence():
    router = TaskRouterAgent(auto_llm=False)
    result = router.route(_state(AMBIGUOUS_INPUT))
    assert result.route_result.confidence <= 0.7
    assert (
        any("ambiguous" in e for e in result.route_result.evidence)
        or result.route_result.confidence <= 0.55
    )


def test_route_mixed_domain(router):
    result = router.route(_state(MIXED_INPUT))
    assert result.task_type in ("academic_figure", "ppt_visual", "ecommerce_banner")
    assert result.route_result.evidence


def test_route_empty_input(router):
    with pytest.raises(Exception):
        GenerationRequest(user_input=EMPTY_INPUT, task_type="auto")


def test_route_empty_after_strip(router):
    """Router handles effectively empty workflow state gracefully via route_result."""
    state = WorkflowState(
        task_id="t",
        request=GenerationRequest(user_input="x", task_type="auto"),
    )
    state.request.user_input = ""
    result = router.route(state)
    assert result.route_result.confidence == 0.0


def test_manual_override(router):
    result = router.route(_state("任意描述", task_type="academic_figure"))
    assert result.task_type == "academic_figure"
    assert result.route_result.method == "manual"
    assert result.route_result.confidence == 1.0


def test_llm_unavailable_fallback():
    router = TaskRouterAgent(auto_llm=False)
    result = router.route(_state(ECOMMERCE_INPUT))
    assert result.route_result.llm_used is False
    assert result.task_type == "ecommerce_banner"


def test_llm_routing_with_mock():
    router = TaskRouterAgent(llm_client=MockLLM(), requested_provider="mock")
    result = router.route(_state(PPT_INPUT))
    assert result.route_result is not None
    assert result.task_type == "ppt_visual"
