"""Academic figure domain agent."""

from __future__ import annotations

from app.models.schemas import WorkflowState
from app.tools.trace_logger import append_trace


class AcademicFigureAgent:
    """Enrich visual spec with academic figure domain rules."""

    def __init__(self, llm_client=None):
        self.llm_client = llm_client

    def enrich(self, state: WorkflowState) -> WorkflowState:
        """Add method modules, flow order, caption suggestions."""
        elements = state.visual_spec.key_elements if state.visual_spec else []
        enrichment = {
            "method_modules": elements or ["Data Input", "Preprocessing", "Model", "Evaluation"],
            "flow_order": "top-to-bottom",
            "caption_suggestion": f"Figure 1: {state.visual_spec.title if state.visual_spec else 'Method Overview'}",
            "preferred_output": ["svg", "mermaid"],
            "label_guidelines": ["使用无衬线字体", "模块名简洁", "箭头标注数据流"],
        }

        if state.visual_spec:
            # Respect user clarification (e.g. png); only default to svg when unset.
            fmt = (state.visual_spec.output_format or "").lower().strip()
            if fmt not in ("png", "pdf"):
                state.visual_spec.output_format = "svg"
            enrichment["preferred_output"] = (
                ["png", "svg", "mermaid"] if fmt == "png" else ["svg", "mermaid", "png"]
            )
            state.visual_spec.constraints.extend([
                "模块对齐排列",
                "箭头表示数据/控制流",
                "标签字号不小于 10pt",
            ])

        state.domain_enrichment = enrichment
        append_trace(
            state.traces,
            agent_name="AcademicFigureAgent",
            step="enrich_domain_spec",
            input_summary=state.task_type,
            output_summary=f"modules={len(enrichment['method_modules'])}",
            metadata=enrichment,
        )
        return state


# Backward-compatible alias
AcademicAgent = AcademicFigureAgent
