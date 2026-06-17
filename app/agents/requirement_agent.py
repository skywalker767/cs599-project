"""Requirement analysis agent with clarification merge support."""

from __future__ import annotations

from app.llm.llm_factory import get_llm
from app.llm.parsing import llm_trace_meta, parse_json_from_text
from app.models.schemas import WorkflowState
from app.tools.trace_logger import append_trace

DEFAULT_AUDIENCE = {
    "ecommerce_banner": "在线购物消费者",
    "academic_figure": "研究人员与论文审稿人",
    "ppt_visual": "商务汇报受众",
}

DEFAULT_STYLE = {
    "ecommerce_banner": "促销感、高对比、吸引眼球",
    "academic_figure": "学术简洁、模块清晰、标签可读",
    "ppt_visual": "专业、简洁、科技感",
}

STYLE_MAP = {
    "professional_minimal": "简洁专业",
    "tech_futuristic": "科技未来感",
    "fresh_natural": "清新自然",
    "premium_minimal": "高级极简",
    "lively_young": "活泼年轻",
    "business_stable": "商务稳重",
}

PLATFORM_SCENARIO = {
    "xiaohongshu": "小红书内容电商推广场景",
    "taobao": "淘宝商品详情推广场景",
    "jd": "京东商品促销场景",
    "douyin": "抖音短视频电商场景",
    "wechat": "微信朋友圈广告场景",
}

PRESENTATION_AUDIENCE = {
    "course_defense": "课程答辩师生",
    "business_report": "商务汇报受众",
    "technical_sharing": "技术社区受众",
    "research_presentation": "科研学术受众",
}

REQUIREMENT_SYSTEM = (
    "You are RequirementAgent for VisionFlow, an expert visual creative director. "
    "Analyze the user's request and extract a precise, production-ready creative brief. "
    "Return ONLY valid JSON with these keys:\n"
    "- purpose: the concrete communication goal in one Chinese sentence (what the viewer should feel/do).\n"
    "- main_subject: the single focal subject of the visual, concrete and specific (no vague words).\n"
    "- style: a rich visual style descriptor combining mood, color direction and design language.\n"
    "- target_audience: the specific audience.\n"
    "- aspect_ratio: one of 1:1, 4:5, 3:4, 4:3, 16:9 best fitting the platform/use.\n"
    "Rules: be specific and concrete, prefer the user's own wording, never invent facts. "
    "If a DOCUMENT CONTEXT is provided, ground main_subject and purpose in that document. "
    "Use Chinese for all values except aspect_ratio. Agent hint: requirement."
)


class RequirementAgent:
    """Extract structured requirements from user input using LLM + rules."""

    def __init__(self, llm=None, requested_provider: str | None = None):
        if llm is None:
            self.llm, self.requested_provider = get_llm()
        else:
            self.llm = llm
            self.requested_provider = requested_provider or llm.provider_name

    def parse(self, state: WorkflowState) -> WorkflowState:
        """Parse requirements and merge clarification answers."""
        req = state.request
        text = req.user_input
        task_type = state.task_type

        requirement = self._parse_with_rules(text, task_type, req)
        if getattr(req, "document_context", None):
            requirement["document_context"] = req.document_context
        requirement = self._merge_clarification(
            requirement, state.clarification_resolved, task_type
        )

        llm_meta = llm_trace_meta(self.requested_provider, self.llm.provider_name, False, False)
        llm_data, llm_meta = self._try_llm(text, task_type, req)
        if llm_data:
            clarified_keys = set(state.clarification_resolved.keys())
            for key in ("purpose", "main_subject", "style", "target_audience", "aspect_ratio"):
                if llm_data.get(key):
                    if key in clarified_keys and state.clarification_resolved.get(key):
                        continue
                    requirement[key] = llm_data[key]

        state.requirement = requirement
        append_trace(
            state.traces,
            agent_name="RequirementAgent",
            step="parse_requirement",
            input_summary=text[:120],
            output_summary=f"subject={requirement['main_subject']}, style={requirement['style'][:20]}",
            metadata={**requirement, **llm_meta},
        )
        return state

    def _merge_clarification(
        self,
        requirement: dict,
        clarification: dict[str, str],
        task_type: str,
    ) -> dict:
        """Apply clarification choices to requirement fields."""
        if not clarification:
            return requirement

        requirement["clarification"] = dict(clarification)

        if clarification.get("style"):
            requirement["style"] = STYLE_MAP.get(
                clarification["style"],
                clarification["style"],
            )
        if clarification.get("aspect_ratio"):
            requirement["aspect_ratio"] = clarification["aspect_ratio"]
        if clarification.get("text_level"):
            requirement["text_level"] = clarification["text_level"]
        if clarification.get("information_density"):
            requirement["information_density"] = clarification["information_density"]

        if task_type == "ecommerce_banner":
            platform = clarification.get("platform")
            if platform:
                requirement["scenario"] = PLATFORM_SCENARIO.get(
                    platform, requirement.get("scenario", "")
                )
            goal = clarification.get("marketing_goal")
            if goal:
                requirement["marketing_goal"] = goal
            if goal == "discount_promotion":
                requirement["purpose"] = "强调优惠促销，促进购买转化"
            elif goal == "brand_seeding":
                requirement["purpose"] = "品牌种草，提升认知与好感"

        elif task_type == "academic_figure":
            fig_type = clarification.get("figure_type")
            if fig_type:
                requirement["figure_type"] = fig_type
            if clarification.get("output_format"):
                requirement["output_format"] = clarification["output_format"]
            if clarification.get("label_language"):
                requirement["label_language"] = clarification["label_language"]
            if clarification.get("academic_style"):
                requirement["academic_style"] = clarification["academic_style"]

        elif task_type == "ppt_visual":
            slide = clarification.get("slide_position")
            if slide:
                requirement["slide_position"] = slide
                purpose_map = {
                    "cover": "专业汇报封面，突出主题与品牌感",
                    "section": "章节过渡页，区分内容结构",
                    "content": "内容页配图，辅助说明观点",
                    "ending": "结尾致谢页，简洁收尾",
                }
                requirement["purpose"] = purpose_map.get(slide, requirement.get("purpose", ""))
            ctx = clarification.get("presentation_context")
            if ctx:
                requirement["target_audience"] = PRESENTATION_AUDIENCE.get(
                    ctx,
                    requirement.get("target_audience", ""),
                )
            if clarification.get("layout_blank"):
                requirement["layout_blank"] = clarification["layout_blank"]

        return requirement

    def _try_llm(self, text: str, task_type: str, req) -> tuple[dict | None, dict]:
        actual = self.llm.provider_name
        fallback = False
        try:
            doc_block = ""
            if getattr(req, "document_context", None):
                doc_block = f"\nDOCUMENT CONTEXT (ground your answer in this):\n{req.document_context[:1500]}"
            user_prompt = (
                f"task_type: {task_type}\nuser_input: {text}\n"
                f"style_preference: {req.style_preference or ''}\n"
                f"target_audience: {req.target_audience or ''}\n"
                f"aspect_ratio: {req.aspect_ratio or ''}"
                f"{doc_block}"
            )
            raw = self.llm.generate_text(REQUIREMENT_SYSTEM, user_prompt)
            parsed = parse_json_from_text(raw)
            if parsed:
                return parsed, llm_trace_meta(self.requested_provider, actual, fallback, True)
            return None, llm_trace_meta(self.requested_provider, actual, True, False)
        except Exception:
            return None, llm_trace_meta(self.requested_provider, actual, True, False)

    def _parse_with_rules(self, text: str, task_type: str, req) -> dict:
        return {
            "purpose": self._extract_purpose(text, task_type),
            "main_subject": self._extract_main_subject(text, task_type),
            "style": req.style_preference or DEFAULT_STYLE.get(task_type, "现代简洁"),
            "target_audience": req.target_audience or DEFAULT_AUDIENCE.get(task_type, "通用受众"),
            "aspect_ratio": req.aspect_ratio or self._default_aspect_ratio(task_type),
            "user_input": text,
        }

    def _extract_purpose(self, text: str, task_type: str) -> str:
        purposes = {
            "ecommerce_banner": "推广商品并促进购买转化",
            "academic_figure": "展示研究方法或实验流程",
            "ppt_visual": "汇报展示封面或配图",
        }
        if len(text) > 10:
            return text.strip()[:120]
        return purposes.get(task_type, "视觉内容生成")

    def _extract_main_subject(self, text: str, task_type: str) -> str:
        lower = text.lower()
        if task_type == "ecommerce_banner":
            for kw in ("商品", "产品", "product"):
                if kw in lower:
                    idx = lower.find(kw)
                    return text[max(0, idx - 5) : idx + 20].strip() or "促销商品"
            return "促销商品"
        if task_type == "academic_figure":
            for kw in ("方法", "模型", "pipeline", "framework"):
                if kw in lower:
                    return f"学术{kw}流程"
            return "研究方法流程"
        return text.strip().split("，")[0].split(",")[0][:40] or "汇报主题"

    def _default_aspect_ratio(self, task_type: str) -> str:
        return {
            "ecommerce_banner": "1:1",
            "academic_figure": "4:3",
            "ppt_visual": "16:9",
        }.get(task_type, "16:9")
