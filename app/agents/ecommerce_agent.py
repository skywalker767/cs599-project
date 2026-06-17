"""E-commerce banner domain agent."""

from __future__ import annotations

from app.models.schemas import WorkflowState
from app.tools.trace_logger import append_trace


class EcommerceAgent:
    """Enrich visual spec with e-commerce domain rules."""

    def __init__(self, llm_client=None):
        self.llm_client = llm_client

    def enrich(self, state: WorkflowState) -> WorkflowState:
        """Add selling points, promotion elements, and platform guidelines."""
        enrichment = {
            "selling_points": ["品质保证", "限时优惠", "包邮/退换"],
            "promotion_elements": ["折扣标签", "倒计时", "满减信息"],
            "platform_guidelines": [
                "主图尺寸 800x800 或 1:1",
                "文字不超过画面 30%",
                "突出商品主体",
            ],
            "forbidden_phrases": ["最好", "第一", "100%有效", "国家级", "绝对"],
            "cta_suggestions": ["立即购买", "加入购物车", "领券下单"],
        }

        if state.visual_spec:
            state.visual_spec.constraints.extend(
                [
                    "避免绝对化广告词",
                    "促销信息真实可验证",
                ]
            )
            state.visual_spec.avoid.extend(enrichment["forbidden_phrases"])

        state.domain_enrichment = enrichment
        append_trace(
            state.traces,
            agent_name="EcommerceAgent",
            step="enrich_domain_spec",
            input_summary=state.task_type,
            output_summary=f"selling_points={len(enrichment['selling_points'])}",
            metadata=enrichment,
        )
        return state
