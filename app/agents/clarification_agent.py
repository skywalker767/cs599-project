"""Clarification question templates and agent."""

from __future__ import annotations

import hashlib
import re

from app.llm.llm_factory import get_llm
from app.llm.parsing import llm_trace_meta, parse_json_from_text
from app.models.schemas import (
    ClarificationOption,
    ClarificationQuestion,
    WorkflowState,
)
from app.tools.trace_logger import append_trace

CLARIFICATION_SYSTEM = (
    "You are ClarificationAgent for VisionFlow. Your job is to surface the 1-2 MOST decision-"
    "critical, request-specific ambiguities that would materially change the final visual — "
    "things NOT already obvious from the user_input. "
    "Avoid generic questions (style/ratio are already covered elsewhere); instead ask about "
    "concrete choices unique to THIS request (e.g. which selling point to headline, which "
    "pipeline stage to emphasize, what mood/props to feature). "
    "Each question is single_choice OR multi_choice with 3-5 concrete options. "
    "Use multi_choice when multiple options can reasonably combine; otherwise single_choice. "
    "For multi_choice, set incompatible_with on each option (list of option values that "
    "cannot be selected together with it). For single_choice omit incompatible_with. "
    'Return ONLY valid JSON: {"questions": [{"question_id": "snake_case_unique", '
    '"question_text": "...", "question_type": "single_choice|multi_choice", '
    '"options": [{"label": "...", "value": "snake_case", '
    '"description": "..."|null, "incompatible_with": ["other_value"]|[]}], '
    '"default_value": "...", "reason": "why this matters"}]}. '
    "Use Chinese for question_text, labels and reason. Agent hint: clarification."
)
# ── Reusable question builders ─────────────────────────────────


def _q(
    question_id: str,
    question_text: str,
    options: list[tuple[str, str, str | None]],
    default_value: str,
    reason: str,
    *,
    question_type: str = "single_choice",
    incompatible: dict[str, list[str]] | None = None,
) -> ClarificationQuestion:
    option_objs: list[ClarificationOption] = []
    values = [value for _, value, _ in options]
    for label, value, desc in options:
        inc: list[str] = []
        if question_type == "single_choice":
            inc = [v for v in values if v != value]
        elif incompatible:
            inc = [v for v in incompatible.get(value, []) if v in values]
        option_objs.append(
            ClarificationOption(
                label=label,
                value=value,
                description=desc,
                incompatible_with=inc,
            )
        )
    return ClarificationQuestion(
        question_id=question_id,
        question_text=question_text,
        question_type=question_type,
        options=option_objs,
        default_value=default_value,
        reason=reason,
    )


COMMON_STYLE = _q(
    "style",
    "请选择整体视觉风格",
    [
        ("简洁专业", "professional_minimal", None),
        ("科技未来感", "tech_futuristic", None),
        ("清新自然", "fresh_natural", None),
        ("高级极简", "premium_minimal", None),
        ("活泼年轻", "lively_young", None),
        ("商务稳重", "business_stable", None),
    ],
    "professional_minimal",
    "风格决定整体色调、排版气质和受众感知，需在生成 Visual Spec 前明确。",
)

COMMON_ASPECT = _q(
    "aspect_ratio",
    "请选择图片比例",
    [
        ("方图 1:1", "1:1", None),
        ("小红书/电商竖图 4:5", "4:5", None),
        ("PPT/横版 16:9", "16:9", None),
        ("竖版海报 3:4", "3:4", None),
        ("报告页面 A4", "A4", None),
    ],
    "16:9",
    "比例影响构图与平台适配，不同任务对尺寸要求差异较大。",
)

COMMON_DENSITY = _q(
    "information_density",
    "请选择信息密度",
    [
        ("极简，少元素", "low", None),
        ("适中，主体清晰", "medium", None),
        ("信息丰富，适合说明型内容", "high", None),
    ],
    "medium",
    "信息密度影响画面元素数量与留白，需与任务目的匹配。",
)

COMMON_TEXT = _q(
    "text_level",
    "是否需要图片中包含文字",
    [
        ("不需要文字", "none", None),
        ("只需要标题", "title_only", None),
        ("需要少量关键词", "key_points", None),
        ("需要完整文案", "full_copy", None),
    ],
    "title_only",
    "文字层级影响排版区域预留和 Prompt 中的 text requirements。",
)

# ── Ecommerce questions ────────────────────────────────────────

ECOM_PLATFORM = _q(
    "platform",
    "请选择目标投放平台",
    [
        ("小红书", "xiaohongshu", None),
        ("淘宝", "taobao", None),
        ("京东", "jd", None),
        ("抖音", "douyin", None),
        ("微信朋友圈", "wechat", None),
    ],
    "xiaohongshu",
    "不同平台对尺寸、风格和合规要求不同，需提前对齐平台规范。",
)

ECOM_MARKETING = _q(
    "marketing_goal",
    "请选择营销目标",
    [
        ("提升点击率", "click_through", None),
        ("突出商品主体", "product_focus", None),
        ("强调优惠促销", "discount_promotion", None),
        ("品牌种草", "brand_seeding", None),
        ("新品发布", "new_product_launch", None),
    ],
    "product_focus",
    "营销目标决定画面重心是商品、优惠还是品牌故事。",
)

ECOM_PRODUCT_RATIO = _q(
    "product_ratio",
    "请选择商品在画面中的占比",
    [
        ("商品大主体", "large", None),
        ("商品中等占比", "medium", None),
        ("场景氛围优先", "scene_first", None),
    ],
    "large",
    "商品占比影响构图方式和背景处理策略。",
)

ECOM_PROMOTION = _q(
    "promotion_intensity",
    "请选择促销强度",
    [
        ("无促销", "none", None),
        ("轻促销", "light", None),
        ("强促销", "strong", None),
    ],
    "light",
    "促销强度影响 CTA、折扣标签和色彩对比度。",
)

ECOM_COMPLIANCE = _q(
    "compliance_level",
    "请选择合规策略",
    [
        ("保守合规，避免风险表达", "conservative", None),
        ("标准合规", "standard", None),
        ("创意优先，保留基础风险检查", "creative", None),
    ],
    "standard",
    "合规策略决定 avoid 列表和文案约束的严格程度。",
)

# ── Academic questions ─────────────────────────────────────────

ACAD_FIGURE_TYPE = _q(
    "figure_type",
    "请选择论文图类型",
    [
        ("方法流程图", "method_pipeline", None),
        ("模型结构图", "model_architecture", None),
        ("实验流程图", "experiment_workflow", None),
        ("图形摘要", "graphical_abstract", None),
        ("对比框架图", "comparison_framework", None),
    ],
    "method_pipeline",
    "图类型决定模块组织方式和 Visual Spec 的 key_elements。",
)

ACAD_OUTPUT = _q(
    "output_format",
    "请选择输出格式",
    [
        ("SVG 矢量图", "svg", None),
        ("Mermaid 源码", "mermaid", None),
        ("PNG 图片", "png", None),
        ("PDF 图示", "pdf", None),
    ],
    "svg",
    "输出格式影响生成工具链（SVG 流程图 vs 位图）。",
)

ACAD_STYLE = _q(
    "academic_style",
    "请选择学术视觉风格",
    [
        ("黑白极简", "black_white_minimal", None),
        ("蓝灰科技", "blue_gray_tech", None),
        ("期刊论文风", "journal_clean", None),
        ("会议海报风", "conference_poster", None),
    ],
    "journal_clean",
    "学术风格影响配色、线宽和标签排版规范。",
)

ACAD_LABEL_LANG = _q(
    "label_language",
    "请选择图中文字语言",
    [
        ("英文标签", "en", None),
        ("中文标签", "zh", None),
    ],
    "en",
    "标签语言影响模块命名和图注建议。",
)

ACAD_COMPLEXITY = _q(
    "structure_complexity",
    "请选择结构复杂度",
    [
        ("简单结构，3-4 个模块", "simple", None),
        ("中等结构，5-7 个模块", "medium", None),
        ("复杂结构，多层模块", "complex", None),
    ],
    "medium",
    "复杂度决定流程图节点数量和层次深度。",
)

ACAD_EMPHASIS = _q(
    "emphasis",
    "请选择重点表达内容（可多选）",
    [
        ("数据流", "data_flow", None),
        ("模块关系", "module_relation", None),
        ("算法流程", "algorithm_process", None),
        ("实验设计", "experiment_design", None),
        ("核心贡献点", "contribution", None),
    ],
    "algorithm_process",
    "重点内容影响箭头标注和 evaluation_dimensions；可组合选择多个侧重点。",
    question_type="multi_choice",
)

# ── PPT questions ──────────────────────────────────────────────

PPT_SLIDE = _q(
    "slide_position",
    "请选择图片使用位置",
    [
        ("封面", "cover", None),
        ("章节页", "section", None),
        ("内容页", "content", None),
        ("结尾页", "ending", None),
    ],
    "cover",
    "幻灯片位置决定标题区、留白和构图策略。",
)

PPT_CONTEXT = _q(
    "presentation_context",
    "请选择汇报场景",
    [
        ("课程答辩", "course_defense", None),
        ("商业汇报", "business_report", None),
        ("技术分享", "technical_sharing", None),
        ("科研展示", "research_presentation", None),
    ],
    "course_defense",
    "汇报场景影响受众、语气和视觉正式程度。",
)

PPT_BLANK = _q(
    "layout_blank",
    "请选择留白位置",
    [
        ("左侧留白", "left", None),
        ("右侧留白", "right", None),
        ("中间留白", "center", None),
        ("不需要留白", "none", None),
    ],
    "left",
    "留白位置需与标题和正文区域对齐，避免遮挡文字。",
)

PPT_FOCUS = _q(
    "visual_focus",
    "请选择画面重心（可多选）",
    [
        ("抽象概念", "abstract_concept", None),
        ("人物协作", "people_collaboration", None),
        ("技术系统", "technical_system", None),
        ("数据增长", "data_growth", None),
        ("未来城市", "future_city", None),
    ],
    "technical_system",
    "画面重心决定主视觉元素；可选择多个元素组合呈现。",
    question_type="multi_choice",
    incompatible={
        "abstract_concept": ["future_city"],
        "future_city": ["abstract_concept"],
    },
)

PPT_STRENGTH = _q(
    "visual_strength",
    "请选择视觉冲击力",
    [
        ("背景型，低干扰", "background", None),
        ("平衡型", "balanced", None),
        ("强视觉冲击型", "strong", None),
    ],
    "balanced",
    "冲击力影响背景复杂度与前景对比度。",
)

# ── Extra optional questions (rotated for diversity) ───────────

ECOM_COLOR_PALETTE = _q(
    "color_palette",
    "请选择主色调方向",
    [
        ("暖色系（橙红金）", "warm", None),
        ("冷色系（蓝绿）", "cool", None),
        ("中性高级灰", "neutral", None),
        ("高饱和活力色", "vibrant", None),
        ("马卡龙柔和色", "pastel", None),
    ],
    "cool",
    "主色调影响商品质感与平台点击率。",
)

ECOM_SCENE = _q(
    "scene_setting",
    "请选择场景设定",
    [
        ("纯色棚拍", "studio", None),
        ("生活场景", "lifestyle", None),
        ("户外自然", "outdoor", None),
        ("极简留白", "minimal", None),
        ("节日主题场景", "festive", None),
    ],
    "lifestyle",
    "场景决定背景元素与氛围道具。",
)

ECOM_CTA_STYLE = _q(
    "cta_style",
    "请选择行动号召样式",
    [
        ("按钮型 CTA", "button", None),
        ("横幅条型", "banner_strip", None),
        ("角标标签", "corner_tag", None),
        ("无 CTA", "none", None),
    ],
    "button",
    "CTA 样式影响用户点击路径设计。",
)

ACAD_LAYOUT = _q(
    "layout_direction",
    "请选择布局方向",
    [
        ("自上而下", "top_down", None),
        ("自左而右", "left_right", None),
        ("中心辐射", "radial", None),
        ("分层嵌套", "nested", None),
    ],
    "top_down",
    "布局方向影响读者理解路径。",
)

ACAD_COLOR_SCHEME = _q(
    "color_scheme",
    "请选择配色方案",
    [
        ("单色灰阶", "grayscale", None),
        ("蓝灰学术", "blue_gray", None),
        ("柔和马卡龙", "soft_color", None),
        ("高对比强调", "high_contrast", None),
    ],
    "blue_gray",
    "配色影响印刷效果与可读性。",
)

PPT_COLOR_MOOD = _q(
    "color_mood",
    "请选择色彩情绪",
    [
        ("冷静专业蓝", "professional_blue", None),
        ("活力创新橙", "energetic_orange", None),
        ("自然生态绿", "eco_green", None),
        ("高端黑金", "luxury_dark", None),
        ("柔和浅色系", "soft_light", None),
    ],
    "professional_blue",
    "色彩情绪决定汇报第一印象。",
)

PPT_BRAND_TONE = _q(
    "brand_tone",
    "请选择品牌气质",
    [
        ("权威可信", "authoritative", None),
        ("亲和友好", "friendly", None),
        ("前沿创新", "innovative", None),
        ("稳健务实", "pragmatic", None),
    ],
    "innovative",
    "品牌气质影响图形语言与字体选择。",
)

# Core questions (stable IDs, always included)
DOMAIN_CORE: dict[str, list[ClarificationQuestion]] = {
    "ecommerce_banner": [
        ECOM_PLATFORM,
        ECOM_MARKETING,
        COMMON_STYLE,
        COMMON_ASPECT,
    ],
    "academic_figure": [
        ACAD_FIGURE_TYPE,
        ACAD_OUTPUT,
        ACAD_LABEL_LANG,
        ACAD_STYLE,
    ],
    "ppt_visual": [
        PPT_SLIDE,
        PPT_BLANK,
        PPT_FOCUS,
        COMMON_ASPECT,
    ],
}

# Optional pool (rotated by user input hash for variety)
DOMAIN_OPTIONAL: dict[str, list[ClarificationQuestion]] = {
    "ecommerce_banner": [
        ECOM_PRODUCT_RATIO,
        ECOM_PROMOTION,
        ECOM_COMPLIANCE,
        COMMON_DENSITY,
        COMMON_TEXT,
        ECOM_COLOR_PALETTE,
        ECOM_SCENE,
        ECOM_CTA_STYLE,
    ],
    "academic_figure": [
        ACAD_COMPLEXITY,
        ACAD_EMPHASIS,
        ACAD_LAYOUT,
        ACAD_COLOR_SCHEME,
        COMMON_DENSITY,
    ],
    "ppt_visual": [
        PPT_CONTEXT,
        PPT_STRENGTH,
        COMMON_STYLE,
        PPT_COLOR_MOOD,
        PPT_BRAND_TONE,
        COMMON_DENSITY,
        COMMON_TEXT,
    ],
}

# Legacy alias for tests/docs
DOMAIN_QUESTIONS: dict[str, list[ClarificationQuestion]] = {
    k: DOMAIN_CORE[k] + DOMAIN_OPTIONAL.get(k, [])[:2] for k in DOMAIN_CORE
}


class ClarificationAgent:
    """Generate clarification multiple-choice questions before generation."""

    MAX_QUESTIONS = 8
    OPTIONAL_PICK = 2
    LLM_MAX_QUESTIONS = 2

    def __init__(self, llm=None, requested_provider: str | None = None):
        if llm is None:
            self.llm, self.requested_provider = get_llm()
        else:
            self.llm = llm
            self.requested_provider = requested_provider or llm.provider_name
        self._last_sources: dict[str, str] = {}
        self._last_llm_meta: dict = {}

    def generate_questions(
        self,
        user_input: str,
        task_type: str,
        *,
        skip_llm: bool = False,
    ) -> list[ClarificationQuestion]:
        """Return core + rotated optional + DeepSeek dynamic questions."""
        self._last_sources = {}
        self._last_llm_meta = {}

        core = list(DOMAIN_CORE.get(task_type, DOMAIN_CORE["ppt_visual"]))
        for q in core:
            self._last_sources[q.question_id] = "core"

        optional = self._pick_optional(task_type, user_input, {q.question_id for q in core})
        for q in optional:
            self._last_sources[q.question_id] = "optional"

        merged = self._merge_by_id(core + optional)

        if skip_llm:
            self._last_llm_meta = {
                "llm_requested_provider": self.requested_provider,
                "llm_skipped": True,
                "llm_reason": "clarification_answers already provided",
            }
        else:
            llm_questions, self._last_llm_meta = self._try_llm_questions(
                user_input,
                task_type,
                merged,
            )
            for q in llm_questions:
                self._last_sources[q.question_id] = "llm"
            merged = self._merge_by_id(merged + llm_questions)

        return merged[: self.MAX_QUESTIONS]

    def _pick_optional(
        self,
        task_type: str,
        user_input: str,
        exclude_ids: set[str],
    ) -> list[ClarificationQuestion]:
        pool = [q for q in DOMAIN_OPTIONAL.get(task_type, []) if q.question_id not in exclude_ids]
        if not pool:
            return []

        seed = int(hashlib.md5(f"{task_type}:{user_input}".encode()).hexdigest(), 16)
        picked: list[ClarificationQuestion] = []
        for i in range(min(self.OPTIONAL_PICK, len(pool))):
            idx = (seed + i * 7) % len(pool)
            candidate = pool[idx]
            if candidate.question_id not in {q.question_id for q in picked}:
                picked.append(candidate)
        return picked

    def _try_llm_questions(
        self,
        user_input: str,
        task_type: str,
        existing: list[ClarificationQuestion],
    ) -> tuple[list[ClarificationQuestion], dict]:
        existing_ids = {q.question_id for q in existing}
        existing_summary = ", ".join(existing_ids) or "none"
        actual = self.llm.provider_name

        try:
            user_prompt = (
                f"task_type: {task_type}\n"
                f"user_input: {user_input}\n"
                f"already_covered_question_ids: {existing_summary}\n"
                f"Generate up to {self.LLM_MAX_QUESTIONS} NEW questions not duplicating the above IDs."
            )
            raw = self.llm.generate_text(CLARIFICATION_SYSTEM, user_prompt)
            parsed = parse_json_from_text(raw)
            questions = self._parse_llm_questions(parsed, existing_ids)
            meta = llm_trace_meta(self.requested_provider, actual, False, bool(questions))
            meta["llm_question_count"] = len(questions)
            return questions[: self.LLM_MAX_QUESTIONS], meta
        except Exception as exc:
            return [], llm_trace_meta(
                self.requested_provider,
                actual,
                False,
                False,
                extra={"llm_error": str(exc)[:120]},
            )

    def _parse_llm_questions(
        self,
        parsed: dict | None,
        existing_ids: set[str],
    ) -> list[ClarificationQuestion]:
        if not parsed:
            return []

        raw_list = parsed.get("questions", [])
        if not isinstance(raw_list, list):
            return []

        result: list[ClarificationQuestion] = []
        for item in raw_list:
            if not isinstance(item, dict):
                continue
            qid = self._sanitize_id(str(item.get("question_id", "")))
            if not qid or qid in existing_ids:
                continue

            options_raw = item.get("options") or []
            option_objs: list[ClarificationOption] = []
            parsed_values: list[str] = []
            for opt in options_raw:
                if not isinstance(opt, dict):
                    continue
                label = str(opt.get("label", "")).strip()
                value = self._sanitize_id(str(opt.get("value", label)))
                if label and value:
                    parsed_values.append(value)
                    inc_raw = opt.get("incompatible_with") or []
                    inc = [
                        self._sanitize_id(str(v))
                        for v in inc_raw
                        if isinstance(v, str) and self._sanitize_id(str(v))
                    ]
                    option_objs.append(
                        ClarificationOption(
                            label=label,
                            value=value,
                            description=opt.get("description"),
                            incompatible_with=inc,
                        )
                    )

            if len(option_objs) < 2:
                continue

            qtype = str(item.get("question_type", "single_choice")).strip() or "single_choice"
            if qtype not in ("single_choice", "multi_choice"):
                qtype = "single_choice"
            if qtype == "single_choice":
                vals = [o.value for o in option_objs]
                option_objs = [
                    o.model_copy(update={"incompatible_with": [v for v in vals if v != o.value]})
                    for o in option_objs
                ]

            default = self._sanitize_id(str(item.get("default_value", option_objs[0].value)))
            if default not in {o.value for o in option_objs}:
                default = option_objs[0].value

            question_text = str(item.get("question_text", "")).strip()
            reason = str(item.get("reason", "根据您的具体需求生成的个性化澄清问题。")).strip()
            if not question_text:
                continue

            result.append(
                ClarificationQuestion(
                    question_id=qid,
                    question_text=question_text,
                    question_type=qtype,
                    options=option_objs,
                    default_value=default,
                    reason=reason,
                )
            )
            existing_ids.add(qid)
        return result

    @staticmethod
    def _sanitize_id(raw: str) -> str:
        cleaned = re.sub(r"[^a-zA-Z0-9_]+", "_", raw.strip().lower())
        cleaned = re.sub(r"_+", "_", cleaned).strip("_")
        return cleaned[:48]

    @staticmethod
    def _merge_by_id(questions: list[ClarificationQuestion]) -> list[ClarificationQuestion]:
        seen: dict[str, ClarificationQuestion] = {}
        for q in questions:
            if q.question_id not in seen:
                seen[q.question_id] = q
        return list(seen.values())

    @staticmethod
    def _answer_values(answer) -> list[str]:
        if getattr(answer, "selected_values", None):
            return [str(v) for v in answer.selected_values if str(v)]
        raw = getattr(answer, "selected_value", "") or ""
        if ";" in raw:
            return [v for v in raw.split(";") if v]
        return [raw] if raw else []

    def resolve_answers(
        self,
        questions: list[ClarificationQuestion],
        answers: list,
    ) -> dict[str, str]:
        """Merge user answers with defaults for unanswered questions."""
        answer_map: dict[str, str] = {}
        for a in answers:
            vals = self._answer_values(a)
            if vals:
                answer_map[a.question_id] = ";".join(vals)

        resolved: dict[str, str] = {}
        for q in questions:
            resolved[q.question_id] = (
                answer_map.get(q.question_id) or q.default_value or q.options[0].value
            )
        for qid, val in answer_map.items():
            if qid not in resolved and val:
                resolved[qid] = val
        return resolved

    def apply_in_workflow(self, state: WorkflowState) -> WorkflowState:
        """Generate questions, resolve answers, store in state, write trace."""
        skip_llm = (
            bool(state.request.clarification_answers) and not state.request.skip_clarification
        )
        questions = self.generate_questions(
            state.request.user_input,
            state.task_type,
            skip_llm=skip_llm,
        )
        state.clarification_questions = questions

        if state.request.skip_clarification:
            resolved = self.resolve_answers(questions, [])
        else:
            resolved = self.resolve_answers(questions, state.request.clarification_answers)

        state.clarification_resolved = resolved

        user_answers = [
            {"question_id": k, "selected_value": v}
            for k, v in resolved.items()
            if any(a.question_id == k for a in state.request.clarification_answers)
        ]

        append_trace(
            state.traces,
            agent_name="ClarificationAgent",
            step="generate_clarification",
            input_summary=state.request.user_input[:100],
            output_summary=(
                f"questions={len(questions)}, resolved={len(resolved)}, "
                f"llm={self.requested_provider}"
            ),
            metadata={
                "questions": [q.model_dump() for q in questions],
                "question_sources": self._last_sources,
                "defaults": {q.question_id: q.default_value for q in questions},
                "resolved_answers": resolved,
                "user_selected": user_answers,
                "clarification_needed": not state.request.skip_clarification,
                **self._last_llm_meta,
            },
            pipeline_step="clarification_needed",
        )
        return state
