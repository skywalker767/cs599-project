"""PPT visual domain agent."""

from __future__ import annotations

from app.models.schemas import WorkflowState
from app.tools.trace_logger import append_trace


class PPTVisualAgent:
    """Enrich visual spec with PPT/report visual domain rules."""

    def __init__(self, llm_client=None):
        self.llm_client = llm_client

    def enrich(self, state: WorkflowState) -> WorkflowState:
        """Add cover composition, presentation style, and whitespace rules."""
        enrichment = {
            "cover_composition": "标题居左或居中，右侧/背景放抽象图形",
            "presentation_style": "专业商务或学术科技风",
            "whitespace_zones": ["标题区上方留白", "底部品牌/日期区", "左右安全边距"],
            "title_readability": [
                "标题字号不小于 36pt",
                "标题与背景对比度 ≥ 4.5:1",
                "副标题弱化处理",
            ],
            "background_motif": "几何渐变或低饱和度抽象图形",
        }

        if state.visual_spec:
            state.visual_spec.constraints.extend(
                [
                    "保留充足留白",
                    "标题区域不被图形遮挡",
                ]
            )

        state.domain_enrichment = enrichment
        append_trace(
            state.traces,
            agent_name="PPTVisualAgent",
            step="enrich_domain_spec",
            input_summary=state.task_type,
            output_summary="cover_composition applied",
            metadata=enrichment,
        )
        return state


# Backward-compatible alias
PPTAgent = PPTVisualAgent
