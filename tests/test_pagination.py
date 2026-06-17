"""Tests for API pagination."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client():
    return TestClient(app)


def _generate(client, text: str):
    return client.post(
        "/generate",
        json={
            "user_input": text,
            "task_type": "auto",
            "skip_clarification": True,
            "enable_revision": False,
        },
    )


def test_tasks_pagination_total_and_has_next(client):
    for i in range(5):
        resp = _generate(client, f"电商促销主图测试 {i} banner product")
        assert resp.status_code == 200

    page = client.get("/tasks", params={"limit": 2, "offset": 0})
    assert page.status_code == 200
    data = page.json()
    assert data["limit"] == 2
    assert data["offset"] == 0
    assert data["returned_count"] == len(data["tasks"]) <= 2
    assert data["total"] >= 5
    assert data["has_next"] is True
    assert len(data["items"]) == len(data["tasks"])

    page2 = client.get("/tasks", params={"limit": 2, "offset": 2})
    data2 = page2.json()
    assert data2["total"] == data["total"]
    assert data2["offset"] == 2
    assert data2["has_next"] is True

    last = client.get("/tasks", params={"limit": 2, "offset": data["total"] - 1})
    last_data = last.json()
    assert last_data["has_next"] is False
