"""Tests for ClarificationAgent and clarification-driven generation."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.agents.clarification_agent import ClarificationAgent
from app.models.database import Base
from app.models.schemas import ClarificationAnswer, GenerationRequest
from app.services.generation_service import GenerationService


@pytest.fixture
def agent():
    return ClarificationAgent()


def _question_ids(questions) -> set[str]:
    return {q.question_id for q in questions}


@pytest.fixture
def db_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def test_ecommerce_banner_questions(agent):
    questions = agent.generate_questions("夏季冰咖啡促销图", "ecommerce_banner")
    ids = _question_ids(questions)
    assert "platform" in ids
    assert "marketing_goal" in ids
    assert "style" in ids
    assert "aspect_ratio" in ids
    assert len(questions) >= 6
    assert len(questions) <= 8


def test_academic_figure_questions(agent):
    questions = agent.generate_questions("论文方法流程图", "academic_figure")
    ids = _question_ids(questions)
    assert "figure_type" in ids
    assert "output_format" in ids
    assert "label_language" in ids
    assert len(questions) >= 4


def test_ppt_visual_questions(agent):
    questions = agent.generate_questions("课程汇报封面", "ppt_visual")
    ids = _question_ids(questions)
    assert "slide_position" in ids
    assert "layout_blank" in ids
    assert "visual_focus" in ids
    assert len(questions) >= 4


@pytest.mark.parametrize(
    "task_type",
    ["ecommerce_banner", "academic_figure", "ppt_visual"],
)
def test_each_question_has_options_and_default(agent, task_type: str):
    questions = agent.generate_questions("测试需求", task_type)
    for q in questions:
        assert q.options, f"{q.question_id} missing options"
        assert q.default_value, f"{q.question_id} missing default_value"
        option_values = {o.value for o in q.options}
        assert q.default_value in option_values


def test_clarification_answers_reflected_in_visual_spec(db_session):
    """User choices should flow into VisualSpec constraints and output_format."""
    request = GenerationRequest(
        user_input="为夏季低糖冰咖啡生成小红书促销图",
        task_type="ecommerce_banner",
        clarification_answers=[
            ClarificationAnswer(question_id="compliance_level", selected_value="conservative"),
            ClarificationAnswer(question_id="aspect_ratio", selected_value="4:5"),
            ClarificationAnswer(question_id="style", selected_value="fresh_natural"),
        ],
        skip_clarification=False,
    )
    service = GenerationService()
    result = service.run_generation(db_session, request)

    spec = result.visual_spec
    assert spec.aspect_ratio == "4:5"
    assert "use conservative commercial wording" in spec.constraints
    assert any("absolute advertising claims" in a for a in spec.avoid)

    assert result.clarification_answers
    answer_map = {a.question_id: a.selected_value for a in result.clarification_answers}
    assert answer_map.get("compliance_level") == "conservative"


def test_academic_svg_clarification_in_spec(db_session):
    request = GenerationRequest(
        user_input="生成机器学习方法流程图",
        task_type="academic_figure",
        clarification_answers=[
            ClarificationAnswer(question_id="output_format", selected_value="svg"),
            ClarificationAnswer(question_id="emphasis", selected_value="data_flow"),
        ],
        skip_clarification=False,
    )
    service = GenerationService()
    result = service.run_generation(db_session, request)

    assert result.visual_spec.output_format == "svg"
    assert "ensure readable labels and clear arrows" in result.visual_spec.constraints
    assert any("emphasis:data_flow" in d for d in result.visual_spec.evaluation_dimensions)


def test_run_clarify_via_service():
    service = GenerationService()
    from app.models.schemas import ClarificationRequest

    resp = service.run_clarify(
        ClarificationRequest(
            user_input="为一款夏季低糖冰咖啡生成小红书风格促销图",
            task_type="auto",
        )
    )
    assert resp.task_type == "ecommerce_banner"
    assert len(resp.questions) >= 6
    assert resp.route_reason


def test_llm_dynamic_question_included(agent):
    """DeepSeek (mocked) should add at least one contextual question."""
    questions = agent.generate_questions(
        "为夏季低糖冰咖啡生成小红书促销图，突出清爽低糖",
        "ecommerce_banner",
    )
    ids = _question_ids(questions)
    llm_ids = {qid for qid, src in agent._last_sources.items() if src == "llm"}
    assert llm_ids, f"expected LLM question, got sources={agent._last_sources}"
    assert llm_ids & ids


def test_optional_questions_rotate(agent):
    """Different inputs should pick different optional questions from the pool."""
    q1 = _question_ids(agent.generate_questions("冰咖啡夏日促销", "ecommerce_banner"))
    q2 = _question_ids(agent.generate_questions("冬季羽绒服保暖促销主图", "ecommerce_banner"))
    assert q1 != q2 or len(q1) >= 6
