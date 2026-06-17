"""Revision agent with optional LLM enhancement."""

from __future__ import annotations

import re

from app.llm.llm_factory import get_llm
from app.llm.parsing import llm_trace_meta, parse_json_from_text
from app.models.schemas import WorkflowState
from app.tools.trace_logger import append_trace

RISK_PATTERNS = [
    (r"最好|第一|绝对|100%|国家级|顶级|唯一", ""),
    (r"best ever|#1|guaranteed", ""),
]

REVISION_SYSTEM = (
    "You are RevisionAgent for VisionFlow. "
    "Return ONLY valid JSON with key 'revised_prompt' containing the improved prompt. "
    "Remove risky words, add subject and composition details. Agent hint: revision."
)


class RevisionAgent:
    """Revise prompt when quality score is below threshold."""

    PASS_THRESHOLD = 85

    def __init__(self, llm=None, requested_provider: str | None = None):
        if llm is None:
            self.llm, self.requested_provider = get_llm()
        else:
            self.llm = llm
            self.requested_provider = requested_provider or llm.provider_name

    def revise_if_needed(self, state: WorkflowState) -> WorkflowState:
        """Apply one revision if score < 85 and revision enabled."""
        if not state.evaluation:
            return state

        if not state.request.enable_revision or state.revision_done:
            append_trace(
                state.traces,
                agent_name="RevisionAgent",
                step="revise_if_needed",
                input_summary="revision skipped",
                output_summary="enable_revision=false or already revised",
                metadata=llm_trace_meta(
                    self.requested_provider, self.llm.provider_name, False, False
                ),
            )
            return state

        if state.evaluation.overall_score >= self.PASS_THRESHOLD:
            append_trace(
                state.traces,
                agent_name="RevisionAgent",
                step="revise_if_needed",
                input_summary=f"score={state.evaluation.overall_score}",
                output_summary="score meets threshold, no revision",
                metadata=llm_trace_meta(
                    self.requested_provider, self.llm.provider_name, False, False
                ),
            )
            return state

        revised, llm_meta = self._revise_prompt(state)
        state.prompt = revised.strip()
        state.revision_done = True

        append_trace(
            state.traces,
            agent_name="RevisionAgent",
            step="revise_if_needed",
            input_summary=f"score={state.evaluation.overall_score}",
            output_summary=revised[:100] + "...",
            metadata={"revised_prompt_length": len(revised), **llm_meta},
        )
        return state

    def _revise_prompt(self, state: WorkflowState) -> tuple[str, dict]:
        llm_result, llm_meta = self._try_llm(state)
        if llm_result:
            return llm_result, llm_meta
        return self._revise_with_rules(state), llm_trace_meta(
            self.requested_provider,
            self.llm.provider_name,
            False,
            False,
        )

    def _try_llm(self, state: WorkflowState) -> tuple[str | None, dict]:
        actual = self.llm.provider_name
        fallback = False
        try:
            user_prompt = (
                f"prompt: {state.prompt}\n"
                f"score: {state.evaluation.overall_score}\n"
                f"suggestions: {state.evaluation.suggestions}\n"
                f"visual_spec: {state.visual_spec.model_dump() if state.visual_spec else {}}"
            )
            raw = self.llm.generate_text(REVISION_SYSTEM, user_prompt)
            parsed = parse_json_from_text(raw)
            if parsed and parsed.get("revised_prompt"):
                return str(parsed["revised_prompt"]), llm_trace_meta(
                    self.requested_provider,
                    actual,
                    fallback,
                    True,
                )
            return None, llm_trace_meta(self.requested_provider, actual, True, False)
        except Exception:
            return None, llm_trace_meta(self.requested_provider, actual, True, False)

    def _revise_with_rules(self, state: WorkflowState) -> str:
        revised = state.prompt
        vs = state.visual_spec

        if vs and vs.main_subject.lower() not in revised.lower():
            revised += f". Subject emphasis: {vs.main_subject}"
        if vs and vs.constraints:
            revised += f". Constraints: {'; '.join(vs.constraints[:2])}"
        for pattern, replacement in RISK_PATTERNS:
            revised = re.sub(pattern, replacement, revised, flags=re.IGNORECASE)
        if "composition" not in revised.lower() and vs:
            revised += f". Composition: balanced layout with {', '.join(vs.key_elements[:3])}"
        return revised

    def needs_revision(self, state: WorkflowState) -> bool:
        if not state.request.enable_revision or state.revision_done:
            return False
        if not state.evaluation:
            return False
        return state.evaluation.overall_score < self.PASS_THRESHOLD
