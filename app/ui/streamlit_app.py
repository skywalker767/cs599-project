"""VisionFlow Streamlit UI — modern single-flow studio."""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import pandas as pd
import streamlit as st

from app.ui.api_client import DEFAULT_BASE_URL, APIError, VisionFlowClient
from app.ui.components import (
    clarification_impact_hints,
    render_asset_hero,
    render_clarification_carousel,
    render_evaluation_compact,
    render_trace_timeline,
    score_color,
    task_type_label,
)
from app.ui.theme import inject_theme, render_hero, render_steps

EXAMPLES = {
    "ecommerce_coffee": {
        "label": "🛒 冰咖啡促销",
        "user_input": (
            "为一款夏季新品『0蔗糖低卡冰咖啡』制作一张小红书首页推广主图（banner）。"
            "商品是一罐铝罐装冰美式，核心卖点是『0蔗糖、低卡、冰爽不腻』。画面需要："
            "突出商品主图（约占画面 60%），加入限时促销标签『夏日限时·第二件半价』，"
            "标注醒目的折扣到手价『¥19.9』，并放置一个『立即抢购』CTA 按钮；"
            "背景使用薄荷绿渐变 + 冰块与水珠元素营造清爽感，整体走清新明亮的小红书风格。"
        ),
        "task_type": "auto",
        "style_preference": "小红书风格、清新明亮、薄荷绿主色调",
        "target_audience": "18-30 岁注重健康的年轻消费者",
        "aspect_ratio": "1:1",
    },
    "ecommerce_skincare": {
        "label": "🛒 护肤品双11",
        "user_input": (
            "为一款抗老精华液制作双11电商详情页头图。突出商品主图与质地特写，"
            "叠加促销信息『双11狂欢·前1小时直降50%』，标注到手价，"
            "加入『加入购物车』CTA 与『限量赠品』角标；整体走高级感金棕配色、轻奢质感。"
        ),
        "task_type": "auto",
        "style_preference": "轻奢高级感、金棕配色",
        "target_audience": "25-40 岁有抗老需求的女性消费者",
        "aspect_ratio": "4:5",
    },
    "academic_pipeline": {
        "label": "📊 方法流程图",
        "user_input": (
            "为一篇机器学习论文绘制方法流程图：数据预处理 → 特征提取 → "
            "双分支神经网络（CNN + Transformer 并行）→ 特征融合 → 分类输出。"
            "学术简洁风格，圆角矩形模块、带箭头连线，输出矢量图便于论文缩放。"
        ),
        "task_type": "auto",
        "style_preference": "学术简洁、期刊论文风、蓝灰配色",
        "target_audience": "机器学习研究人员",
        "aspect_ratio": "4:3",
    },
    "academic_abstract": {
        "label": "📊 图形摘要",
        "user_input": (
            "为多智能体协作生成视觉内容的论文绘制图形摘要（graphical abstract）。"
            "左侧用户输入 → 中间 Agent pipeline（路由、澄清、需求、规范、评估）"
            " → 右侧输出图像。学术 framework 风格，适合论文首页与会议海报。"
        ),
        "task_type": "auto",
        "style_preference": "学术简洁、framework 框架图",
        "target_audience": "AI/软件工程学术读者",
        "aspect_ratio": "16:9",
    },
    "ppt_cover": {
        "label": "📽️ 课程封面",
        "user_input": (
            "为《人工智能驱动的软件开发》课程结课汇报制作 PPT 封面配图。"
            "专业科技感：深色科技蓝渐变，抽象神经网络与代码纹理；"
            "左侧预留标题区，右下角预留校徽区域，适合大屏演示。"
        ),
        "task_type": "auto",
        "style_preference": "专业科技感、深色科技蓝",
        "target_audience": "课程师生与答辩评委",
        "aspect_ratio": "16:9",
    },
    "ppt_section": {
        "label": "📽️ 数据章节页",
        "user_input": (
            "为商业汇报 PPT 制作『业务增长』章节页配图。简洁商务风：浅色背景，"
            "右侧抽象上升折线与城市剪影，左侧留白放章节标题『2026 增长复盘』。"
        ),
        "task_type": "auto",
        "style_preference": "简洁商务、数据感",
        "target_audience": "企业管理层",
        "aspect_ratio": "16:9",
    },
}

TASK_TYPE_OPTIONS = ["auto", "ecommerce_banner", "academic_figure", "ppt_visual"]
TASK_TYPE_LABELS = {
    "auto": "自动路由",
    "ecommerce_banner": "电商营销图",
    "academic_figure": "论文图示",
    "ppt_visual": "PPT 配图",
}

API_URL = DEFAULT_BASE_URL


def _init_state() -> None:
    defaults = {
        "user_input": "",
        "prompt_text": "",
        "task_type": "auto",
        "style_preference": "",
        "target_audience": "",
        "aspect_ratio": "16:9",
        "enable_revision": False,
        "clarification_response": None,
        "clarification_selections": {},
        "clarify_carousel_idx": 0,
        "last_result": None,
        "view_task_id": None,
        "benchmark_report": None,
        "document_context": None,
        "document_summary": None,
        "uploaded_filename": None,
    }
    for k, v in defaults.items():
        st.session_state.setdefault(k, v)


def _load_example(key: str) -> None:
    ex = EXAMPLES[key]
    st.session_state.update(
        {
            "user_input": ex["user_input"],
            "prompt_text": ex["user_input"],
            "task_type": ex["task_type"],
            "style_preference": ex["style_preference"],
            "target_audience": ex["target_audience"],
            "aspect_ratio": ex["aspect_ratio"],
            "clarification_response": None,
            "clarification_selections": {},
            "clarify_carousel_idx": 0,
            "last_result": None,
            "document_context": None,
            "document_summary": None,
            "uploaded_filename": None,
        }
    )


def _current_step() -> int:
    if st.session_state.get("last_result"):
        return 2
    if st.session_state.get("clarification_response"):
        return 1
    return 0


def _fallback_prompt_from_summary(summary: dict) -> str:
    title = summary.get("title") or "上传文档"
    steps = summary.get("method_steps") or []
    chain = " → ".join(steps) if steps else "核心方法流程"
    return f"为论文《{title}》生成一张图形摘要，展示：{chain}。"


def _effective_user_input() -> str:
    """Resolve prompt text even when the Step-1 text_area is not rendered."""
    # Step 1 visible: sync widget → persistent store
    if st.session_state.get("user_input"):
        text = str(st.session_state["user_input"]).strip()
        if text:
            st.session_state["prompt_text"] = text
            return text

    text = str(st.session_state.get("prompt_text") or "").strip()
    if text:
        return text

    summary = st.session_state.get("document_summary") or {}
    suggested = str(summary.get("suggested_input") or "").strip()
    if suggested:
        st.session_state["prompt_text"] = suggested
        return suggested

    if st.session_state.get("document_context"):
        fallback = _fallback_prompt_from_summary(summary)
        st.session_state["prompt_text"] = fallback
        return fallback

    return ""


_init_state()

st.set_page_config(
    page_title="VisionFlow",
    page_icon="🎨",
    layout="wide",
    initial_sidebar_state="collapsed",
)

inject_theme()
client = VisionFlowClient(API_URL)

render_hero(
    "VisionFlow",
    "Clarification → Visual Spec → Multi-Agent · 电商 · 论文 · PPT 视觉生成",
)


# ── Cached helpers ─────────────────────────────────────────────
@st.cache_data(ttl=15, show_spinner=False)
def _cached_tasks(limit: int = 50) -> list[dict]:
    try:
        return VisionFlowClient(API_URL).list_tasks(limit=limit).get("tasks", [])
    except APIError:
        return []


@st.cache_data(ttl=15, show_spinner=False)
def _cached_stats() -> dict | None:
    try:
        return VisionFlowClient(API_URL).stats()
    except APIError:
        return None


def _refresh_caches() -> None:
    _cached_tasks.clear()
    _cached_stats.clear()


def _render_result(result: dict) -> None:
    """Image-first result layout with download at top."""
    eval_data = result.get("evaluation") or {}
    traces = result.get("traces", [])
    task_id = result.get("task_id", "")
    total_ms = result.get("duration_ms") or sum(t.get("duration_ms", 0) for t in traces)
    overall = eval_data.get("overall_score", 0)

    # ── Hero: image + score side by side ──
    img_col, info_col = st.columns([1.4, 1])
    with img_col:
        st.markdown("#### 🖼️ 生成结果")
        render_asset_hero(
            result.get("output_path", ""),
            client.asset_url(task_id),
            task_id=task_id,
        )
    with info_col:
        st.markdown("#### 📊 质量评估")
        render_evaluation_compact(eval_data)
        st.markdown("---")
        st.markdown(
            f"**{task_type_label(result.get('task_type', ''))}**  \n"
            f"综合 {score_color(overall)} **{overall}**/100 · 耗时 **{total_ms}** ms"
        )
        st.caption(result.get("route_reason", ""))

    # ── Details below ──
    detail_tabs = st.tabs(["Visual Spec", "Prompt", "澄清选择", "Agent 链路"])
    with detail_tabs[0]:
        if result.get("visual_spec"):
            st.json(result["visual_spec"])
    with detail_tabs[1]:
        prompt = result.get("prompt", "")
        if prompt:
            lang = "markdown" if "mermaid" in prompt.lower() else None
            st.code(prompt, language=lang)
    with detail_tabs[2]:
        clar = result.get("clarification_answers") or []
        if clar:
            st.dataframe(pd.DataFrame(clar), use_container_width=True, hide_index=True)
            for hint in clarification_impact_hints(clar):
                st.caption(f"→ {hint}")
        else:
            st.caption("无澄清记录")
    with detail_tabs[3]:
        render_trace_timeline(traces)


# ── Main tabs ──────────────────────────────────────────────────
studio_tab, history_tab, more_tab = st.tabs(["✨ 创作", "📂 历史", "⚙️ 更多"])

# ══════════════════════════════════════════════════════════════
with studio_tab:
    render_steps(_current_step(), ["描述需求", "澄清偏好", "查看结果"])

    result = st.session_state.get("last_result")
    clarify_data = st.session_state.get("clarification_response")

    # Show result prominently when available (not buried at bottom)
    if result and _current_step() == 2:
        _render_result(result)
        if st.button("🔄 开始新任务", use_container_width=True):
            st.session_state["last_result"] = None
            st.session_state["clarification_response"] = None
            st.session_state["clarification_selections"] = {}
            st.session_state["clarify_carousel_idx"] = 0
            st.session_state["document_context"] = None
            st.session_state["document_summary"] = None
            st.session_state["uploaded_filename"] = None
            st.session_state["prompt_text"] = ""
            st.rerun()
        st.divider()

    # ── Step 1: Input ──
    if not result and not clarify_data:
        with st.container():
            st.markdown('<div class="vf-card vf-card-accent">', unsafe_allow_html=True)

            # ── Document upload (PDF → paper overview figure) ──
            with st.expander("📄 上传文档（PDF / TXT）→ 自动生成论文概览图", expanded=False):
                uploaded = st.file_uploader(
                    "上传一篇论文，AI 将提炼方法流程并生成一张图形摘要",
                    type=["pdf", "txt", "md"],
                    key="doc_uploader",
                    label_visibility="collapsed",
                )
                if uploaded is not None and st.button(
                    "🔍 解析文档并填充需求", use_container_width=True, key="extract_btn"
                ):
                    with st.spinner("解析文档并提炼概要中…"):
                        try:
                            data = client.extract_document(
                                uploaded.name,
                                uploaded.getvalue(),
                                uploaded.type or "application/pdf",
                            )
                            summary = data.get("summary", {})
                            suggested = (summary.get("suggested_input") or "").strip()
                            if not suggested:
                                suggested = _fallback_prompt_from_summary(summary)
                            st.session_state["document_context"] = data.get("document_context")
                            st.session_state["document_summary"] = summary
                            st.session_state["uploaded_filename"] = data.get("filename")
                            st.session_state["prompt_text"] = suggested
                            st.session_state["user_input"] = suggested
                            st.session_state["task_type"] = data.get(
                                "suggested_task_type", "academic_figure"
                            )
                            st.session_state["aspect_ratio"] = data.get(
                                "suggested_aspect_ratio", "16:9"
                            )
                            # 论文概览生成：风格/受众从模型自动推断即可（留空也行）
                            st.session_state["style_preference"] = ""
                            st.session_state["target_audience"] = ""
                            # 论文概览场景下，示例默认隐藏
                            st.session_state["show_examples"] = False
                            st.rerun()
                        except APIError as e:
                            st.error(f"解析失败：{e.message}")

                doc_summary = st.session_state.get("document_summary")
                if doc_summary:
                    st.success(f"已解析：{st.session_state.get('uploaded_filename', '')}")
                    st.markdown(f"**标题**：{doc_summary.get('title', '—')}")
                    if doc_summary.get("problem"):
                        st.markdown(f"**问题**：{doc_summary['problem']}")
                    if doc_summary.get("method_steps"):
                        st.markdown("**方法流程**：" + " → ".join(doc_summary["method_steps"]))
                    if doc_summary.get("architecture_highlights"):
                        st.markdown(
                            "**架构要素**：" + "、".join(doc_summary["architecture_highlights"])
                        )
                    if doc_summary.get("contributions"):
                        st.markdown("**创新贡献**：" + "；".join(doc_summary["contributions"]))
                    if doc_summary.get("performance_metrics"):
                        st.markdown(
                            "**性能指标**：" + "；".join(doc_summary["performance_metrics"])
                        )
                    if doc_summary.get("keywords"):
                        st.caption("关键词：" + "、".join(doc_summary["keywords"]))
                    if st.button("清除文档", key="clear_doc"):
                        st.session_state["document_context"] = None
                        st.session_state["document_summary"] = None
                        st.session_state["uploaded_filename"] = None
                        st.session_state["show_examples"] = True
                        st.rerun()

            st.markdown('<p class="vf-chip-hint">快速示例 · 点击填充</p>', unsafe_allow_html=True)
            # PDF 上传后示例内容可能不再匹配，因此默认可隐藏
            show_examples_default = not bool(st.session_state.get("document_context"))
            show_examples = st.checkbox(
                "显示示例（可隐藏）",
                value=show_examples_default,
                key="show_examples",
            )
            if show_examples:
                chip_cols = st.columns(3)
                example_keys = list(EXAMPLES.keys())
                for i, key in enumerate(example_keys):
                    with chip_cols[i % 3]:
                        st.button(
                            EXAMPLES[key]["label"],
                            key=f"chip_{key}",
                            use_container_width=True,
                            on_click=_load_example,
                            args=(key,),
                        )

            if st.session_state.get("document_context"):
                st.info("📎 已附加文档上下文，生成时将参考论文内容")

            st.text_area(
                "Prompt（可编辑：用于生成论文概览/图像的需求描述）",
                height=120,
                key="user_input",
                placeholder="例如：为上传论文生成一张方法流程图式的图形摘要，突出数据预处理→模型双分支→特征融合→分类输出…",
                label_visibility="collapsed",
            )

            opt1, opt2, opt3, opt4 = st.columns(4)
            with opt1:
                st.selectbox(
                    "任务类型",
                    TASK_TYPE_OPTIONS,
                    format_func=lambda x: TASK_TYPE_LABELS[x],
                    key="task_type",
                    label_visibility="collapsed",
                )
            with opt2:
                with st.expander("风格（可选）", expanded=False):
                    st.text_input(
                        "风格", key="style_preference", placeholder="风格偏好（留空自动推断）"
                    )
            with opt3:
                with st.expander("受众（可选）", expanded=False):
                    st.text_input(
                        "受众", key="target_audience", placeholder="目标受众（留空自动推断）"
                    )
            with opt4:
                with st.expander("比例（可选）", expanded=False):
                    st.text_input("比例", key="aspect_ratio", placeholder="宽高比（留空默认）")

            st.checkbox("启用自动修订（更慢）", key="enable_revision")

            if st.button("下一步：生成澄清问题 →", type="primary", use_container_width=True):
                prompt = _effective_user_input()
                if not prompt:
                    st.warning("请先输入 Prompt，或上传 PDF 自动填充")
                else:
                    st.session_state["prompt_text"] = prompt
                    with st.spinner("分析需求并生成选择题…"):
                        try:
                            data = client.clarify(
                                prompt,
                                st.session_state["task_type"],
                                st.session_state.get("document_context"),
                            )
                            st.session_state["clarification_response"] = data
                            st.session_state["clarification_selections"] = {}
                            st.session_state["clarify_carousel_idx"] = 0
                            st.rerun()
                        except APIError as e:
                            st.error(e.message)

            st.markdown("</div>", unsafe_allow_html=True)

    # ── Step 2: Parallel clarification grid ──
    if clarify_data and not result:
        st.markdown("#### 🎯 偏好澄清")
        route = task_type_label(clarify_data.get("task_type", ""))
        st.caption(f"已路由至 {route} · {clarify_data.get('route_reason', '')}")

        prompt_preview = _effective_user_input()
        if prompt_preview:
            with st.expander("📝 当前 Prompt（已锁定，返回上一步可修改）", expanded=False):
                st.write(prompt_preview)

        selections = render_clarification_carousel(
            clarify_data.get("questions", []),
            "clarification_selections",
            clarify_data.get("sources", {}),
        )

        gen_col, back_col = st.columns([2, 1])
        with gen_col:
            if st.button("🚀 开始生成", type="primary", use_container_width=True):
                prompt = _effective_user_input()
                if not prompt:
                    st.error("Prompt 为空，请返回上一步填写或重新上传 PDF")
                else:
                    payload = {
                        "user_input": prompt,
                        "task_type": st.session_state["task_type"],
                        "style_preference": st.session_state["style_preference"] or None,
                        "target_audience": st.session_state["target_audience"] or None,
                        "aspect_ratio": st.session_state["aspect_ratio"] or None,
                        "enable_revision": st.session_state["enable_revision"],
                        "document_context": st.session_state.get("document_context"),
                        "clarification_answers": [
                            {
                                "question_id": qid,
                                "selected_values": vals,
                                "selected_value": ";".join(vals) if vals else "",
                            }
                            for qid, vals in selections.items()
                        ],
                        "skip_clarification": False,
                    }
                    with st.spinner("多智能体协作生成中，请耐心等待…"):
                        try:
                            gen_result = client.generate(payload)
                            st.session_state["last_result"] = gen_result
                            _refresh_caches()
                            st.rerun()
                        except APIError as e:
                            st.error(f"生成失败：{e.message}")
        with back_col:
            if st.button("← 返回修改", use_container_width=True):
                st.session_state["clarification_response"] = None
                st.session_state["clarification_selections"] = {}
                st.rerun()

# ══════════════════════════════════════════════════════════════
with history_tab:
    st.markdown("#### 历史任务")
    if st.button("刷新", key="hist_refresh"):
        _refresh_caches()
        st.rerun()

    tasks = _cached_tasks(30)
    if not tasks:
        st.info("暂无历史记录")
    else:
        for t in tasks[:12]:
            c1, c2, c3, c4 = st.columns([2, 2, 1, 1])
            c1.caption(f"`{t.get('task_id')}`")
            c2.write(task_type_label(t.get("task_type", "")))
            c3.write(f"{score_color(t.get('overall_score', 0))} {t.get('overall_score', 0)}")
            if c4.button("查看", key=f"view_{t.get('task_id')}"):
                st.session_state["view_task_id"] = t.get("task_id")
                st.rerun()

        view_id = st.session_state.get("view_task_id")
        if view_id:
            st.divider()
            try:
                _render_result(client.get_task(view_id))
            except APIError as e:
                st.error(e.message)

# ══════════════════════════════════════════════════════════════
with more_tab:
    st.markdown("#### 数据看板")
    stats = _cached_stats()
    if stats and stats.get("total_tasks", 0) > 0:
        m = st.columns(4)
        m[0].metric("任务数", stats.get("total_tasks", 0))
        m[1].metric("均分", stats.get("avg_overall_score", 0))
        m[2].metric("均耗时", f"{stats.get('avg_duration_ms', 0)} ms")
        m[3].metric("风险词", stats.get("total_risk_count", 0))
        by_type = stats.get("by_task_type", {})
        if by_type:
            st.bar_chart(
                pd.DataFrame(
                    {"数量": list(by_type.values())},
                    index=[task_type_label(k) for k in by_type],
                )
            )
    else:
        st.caption("生成任务后显示统计")

    st.divider()
    st.markdown("#### Benchmark")
    if st.button("运行 Benchmark（耗时较长）"):
        with st.spinner("运行中…"):
            try:
                from app.tools.benchmark import run_benchmark

                st.session_state["benchmark_report"] = run_benchmark(save=True)
                st.success("完成")
            except Exception as e:
                st.error(str(e))

    br = st.session_state.get("benchmark_report")
    if br:
        st.json({"通过率": f"{br.get('pass_rate', 0)*100:.0f}%", "案例": br.get("total_cases")})

    st.divider()
    st.markdown("""
**工作流**
用户输入 → 路由 → 澄清选择题 → Requirement → Visual Spec → Prompt → 生成 → 评估
        """)
