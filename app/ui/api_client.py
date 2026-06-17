"""Centralized HTTP client for the VisionFlow API.

Keeps all networking, timeouts and error normalization in one place so the
Streamlit UI stays declarative and easy to reason about.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import requests

DEFAULT_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")
CLARIFY_TIMEOUT = int(os.getenv("CLARIFY_TIMEOUT", "180"))
GENERATE_TIMEOUT = int(os.getenv("GENERATE_TIMEOUT", "600"))
QUICK_TIMEOUT = int(os.getenv("QUICK_TIMEOUT", "15"))


class APIError(Exception):
    """Normalized, user-friendly API error."""

    def __init__(self, message: str, *, status_code: int | None = None):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _extract_detail(resp: requests.Response) -> str:
    try:
        body = resp.json()
        if isinstance(body, dict) and "detail" in body:
            return str(body["detail"])
    except Exception:
        pass
    return (resp.text or "")[:500]


@dataclass
class VisionFlowClient:
    """Thin, well-typed wrapper around the VisionFlow REST API."""

    base_url: str = DEFAULT_BASE_URL

    def _url(self, path: str) -> str:
        return f"{self.base_url.rstrip('/')}{path}"

    def _request(self, method: str, path: str, *, timeout: int, **kwargs) -> Any:
        try:
            resp = requests.request(method, self._url(path), timeout=timeout, **kwargs)
            resp.raise_for_status()
            if resp.content and resp.headers.get("content-type", "").startswith("application/json"):
                return resp.json()
            return resp.content
        except requests.Timeout as exc:
            raise APIError(f"请求超时（>{timeout}s），后端可能仍在处理。") from exc
        except requests.ConnectionError as exc:
            raise APIError("无法连接后端 API。请先运行：uvicorn app.main:app --reload") from exc
        except requests.HTTPError as exc:
            detail = _extract_detail(exc.response) if exc.response is not None else str(exc)
            code = exc.response.status_code if exc.response is not None else None
            raise APIError(detail or str(exc), status_code=code) from exc
        except requests.RequestException as exc:
            raise APIError(str(exc)) from exc

    # ── Read endpoints ────────────────────────────────────────────
    def health(self) -> dict:
        return self._request("GET", "/health", timeout=QUICK_TIMEOUT)

    def stats(self) -> dict:
        return self._request("GET", "/stats", timeout=QUICK_TIMEOUT)

    def list_tasks(self, limit: int = 20, offset: int = 0) -> dict:
        return self._request(
            "GET", "/tasks", timeout=QUICK_TIMEOUT, params={"limit": limit, "offset": offset}
        )

    def get_task(self, task_id: str) -> dict:
        return self._request("GET", f"/tasks/{task_id}", timeout=QUICK_TIMEOUT)

    def asset_url(self, task_id: str) -> str:
        return self._url(f"/tasks/{task_id}/asset")

    # ── Write endpoints ───────────────────────────────────────────
    def extract_document(
        self, filename: str, data: bytes, content_type: str = "application/pdf"
    ) -> dict:
        return self._request(
            "POST",
            "/extract",
            timeout=CLARIFY_TIMEOUT,
            files={"file": (filename, data, content_type)},
        )

    def clarify(
        self,
        user_input: str,
        task_type: str,
        document_context: str | None = None,
    ) -> dict:
        body: dict = {"user_input": user_input, "task_type": task_type}
        if document_context:
            body["document_context"] = document_context
        return self._request(
            "POST",
            "/clarify",
            timeout=CLARIFY_TIMEOUT,
            json=body,
        )

    def generate(self, payload: dict) -> dict:
        return self._request("POST", "/generate", timeout=GENERATE_TIMEOUT, json=payload)

    def delete_task(self, task_id: str) -> dict:
        return self._request("DELETE", f"/tasks/{task_id}", timeout=QUICK_TIMEOUT)
