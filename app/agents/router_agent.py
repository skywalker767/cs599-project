"""Router agent: hybrid deterministic + optional LLM task classification."""

from __future__ import annotations

import re
from typing import Any

from app.config import get_settings
from app.llm.llm_factory import get_llm
from app.llm.parsing import llm_trace_meta, parse_json_from_text
from app.models.schemas import VALID_TASK_TYPES, RouteResult, WorkflowState
from app.tools.trace_logger import append_trace

# Weighted keyword + regex patterns per domain
_DOMAIN_PATTERNS: dict[str, list[tuple[str, float]]] = {
    "ecommerce_banner": [
        (r"商品|促销|电商|主图|详情页|618|双11|banner|广告|抢购|折扣|到手价", 2.0),
        (r"product|sale|shop|ecommerce|discount|cta|buy now|poster", 1.5),
    ],
    "academic_figure": [
        (r"论文|方法|模型|流程图|实验|学术|算法|架构图|图注", 2.0),
        (r"framework|pipeline|architecture|graphical abstract|diagram|arxiv", 1.5),
    ],
    "ppt_visual": [
        (r"ppt|汇报|报告|封面|演示|教学|教育|信息图|课程", 2.0),
        (r"presentation|slide|keynote|infographic|learning|lesson", 1.5),
    ],
}

ROUTER_LLM_SYSTEM = (
    "You are TaskRouterAgent for VisionFlow. Classify the user request into exactly one task_type: "
    "ecommerce_banner, academic_figure, or ppt_visual. "
    "Return ONLY valid JSON with keys: task_type, confidence (0-1 float), reasoning (short). "
    "ppt_visual covers presentations and educational infographics. "
    "ecommerce_banner covers product posters and ads. "
    "academic_figure covers papers, pipelines, and academic diagrams."
)


class TaskRouterAgent:
    """Hybrid task router: deterministic baseline with optional LLM refinement."""

    def __init__(
        self, llm_client=None, requested_provider: str | None = None, *, auto_llm: bool = True
    ):
        self.llm_client = llm_client
        self.requested_provider = requested_provider
        if llm_client is None and auto_llm:
            try:
                settings = get_settings()
                if settings.llm_enabled:
                    self.llm_client, self.requested_provider = get_llm()
            except Exception:
                self.llm_client = None
                self.requested_provider = None

    def route(self, state: WorkflowState) -> WorkflowState:
        """Determine task_type using hybrid routing."""
        req = state.request
        text = (req.user_input or "").strip()

        if not text:
            result = RouteResult(
                task_type="ppt_visual",
                confidence=0.0,
                evidence=["empty_input"],
                fallback_reason="empty user_input; defaulting to ppt_visual",
                method="deterministic",
            )
            return self._apply_route(state, result)

        if req.task_type and req.task_type != "auto" and req.task_type in VALID_TASK_TYPES:
            result = RouteResult(
                task_type=req.task_type,  # type: ignore[arg-type]
                confidence=1.0,
                evidence=[f"manual_override:{req.task_type}"],
                method="manual",
            )
            return self._apply_route(state, result)

        baseline = self._deterministic_route(text)
        if self.llm_client and self._llm_available():
            llm_result = self._llm_route(text, baseline)
            if llm_result:
                return self._apply_route(state, llm_result)

        return self._apply_route(state, baseline)

    def route_with_llm(self, state: WorkflowState) -> WorkflowState:
        """Explicit LLM routing entry point with deterministic fallback."""
        return self.route(state)

    def _deterministic_route(self, text: str) -> RouteResult:
        lower = text.lower()
        scores: dict[str, float] = {}
        evidence: list[str] = []

        for task_type, patterns in _DOMAIN_PATTERNS.items():
            score = 0.0
            for pattern, weight in patterns:
                matches = re.findall(pattern, lower, flags=re.IGNORECASE)
                if matches:
                    score += weight * len(matches)
                    evidence.append(f"{task_type}:{pattern}×{len(matches)}")
            scores[task_type] = score

        total = sum(scores.values())
        if total == 0:
            return RouteResult(
                task_type="ppt_visual",
                confidence=0.35,
                evidence=["no_keyword_match"],
                fallback_reason="no domain keywords matched; default ppt_visual",
                method="deterministic",
            )

        best = max(scores, key=scores.get)
        second_best = sorted(scores.values(), reverse=True)
        margin = (second_best[0] - second_best[1]) if len(second_best) > 1 else second_best[0]
        confidence = min(0.95, 0.5 + (scores[best] / max(total, 1)) * 0.4 + margin * 0.05)

        # Ambiguous: top two scores within 15% of each other
        sorted_types = sorted(scores, key=scores.get, reverse=True)
        if len(sorted_types) > 1 and scores[sorted_types[0]] > 0:
            ratio = scores[sorted_types[1]] / scores[sorted_types[0]]
            if ratio > 0.85:
                evidence.append(f"ambiguous:{sorted_types[0]}_vs_{sorted_types[1]}")
                confidence = min(confidence, 0.55)

        return RouteResult(
            task_type=best,  # type: ignore[arg-type]
            confidence=round(confidence, 3),
            evidence=evidence[:12],
            method="deterministic",
        )

    def _llm_route(self, text: str, baseline: RouteResult) -> RouteResult | None:
        try:
            raw = self.llm_client.generate_text(ROUTER_LLM_SYSTEM, f"user_input:\n{text[:2000]}")
            parsed = parse_json_from_text(raw)
            if not parsed:
                return RouteResult(
                    task_type=baseline.task_type,
                    confidence=baseline.confidence,
                    evidence=baseline.evidence + ["llm_parse_failed"],
                    llm_used=False,
                    fallback_reason="LLM response could not be parsed; using deterministic baseline",
                    method="deterministic_fallback",
                )

            task_type = parsed.get("task_type", baseline.task_type)
            if task_type not in VALID_TASK_TYPES:
                return RouteResult(
                    task_type=baseline.task_type,
                    confidence=baseline.confidence,
                    evidence=baseline.evidence + [f"llm_invalid_type:{task_type}"],
                    llm_used=False,
                    fallback_reason=f"LLM returned invalid task_type '{task_type}'",
                    method="deterministic_fallback",
                )

            conf = float(parsed.get("confidence", 0.8))
            conf = max(0.0, min(1.0, conf))
            reasoning = str(parsed.get("reasoning", ""))[:120]
            return RouteResult(
                task_type=task_type,  # type: ignore[arg-type]
                confidence=round(conf, 3),
                evidence=baseline.evidence + [f"llm:{reasoning}"] if reasoning else ["llm_routing"],
                llm_used=True,
                method="llm",
            )
        except Exception as exc:
            return RouteResult(
                task_type=baseline.task_type,
                confidence=baseline.confidence,
                evidence=baseline.evidence + ["llm_exception"],
                llm_used=False,
                fallback_reason=f"LLM unavailable: {type(exc).__name__}",
                method="deterministic_fallback",
            )

    @staticmethod
    def _llm_available() -> bool:
        settings = get_settings()
        return settings.llm_enabled

    def _apply_route(self, state: WorkflowState, result: RouteResult) -> WorkflowState:
        state.task_type = result.task_type
        state.route_result = result
        state.route_reason = self._format_reason(result)

        llm_meta: dict[str, Any] = {}
        if self.requested_provider:
            actual = (
                getattr(self.llm_client, "provider_name", "none") if self.llm_client else "none"
            )
            llm_meta = llm_trace_meta(
                self.requested_provider,
                actual,
                not result.llm_used,
                result.llm_used,
            )

        append_trace(
            state.traces,
            agent_name="TaskRouterAgent",
            step="route_task",
            input_summary=(state.request.user_input or "")[:120],
            output_summary=(
                f"type={result.task_type}, confidence={result.confidence}, "
                f"method={result.method}"
            ),
            metadata={
                "task_type": result.task_type,
                "route_reason": state.route_reason,
                "route_result": result.model_dump(),
                **llm_meta,
            },
            pipeline_step="router_decision",
            warnings=[result.fallback_reason] if result.fallback_reason else [],
        )
        return state

    @staticmethod
    def _format_reason(result: RouteResult) -> str:
        parts = [
            f"method={result.method}",
            f"confidence={result.confidence}",
            f"task_type={result.task_type}",
        ]
        if result.evidence:
            parts.append(f"evidence={'; '.join(result.evidence[:4])}")
        if result.fallback_reason:
            parts.append(f"fallback={result.fallback_reason}")
        return " | ".join(parts)


# Backward-compatible alias
RouterAgent = TaskRouterAgent
