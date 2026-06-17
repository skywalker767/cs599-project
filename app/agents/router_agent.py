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

# Below this confidence the route is treated as uncertain and clarification is requested.
CLARIFICATION_THRESHOLD = 0.45

CLARIFICATION_QUESTION = (
    "无法确定视觉类型，请选择：电商商品主图(ecommerce)、学术论文配图(academic)，"
    "还是演示/PPT 幻灯片(ppt_visual)？"
    " | Do you want an e-commerce product visual, an academic figure, "
    "or a presentation slide?"
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
                reasoning="用户输入为空，无法判断视觉类型，需要澄清。",
                matched_signals=[],
                evidence=["empty_input"],
                clarification_required=True,
                clarification_question=CLARIFICATION_QUESTION,
                fallback_reason="empty user_input; clarification required (best-guess ppt_visual)",
                method="deterministic",
            )
            return self._apply_route(state, result)

        if req.task_type and req.task_type != "auto" and req.task_type in VALID_TASK_TYPES:
            result = RouteResult(
                task_type=req.task_type,  # type: ignore[arg-type]
                confidence=1.0,
                reasoning=f"调用方显式指定 task_type={req.task_type}。",
                matched_signals=[f"manual_override:{req.task_type}"],
                evidence=[f"manual_override:{req.task_type}"],
                method="manual",
            )
            return self._apply_route(state, result)

        baseline = self._deterministic_route(text)
        if self.llm_client and self._llm_available():
            llm_result = self._llm_route(text, baseline)
            if llm_result:
                return self._apply_route(state, self._finalize(llm_result))

        return self._apply_route(state, self._finalize(baseline))

    def route_rule_based(self, state: WorkflowState) -> WorkflowState:
        """Deterministic-only routing entry point (no LLM call)."""
        req = state.request
        text = (req.user_input or "").strip()
        if not text:
            return self.route(state)
        if req.task_type and req.task_type != "auto" and req.task_type in VALID_TASK_TYPES:
            return self.route(state)
        return self._apply_route(state, self._finalize(self._deterministic_route(text)))

    def route_with_llm(self, state: WorkflowState) -> WorkflowState:
        """Backward-compatible alias for :meth:`route`.

        ``route`` already performs real LLM classification when an LLM client is
        available (falling back to the deterministic baseline otherwise), so this
        method simply delegates. Prefer :meth:`route` or :meth:`route_rule_based`.
        """
        return self.route(state)

    @staticmethod
    def _finalize(result: RouteResult) -> RouteResult:
        """Flag low-confidence routes as needing clarification."""
        if result.method == "manual":
            return result
        if result.confidence < CLARIFICATION_THRESHOLD and not result.clarification_required:
            result.clarification_required = True
            if not result.clarification_question:
                result.clarification_question = CLARIFICATION_QUESTION
            if not result.fallback_reason:
                result.fallback_reason = (
                    f"confidence {result.confidence} < {CLARIFICATION_THRESHOLD}; "
                    "clarification recommended"
                )
        return result

    def _deterministic_route(self, text: str) -> RouteResult:
        lower = text.lower()
        scores: dict[str, float] = {}
        evidence: list[str] = []
        matched_signals: list[str] = []

        for task_type, patterns in _DOMAIN_PATTERNS.items():
            score = 0.0
            for pattern, weight in patterns:
                matches = re.findall(pattern, lower, flags=re.IGNORECASE)
                if matches:
                    score += weight * len(matches)
                    evidence.append(f"{task_type}:{pattern}×{len(matches)}")
                    matched_signals.extend(dict.fromkeys(m for m in matches if m))
            scores[task_type] = score

        total = sum(scores.values())
        if total == 0:
            # Honest behaviour: do NOT silently classify unknown input as ppt_visual.
            return RouteResult(
                task_type="ppt_visual",
                confidence=0.2,
                reasoning="未匹配到任何领域关键词，无法可靠判断，建议向用户澄清。",
                matched_signals=[],
                evidence=["no_keyword_match"],
                clarification_required=True,
                clarification_question=CLARIFICATION_QUESTION,
                fallback_reason="no domain keywords matched; clarification required",
                method="deterministic",
            )

        best = max(scores, key=scores.get)
        second_best = sorted(scores.values(), reverse=True)
        margin = (second_best[0] - second_best[1]) if len(second_best) > 1 else second_best[0]
        confidence = min(0.95, 0.5 + (scores[best] / max(total, 1)) * 0.4 + margin * 0.05)

        # Ambiguous: top two scores within 15% of each other
        ambiguous = False
        sorted_types = sorted(scores, key=scores.get, reverse=True)
        if len(sorted_types) > 1 and scores[sorted_types[0]] > 0:
            ratio = scores[sorted_types[1]] / scores[sorted_types[0]]
            if ratio > 0.85:
                evidence.append(f"ambiguous:{sorted_types[0]}_vs_{sorted_types[1]}")
                confidence = min(confidence, 0.4)
                ambiguous = True

        reasoning = (
            f"领域信号最强为 {best}（score={scores[best]:.1f}，领先 margin={margin:.1f}）。"
        )
        if ambiguous:
            reasoning += (
                f" 但 {sorted_types[0]} 与 {sorted_types[1]} 信号接近，存在歧义。"
            )

        return RouteResult(
            task_type=best,  # type: ignore[arg-type]
            confidence=round(confidence, 3),
            reasoning=reasoning,
            matched_signals=list(dict.fromkeys(matched_signals))[:12],
            evidence=evidence[:12],
            clarification_required=ambiguous,
            clarification_question=CLARIFICATION_QUESTION if ambiguous else None,
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
                    reasoning=baseline.reasoning,
                    matched_signals=baseline.matched_signals,
                    evidence=baseline.evidence + ["llm_parse_failed"],
                    clarification_required=baseline.clarification_required,
                    clarification_question=baseline.clarification_question,
                    llm_used=False,
                    fallback_reason="LLM response could not be parsed; using deterministic baseline",
                    method="deterministic_fallback",
                )

            task_type = parsed.get("task_type", baseline.task_type)
            if task_type not in VALID_TASK_TYPES:
                return RouteResult(
                    task_type=baseline.task_type,
                    confidence=baseline.confidence,
                    reasoning=baseline.reasoning,
                    matched_signals=baseline.matched_signals,
                    evidence=baseline.evidence + [f"llm_invalid_type:{task_type}"],
                    clarification_required=baseline.clarification_required,
                    clarification_question=baseline.clarification_question,
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
                reasoning=(f"LLM 分类：{reasoning}" if reasoning else "LLM 分类（无说明）。"),
                matched_signals=baseline.matched_signals,
                evidence=baseline.evidence + [f"llm:{reasoning}"] if reasoning else ["llm_routing"],
                llm_used=True,
                method="llm",
            )
        except Exception as exc:
            return RouteResult(
                task_type=baseline.task_type,
                confidence=baseline.confidence,
                reasoning=baseline.reasoning,
                matched_signals=baseline.matched_signals,
                evidence=baseline.evidence + ["llm_exception"],
                clarification_required=baseline.clarification_required,
                clarification_question=baseline.clarification_question,
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
        if result.clarification_required:
            parts.append("clarification_required=true")
        if result.matched_signals:
            parts.append(f"signals={', '.join(result.matched_signals[:4])}")
        elif result.evidence:
            parts.append(f"evidence={'; '.join(result.evidence[:4])}")
        if result.fallback_reason:
            parts.append(f"fallback={result.fallback_reason}")
        return " | ".join(parts)


# Backward-compatible alias
RouterAgent = TaskRouterAgent
