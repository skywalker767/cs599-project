"""Integration tests for generation flow – correctness, not smoke."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.models.database import Base, get_db
from app.models.schemas import GenerationRequest
from app.services.generation_service import GenerationService

EXAMPLES_DIR = Path(__file__).resolve().parent.parent / "examples"
EXAMPLE_FILES = [
    "ecommerce_case.json",
    "academic_case.json",
    "ppt_case.json",
]

PIPELINE_STEPS = {
    "router_decision",
    "visual_spec_created",
    "prompt_created",
    "output_generated",
    "evaluation_completed",
}


@pytest.fixture
def client():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    TestSession = sessionmaker(bind=engine)

    def override_get_db():
        db = TestSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


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


def _load_example(name: str) -> dict:
    return json.loads((EXAMPLES_DIR / name).read_text(encoding="utf-8"))


def _assert_result_quality(data: dict, case: dict) -> None:
    assert data["task_type"] == case["expected_task_type"]
    assert data["visual_spec"]["title"]
    assert data["visual_spec"]["aspect_ratio"]
    assert data["visual_spec"]["key_elements"]
    assert len(data["prompt"]) > 20

    output = Path(data["output_path"])
    assert output.exists()
    if case["expected_output_type"] == "svg":
        assert output.suffix.lower() == ".svg"
        assert "<svg" in output.read_text(encoding="utf-8")[:500].lower()
    else:
        assert output.suffix.lower() == ".png"
        with Image.open(output) as img:
            assert img.size[0] >= 8 and img.size[1] >= 8

    ev = data["evaluation"]
    assert ev["overall_score"] >= 0
    assert ev["score_breakdown"]
    assert any(v.get("rationale") for v in ev["score_breakdown"].values())

    steps = {t.get("metadata", {}).get("pipeline_step") for t in data["traces"]}
    assert PIPELINE_STEPS.issubset(steps)


@pytest.mark.parametrize("example_file", EXAMPLE_FILES)
def test_generation_service_with_examples(client, example_file):
    case = _load_example(example_file)
    payload = {
        "user_input": case["user_input"],
        "task_type": case.get("task_type", "auto"),
        "aspect_ratio": case.get("aspect_ratio"),
        "enable_revision": case.get("enable_revision", False),
        "skip_clarification": True,
    }
    resp = client.post("/generate", json=payload)
    assert resp.status_code == 200, resp.text
    _assert_result_quality(resp.json(), case)


def test_ecommerce_generation_direct(db_session):
    case = _load_example("ecommerce_case.json")
    result = GenerationService().run_generation(
        db_session,
        GenerationRequest(
            user_input=case["user_input"],
            task_type="auto",
            skip_clarification=True,
            enable_revision=False,
        ),
    )
    assert result.task_type == "ecommerce_banner"
    assert result.visual_spec.main_subject or result.visual_spec.key_elements


def test_academic_figure_generation_direct(db_session):
    case = _load_example("academic_case.json")
    result = GenerationService().run_generation(
        db_session,
        GenerationRequest(user_input=case["user_input"], task_type="auto", skip_clarification=True),
    )
    assert result.task_type == "academic_figure"
    assert result.visual_spec.output_format in ("svg", "png")


def test_presentation_visual_generation_direct(db_session):
    case = _load_example("ppt_case.json")
    result = GenerationService().run_generation(
        db_session,
        GenerationRequest(user_input=case["user_input"], task_type="auto", skip_clarification=True),
    )
    assert result.task_type == "ppt_visual"


def test_clarification_flow_via_api(client):
    clarify = client.post(
        "/clarify",
        json={"user_input": "帮我做一张好看的图，要有标题和三个要点", "task_type": "auto"},
    )
    assert clarify.status_code == 200
    body = clarify.json()
    assert len(body["questions"]) >= 1
    assert body["task_type"] in ("ppt_visual", "ecommerce_banner", "academic_figure")


def test_pdf_input_flow_via_document_context(client):
    payload = {
        "user_input": "",
        "document_context": "【文档标题】Transformer\n【方法流程】Embed → Attention → FFN → Output",
        "task_type": "academic_figure",
        "skip_clarification": True,
        "enable_revision": False,
    }
    resp = client.post("/generate", json=payload)
    assert resp.status_code == 200
    assert resp.json()["task_type"] == "academic_figure"


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"


def test_list_tasks(client):
    case = _load_example("ppt_case.json")
    client.post(
        "/generate",
        json={"user_input": case["user_input"], "task_type": "auto", "skip_clarification": True},
    )
    resp = client.get("/tasks")
    assert resp.status_code == 200
    assert resp.json()["total"] >= 1
    assert "has_next" in resp.json()


def test_invalid_task_id(client):
    assert client.get("/tasks/not-a-real-id").status_code == 404


def test_invalid_payload(client):
    assert client.post("/generate", json={"user_input": ""}).status_code == 422


def test_asset_and_delete_endpoints(client):
    case = _load_example("ppt_case.json")
    gen = client.post(
        "/generate",
        json={"user_input": case["user_input"], "task_type": "auto", "skip_clarification": True},
    )
    task_id = gen.json()["task_id"]
    assert client.get(f"/tasks/{task_id}/asset").status_code == 200
    assert client.delete(f"/tasks/{task_id}").json()["deleted"] is True
