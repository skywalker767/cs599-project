"""Visual specification agent with domain-aware fields and provenance tracking."""

from __future__ import annotations

import re

from app.llm.llm_factory import get_llm
from app.llm.parsing import llm_trace_meta, parse_json_from_text
from app.models.schemas import (
    AcademicDiagramFields,
    EducationalInfographicFields,
    ProductPosterFields,
    VisualSpec,
    WorkflowState,
)
from app.tools.trace_logger import append_trace

DOMAIN_DEFAULTS: dict[str, dict] = {
    "ecommerce_banner": {
        "scenario": "电商平台商品推广场景",
        "purpose": "突出商品卖点，促进点击与购买",
        "style": "促销感强、色彩鲜明、平台适配",
        "key_elements": ["商品主图", "促销标语", "价格/折扣", "CTA按钮"],
        "text_requirements": ["商品名称", "促销信息", "限时优惠"],
        "constraints": ["符合电商平台尺寸规范", "禁用夸大宣传", "信息层次清晰"],
        "avoid": ["绝对化用语", "虚假承诺", "杂乱排版"],
        "output_format": "png",
        "evaluation_dimensions": ["卖点突出", "促销感", "平台合规", "视觉吸引力"],
    },
    "academic_figure": {
        "scenario": "学术论文方法或实验说明",
        "purpose": "清晰展示模块关系与处理流程",
        "style": "学术简洁、白底、标签可读",
        "key_elements": ["输入模块", "处理模块", "模型模块", "输出模块", "连接箭头"],
        "text_requirements": ["模块标签", "数据流向", "图注说明"],
        "constraints": ["箭头方向明确", "字号适合印刷", "模块对齐"],
        "avoid": ["过度装饰", "低对比度文字", "模糊标签"],
        "output_format": "svg",
        "evaluation_dimensions": ["模块关系", "标签可读性", "流程逻辑", "学术风格"],
    },
    "ppt_visual": {
        "scenario": "商务或学术汇报演示",
        "purpose": "专业封面或配图，支撑汇报主题",
        "style": "专业简洁、科技感、留白充足",
        "key_elements": ["主标题", "副标题", "抽象图形", "品牌区域"],
        "text_requirements": ["标题醒目", "副标题补充", "日期/机构可选"],
        "constraints": ["16:9宽屏适配", "标题可读性", "背景不干扰文字"],
        "avoid": ["信息过载", "低对比标题", "杂乱背景"],
        "output_format": "png",
        "evaluation_dimensions": ["专业感", "简洁度", "标题可读性", "汇报适配"],
    },
}

VISUAL_SPEC_SYSTEM = (
    "You are VisualSpecAgent for VisionFlow, a senior art director translating a creative "
    "brief into a concrete, renderable visual specification. "
    "Return ONLY valid JSON with these keys:\n"
    "- title: a short, evocative title for the visual.\n"
    "- scenario: the concrete scene/setting described in vivid terms.\n"
    "- key_elements: list of 4-6 SPECIFIC visual elements that must appear (objects, layout "
    "regions, labels, callouts) — concrete nouns, not abstract concepts.\n"
    "- style: a detailed style line covering color palette, lighting, composition and design language.\n"
    "- purpose: the communication goal in one sentence.\n"
    "Rules: every element must be visually depictable; favor concrete, camera-ready descriptions; "
    "respect the requirement's aspect_ratio and audience. "
    "For academic_figure, key_elements should be ordered pipeline modules. "
    "If DOCUMENT CONTEXT is given, derive key_elements from the document's method/contributions. "
    "Use Chinese for values. Agent hint: visual_spec."
)


class VisualSpecAgent:
    """Generate structured VisualSpec from requirements and task type."""

    def __init__(self, llm=None, requested_provider: str | None = None):
        if llm is None:
            self.llm, self.requested_provider = get_llm()
        else:
            self.llm = llm
            self.requested_provider = requested_provider or llm.provider_name

    def build(self, state: WorkflowState) -> WorkflowState:
        """Build VisualSpec based on task_type, requirement, and clarification."""
        req = state.requirement
        task_type = state.task_type
        defaults = DOMAIN_DEFAULTS.get(task_type, DOMAIN_DEFAULTS["ppt_visual"])
        clarification = req.get("clarification", state.clarification_resolved)
        provenance: dict[str, str] = {}

        title = self._field_with_provenance(
            req.get("main_subject"),
            "视觉内容",
            "title",
            provenance,
            max_len=60,
        )
        key_elements = list(defaults["key_elements"])
        for el in key_elements:
            provenance.setdefault(f"key_element:{el}", "default")

        words = [w for w in req.get("user_input", "").replace("，", " ").split() if len(w) > 1]
        if words:
            key_elements = key_elements[:2] + words[:3] + key_elements[2:]
            key_elements = key_elements[:6]
            for w in words[:3]:
                provenance[f"key_element:{w}"] = "user_input"

        style = self._field_with_provenance(
            req.get("style"), defaults["style"], "style", provenance
        )
        purpose = self._field_with_provenance(
            req.get("purpose"), defaults["purpose"], "purpose", provenance
        )
        scenario = self._field_with_provenance(
            req.get("scenario"), defaults["scenario"], "scenario", provenance
        )
        constraints = list(defaults["constraints"])
        avoid = list(defaults["avoid"])
        text_requirements = list(defaults["text_requirements"])
        evaluation_dimensions = list(defaults["evaluation_dimensions"])
        output_format = req.get("output_format") or defaults["output_format"]
        provenance.setdefault(
            "output_format", "default" if not req.get("output_format") else "user_input"
        )

        aspect_ratio = req.get("aspect_ratio") or state.request.aspect_ratio or "16:9"
        provenance["aspect_ratio"] = (
            "user_input" if req.get("aspect_ratio") or state.request.aspect_ratio else "default"
        )

        target_audience = req.get("target_audience") or state.request.target_audience or "通用受众"
        provenance["target_audience"] = (
            "user_input"
            if (req.get("target_audience") or state.request.target_audience)
            else "default"
        )

        (
            key_elements,
            constraints,
            avoid,
            text_requirements,
            evaluation_dimensions,
            output_format,
        ) = self._apply_clarification_to_spec(
            task_type,
            clarification,
            req,
            key_elements,
            constraints,
            avoid,
            text_requirements,
            evaluation_dimensions,
            output_format,
        )

        llm_meta = llm_trace_meta(self.requested_provider, self.llm.provider_name, False, False)
        llm_data, llm_meta = self._try_llm(req, task_type)
        if llm_data:
            title = str(llm_data.get("title", title))[:60]
            provenance["title"] = "inferred"
            style = llm_data.get("style", style)
            provenance["style"] = "inferred"
            purpose = llm_data.get("purpose", purpose)
            provenance["purpose"] = "inferred"
            scenario = llm_data.get("scenario", scenario)
            provenance["scenario"] = "inferred"
            if isinstance(llm_data.get("key_elements"), list) and llm_data["key_elements"]:
                key_elements = llm_data["key_elements"][:6]
                for el in key_elements:
                    provenance[f"key_element:{el}"] = "inferred"

        product_poster = (
            self._build_product_fields(req, key_elements, provenance)
            if task_type == "ecommerce_banner"
            else None
        )
        educational = (
            self._build_educational_fields(req, key_elements, provenance)
            if task_type == "ppt_visual"
            else None
        )
        academic = (
            self._build_academic_fields(req, key_elements, output_format, provenance)
            if task_type == "academic_figure"
            else None
        )

        main_subject = req.get("main_subject") or title
        provenance["main_subject"] = "user_input" if req.get("main_subject") else "inferred"

        visual_spec = VisualSpec(
            task_type=task_type,
            title=title,
            scenario=scenario,
            target_audience=target_audience,
            purpose=purpose,
            style=style,
            aspect_ratio=aspect_ratio,
            main_subject=main_subject,
            key_elements=key_elements,
            text_requirements=text_requirements,
            constraints=constraints,
            avoid=avoid,
            output_format=output_format,
            evaluation_dimensions=evaluation_dimensions,
            product_poster=product_poster,
            educational=educational,
            academic=academic,
            field_provenance=provenance,
        )

        state.visual_spec = visual_spec
        append_trace(
            state.traces,
            agent_name="VisualSpecAgent",
            step="build_visual_spec",
            input_summary=str(req)[:120],
            output_summary=f"title={title}, elements={len(key_elements)}",
            metadata={
                **visual_spec.model_dump(),
                "clarification_applied": clarification,
                "field_provenance": provenance,
                **llm_meta,
            },
            pipeline_step="visual_spec_created",
        )
        return state

    @staticmethod
    def _field_with_provenance(
        user_val: str | None,
        default_val: str,
        field_name: str,
        provenance: dict[str, str],
        max_len: int | None = None,
    ) -> str:
        if user_val and str(user_val).strip():
            provenance[field_name] = "user_input"
            val = str(user_val).strip()
        else:
            provenance[field_name] = "default"
            val = default_val
        return val[:max_len] if max_len else val

    def _build_product_fields(
        self,
        req: dict,
        key_elements: list[str],
        provenance: dict[str, str],
    ) -> ProductPosterFields:
        user_input = req.get("user_input", "")
        product_name = (
            req.get("main_subject") or self._extract_quoted(user_input) or key_elements[0]
        )
        provenance["product_poster.product_name"] = (
            "user_input" if req.get("main_subject") else "inferred"
        )

        benefits = [w for w in re.findall(r"『([^』]+)』|「([^」]+)」", user_input) if any(w)]
        benefits = [b[0] or b[1] for b in benefits] or key_elements[1:3]
        for b in benefits:
            provenance.setdefault(
                f"product_poster.benefit:{b}", "user_input" if "『" in user_input else "inferred"
            )

        cta = "立即抢购" if "抢购" in user_input else ("立即购买" if "购买" in user_input else "")
        provenance["product_poster.cta"] = "user_input" if cta else "default"

        return ProductPosterFields(
            product_name=product_name,
            audience=req.get("target_audience", ""),
            benefits=benefits[:5],
            cta=cta or "了解更多",
            brand_tone=req.get("style", ""),
            layout=(
                "product-dominant" if "60%" in user_input or "主图" in user_input else "balanced"
            ),
            color_palette=self._extract_colors(user_input),
            typography="bold sans-serif promotional",
        )

    def _build_educational_fields(
        self,
        req: dict,
        key_elements: list[str],
        provenance: dict[str, str],
    ) -> EducationalInfographicFields:
        user_input = req.get("user_input", "")
        topic = req.get("main_subject") or key_elements[0]
        provenance["educational.topic"] = "user_input" if req.get("main_subject") else "inferred"
        return EducationalInfographicFields(
            topic=topic,
            learning_goal=req.get("purpose", "帮助受众理解核心概念"),
            key_concepts=key_elements[:5],
            hierarchy="top-down" if "流程" in user_input else "layered",
            audience=req.get("target_audience", "学习者"),
            visual_metaphor="icons-and-labels",
            accessibility_notes=["高对比文字", "清晰层级"],
        )

    def _build_academic_fields(
        self,
        req: dict,
        key_elements: list[str],
        output_format: str,
        provenance: dict[str, str],
    ) -> AcademicDiagramFields:
        entities = key_elements[:6]
        for e in entities:
            provenance.setdefault(f"academic.entity:{e}", "inferred")
        relationships = [f"{entities[i]} → {entities[i+1]}" for i in range(len(entities) - 1)]
        return AcademicDiagramFields(
            entities=entities,
            relationships=relationships,
            labels=entities,
            directionality="left-to-right",
            layout="horizontal-pipeline",
            notation="block-diagram",
            caption=req.get("main_subject", "") or "方法流程示意图",
            export_format=output_format,
        )

    @staticmethod
    def _extract_quoted(text: str) -> str:
        m = re.search(r"『([^』]+)』|「([^」]+)」", text)
        if m:
            return m.group(1) or m.group(2) or ""
        return ""

    @staticmethod
    def _extract_colors(text: str) -> list[str]:
        colors = re.findall(r"(薄荷绿|渐变|蓝|红|金|白底|深色)", text)
        return colors[:4] or ["brand-primary"]

    def _apply_clarification_to_spec(
        self,
        task_type: str,
        clarification: dict[str, str],
        req: dict,
        key_elements: list[str],
        constraints: list[str],
        avoid: list[str],
        text_requirements: list[str],
        evaluation_dimensions: list[str],
        output_format: str,
    ) -> tuple:
        if not clarification:
            return (
                key_elements,
                constraints,
                avoid,
                text_requirements,
                evaluation_dimensions,
                output_format,
            )

        density = clarification.get("information_density")
        if density == "low":
            constraints.append("保持极简，元素不超过3个")
        elif density == "high":
            constraints.append("允许信息丰富，需保持层次清晰")

        text_level = clarification.get("text_level")
        if text_level == "none":
            text_requirements = ["无文字，纯视觉"]
            constraints.append("画面中不包含文字")
        elif text_level == "full_copy":
            text_requirements.append("包含完整文案区域")

        if task_type == "ecommerce_banner":
            compliance = clarification.get("compliance_level")
            if compliance == "conservative":
                avoid.extend(
                    [
                        "absolute advertising claims",
                        "exaggerated medical or efficacy claims",
                    ]
                )
                constraints.append("use conservative commercial wording")
            promo = clarification.get("promotion_intensity")
            if promo == "strong":
                key_elements.append("强促销标签")
                evaluation_dimensions.append("促销冲击力")
            ratio = clarification.get("product_ratio")
            if ratio == "large":
                constraints.append("商品主体占画面60%以上")

        elif task_type == "academic_figure":
            fmt = clarification.get("output_format") or req.get("output_format")
            if fmt:
                output_format = fmt if fmt != "mermaid" else "svg"
            if fmt == "svg" or output_format == "svg":
                constraints.append("ensure readable labels and clear arrows")
            complexity = clarification.get("structure_complexity")
            if complexity == "simple":
                key_elements = key_elements[:4]
            elif complexity == "complex":
                constraints.append("支持多层模块嵌套")
            emphasis = clarification.get("emphasis")
            if emphasis:
                for em in str(emphasis).split(";"):
                    em = em.strip()
                    if em:
                        evaluation_dimensions.append(f"emphasis:{em}")

        elif task_type == "ppt_visual":
            blank = clarification.get("layout_blank") or req.get("layout_blank")
            if blank == "left":
                constraints.append("reserve blank space on the left side for slide title")
            elif blank == "right":
                constraints.append("reserve blank space on the right side for slide title")
            elif blank == "center":
                constraints.append("reserve central blank area for title overlay")
            strength = clarification.get("visual_strength")
            if strength == "background":
                constraints.append("low-distraction background visual")
            elif strength == "strong":
                evaluation_dimensions.append("visual impact")

        return (
            key_elements,
            constraints,
            avoid,
            text_requirements,
            evaluation_dimensions,
            output_format,
        )

    def _try_llm(self, req: dict, task_type: str) -> tuple[dict | None, dict]:
        actual = self.llm.provider_name
        fallback = False
        try:
            doc_block = ""
            doc_ctx = req.get("document_context")
            if doc_ctx:
                doc_block = f"\nDOCUMENT CONTEXT:\n{str(doc_ctx)[:1500]}"
            user_prompt = f"task_type: {task_type}\nrequirement: {req}{doc_block}"
            raw = self.llm.generate_text(VISUAL_SPEC_SYSTEM, user_prompt)
            parsed = parse_json_from_text(raw)
            if parsed:
                return parsed, llm_trace_meta(self.requested_provider, actual, fallback, True)
            return None, llm_trace_meta(self.requested_provider, actual, True, False)
        except Exception:
            return None, llm_trace_meta(self.requested_provider, actual, True, False)
