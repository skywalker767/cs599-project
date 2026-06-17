"""Critic agent with optional LLM-enhanced suggestions."""

from __future__ import annotations

from pathlib import Path

from app.llm.llm_factory import get_llm
from app.llm.parsing import llm_trace_meta, parse_json_from_text
from app.models.schemas import EvaluationReport, WorkflowState
from app.tools.evaluator import Evaluator
from app.tools.trace_logger import append_trace

CRITIC_SYSTEM = (
    "You are CriticAgent for VisionFlow, a meticulous art director reviewing a generated visual "
    "against its specification. "
    "Return ONLY valid JSON with keys: extra_comments (list of concise observations) and "
    "extra_suggestions (list of concrete, actionable improvements). "
    "Each suggestion must be specific and implementable (e.g. 'increase title contrast against "
    "the background', 'move the CTA to the lower-right third', 'simplify to 4 pipeline modules'), "
    "not generic advice. Focus on requirement alignment, domain compliance, readability, "
    "composition and visual appeal. Do NOT return numeric scores. "
    "Use Chinese. Agent hint: critic."
)


class CriticAgent:
    """Evaluate generated assets and produce EvaluationReport."""

    def __init__(self, llm=None, requested_provider: str | None = None):
        if llm is None:
            self.llm, self.requested_provider = get_llm()
        else:
            self.llm = llm
            self.requested_provider = requested_provider or llm.provider_name
        self.evaluator = Evaluator()

    def evaluate(self, state: WorkflowState) -> WorkflowState:
        """Score visual spec, prompt, and output asset."""
        if not state.visual_spec:
            raise ValueError("VisualSpec required for evaluation")

        output_path = Path(state.output_path) if state.output_path else None
        report = self.evaluator.evaluate(
            visual_spec=state.visual_spec,
            prompt=state.prompt,
            output_path=output_path,
            trace_count=len(state.traces),
            traces=state.traces,
        )

        llm_meta = llm_trace_meta(self.requested_provider, self.llm.provider_name, False, False)
        extras, llm_meta = self._try_llm_enhance(state, report)
        if extras:
            report = self._merge_extras(report, extras)

        state.evaluation = report
        append_trace(
            state.traces,
            agent_name="CriticAgent",
            step="evaluate_asset",
            input_summary=state.output_path or "no asset",
            output_summary=f"overall={report.overall_score}, offline={report.offline_score}",
            metadata={
                **report.model_dump(),
                "evaluator_layers": report.evaluator_layers,
            },
            pipeline_step="evaluation_completed",
            warnings=list(report.warnings),
        )
        return state

    def _try_llm_enhance(
        self, state: WorkflowState, report: EvaluationReport
    ) -> tuple[dict | None, dict]:
        actual = self.llm.provider_name
        fallback = False
        try:
            user_prompt = (
                f"visual_spec: {state.visual_spec.model_dump()}\n"
                f"prompt: {state.prompt[:500]}\n"
                f"current_score: {report.overall_score}\n"
                f"suggestions: {report.suggestions}"
            )
            raw = self.llm.generate_text(CRITIC_SYSTEM, user_prompt)
            parsed = parse_json_from_text(raw)
            if parsed:
                return parsed, llm_trace_meta(self.requested_provider, actual, fallback, True)
            return None, llm_trace_meta(self.requested_provider, actual, True, False)
        except Exception:
            return None, llm_trace_meta(self.requested_provider, actual, True, False)

    def _merge_extras(self, report: EvaluationReport, extras: dict) -> EvaluationReport:
        comments = list(report.comments)
        suggestions = list(report.suggestions)
        for c in extras.get("extra_comments", []):
            if c and c not in comments:
                comments.append(str(c))
        for s in extras.get("extra_suggestions", []):
            if s and s not in suggestions:
                suggestions.append(str(s))
        return report.model_copy(update={"comments": comments, "suggestions": suggestions})
