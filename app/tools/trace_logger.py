"""Trace logging utilities for agent workflow steps."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.config import get_settings
from app.models.schemas import AgentTrace, utc_now_iso


class TraceLogger:
    """Records AgentTrace entries and persists them as JSON."""

    def __init__(self, traces: list[AgentTrace] | None = None):
        self.traces: list[AgentTrace] = traces if traces is not None else []

    def log(
        self,
        agent_name: str,
        step: str,
        input_summary: str,
        output_summary: str,
        metadata: dict[str, Any] | None = None,
    ) -> AgentTrace:
        entry = AgentTrace(
            step=step,
            agent_name=agent_name,
            input_summary=input_summary,
            output_summary=output_summary,
            metadata=metadata or {},
            timestamp=utc_now_iso(),
        )
        self.traces.append(entry)
        return entry

    def save(self, task_id: str) -> Path:
        settings = get_settings()
        path = settings.traces_dir / f"{task_id}.json"
        payload = [t.model_dump() for t in self.traces]
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        return path


def append_trace(
    traces: list[AgentTrace],
    agent_name: str,
    step: str,
    input_summary: str,
    output_summary: str,
    metadata: dict[str, Any] | None = None,
    duration_ms: int = 0,
    warnings: list[str] | None = None,
    pipeline_step: str | None = None,
) -> AgentTrace:
    """Convenience helper to append a trace entry to a list."""
    meta = dict(metadata or {})
    if pipeline_step:
        meta.setdefault("pipeline_step", pipeline_step)
    # Never leak secrets into traces
    for key in list(meta.keys()):
        if any(s in key.lower() for s in ("api_key", "secret", "password", "token")):
            meta[key] = "[REDACTED]"
        elif isinstance(meta[key], str) and (meta[key].startswith("sk-") or "Bearer " in meta[key]):
            meta[key] = "[REDACTED]"

    entry = AgentTrace(
        step=step,
        agent_name=agent_name,
        input_summary=input_summary,
        output_summary=output_summary,
        metadata=meta,
        warnings=warnings or [],
        timestamp=utc_now_iso(),
        duration_ms=duration_ms,
    )
    traces.append(entry)
    return entry
