"""Tests for visual spec agent."""


from app.agents.requirement_agent import RequirementAgent
from app.agents.router_agent import TaskRouterAgent
from app.agents.visual_spec_agent import VisualSpecAgent
from app.models.schemas import GenerationRequest, VisualSpec, WorkflowState


def _prepare_state(text: str, task_type: str = "auto") -> WorkflowState:
    state = WorkflowState(
        task_id="vs01",
        request=GenerationRequest(user_input=text, task_type=task_type),
    )
    state = TaskRouterAgent().route(state)
    state = RequirementAgent().parse(state)
    return state


def test_ecommerce_visual_spec_domain_fields(openai_http_env):
    # Verifies LLM-enriched (DeepSeek, mocked httpx) ecommerce spec content.
    state = _prepare_state("电商促销商品主图 banner 设计，突出卖点")
    vs = VisualSpecAgent().build(state).visual_spec
    assert vs is not None
    assert vs.task_type == "ecommerce_banner"
    assert vs.product_poster is not None
    assert vs.product_poster.cta
    assert vs.field_provenance.get("title") in ("user_input", "default", "inferred")
    combined = " ".join(vs.key_elements + vs.constraints + vs.avoid).lower()
    assert any(
        k in combined
        for k in ("促销", "商品", "cta", "卖点", "product", "headline", "banner", "sale")
    )


def test_academic_visual_spec_domain_fields():
    state = _prepare_state("论文方法流程图 pipeline architecture 实验")
    vs = VisualSpecAgent().build(state).visual_spec
    assert vs.output_format in ("svg", "mermaid")
    assert vs.academic is not None
    assert len(vs.academic.entities) >= 3
    assert vs.academic.directionality


def test_ppt_educational_fields():
    state = _prepare_state("教育信息图 infographic 教学 PPT 汇报")
    vs = VisualSpecAgent().build(state).visual_spec
    assert vs.task_type == "ppt_visual"
    assert vs.educational is not None
    assert vs.educational.topic
    assert vs.educational.key_concepts


def test_missing_field_repair_defaults():
    state = _prepare_state("做一个图")
    vs = VisualSpecAgent().build(state).visual_spec
    assert vs.title
    assert vs.purpose
    assert vs.key_elements
    assert "default" in vs.field_provenance.values() or "inferred" in vs.field_provenance.values()


def test_visual_spec_schema_valid():
    state = _prepare_state("PPT汇报封面 presentation slide 专业")
    vs = VisualSpecAgent().build(state).visual_spec
    validated = VisualSpec.model_validate(vs.model_dump())
    assert validated.task_type == "ppt_visual"
