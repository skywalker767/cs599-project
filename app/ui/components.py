"""Reusable Streamlit UI components for VisionFlow."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

from app.ui.clarification_compat import (
    build_incompat_map,
    is_blocked,
    sanitize_selection,
    storage_to_selection,
)

TASK_TYPE_LABELS = {
    "auto": "auto（自动路由）",
    "ecommerce_banner": "电商营销图",
    "academic_figure": "论文图示",
    "ppt_visual": "PPT 配图",
    "unknown": "未知",
}

TASK_TYPE_EMOJI = {
    "ecommerce_banner": "🛒",
    "academic_figure": "📊",
    "ppt_visual": "📽️",
    "auto": "🤖",
    "unknown": "❓",
}

SOURCE_META = {
    "core": ("核心", "core"),
    "optional": ("可选", "optional"),
    "llm": ("AI 生成", "llm"),
    "common": ("通用", "core"),
}


def task_type_label(task_type: str) -> str:
    emoji = TASK_TYPE_EMOJI.get(task_type, "")
    label = TASK_TYPE_LABELS.get(task_type, task_type)
    return f"{emoji} {label}".strip()


def score_color(score: float) -> str:
    if score >= 85:
        return "🟢"
    if score >= 70:
        return "🟡"
    return "🔴"


def _resolve_asset_bytes(output_path: str, asset_url: str | None) -> tuple[bytes | None, str, str]:
    """Return (bytes, filename, mime) for download; empty if unavailable."""
    if not output_path:
        return None, "", ""

    path = Path(output_path)
    if path.exists():
        data = path.read_bytes()
        suffix = path.suffix.lower()
        mime = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".svg": "image/svg+xml",
            ".webp": "image/webp",
        }.get(suffix, "application/octet-stream")
        return data, path.name, mime

    if asset_url:
        try:
            import urllib.request

            with urllib.request.urlopen(asset_url, timeout=15) as resp:
                data = resp.read()
            mime = resp.headers.get("Content-Type", "application/octet-stream")
            return data, path.name or "asset.png", mime
        except Exception:
            pass
    return None, path.name, ""


def render_asset_hero(
    output_path: str,
    asset_url: str | None = None,
    *,
    task_id: str = "",
) -> None:
    """Hero-style asset display with prominent download button."""
    if not output_path:
        st.info("暂无生成产物")
        return

    path = Path(output_path)
    file_bytes, filename, mime = _resolve_asset_bytes(output_path, asset_url)

    st.markdown('<div class="vf-result-frame">', unsafe_allow_html=True)

    if path.exists() and path.suffix.lower() == ".svg":
        svg = path.read_text(encoding="utf-8")
        st.markdown(
            f'<div style="background:#fff;border-radius:12px;padding:16px">{svg}</div>',
            unsafe_allow_html=True,
        )
    elif path.exists():
        st.image(str(path), use_container_width=True)
    elif asset_url:
        st.image(asset_url, use_container_width=True)
    else:
        st.warning(f"文件不存在：{path}")

    st.markdown("</div>", unsafe_allow_html=True)

    dl_col, meta_col = st.columns([1, 2])
    with dl_col:
        if file_bytes and filename:
            st.download_button(
                label="⬇️ 保存图片",
                data=file_bytes,
                file_name=filename,
                mime=mime,
                type="primary",
                use_container_width=True,
                key=f"dl_{task_id or filename}",
            )
        else:
            st.caption("暂无可下载文件")
    with meta_col:
        if task_id:
            st.caption(f"任务 ID：`{task_id}` · 文件：`{filename or path.name}`")


def _render_one_question(
    q: dict,
    q_index: int,
    selections: "dict[str, list[str]]",
) -> None:
    """Render a single clarification question inline (modifies selections in-place)."""
    qid = q["question_id"]
    options = q.get("options", [])
    labels = [o["label"] for o in options]
    values = [o["value"] for o in options]
    qtype = str(q.get("question_type", "single_choice")).strip() or "single_choice"

    with st.container(border=True):
        st.markdown(
            '<div style="background:#ffffff;padding:0.25rem 0.5rem;border-radius:8px;">'
            f'<p class="vf-q-title" style="color:#0f172a;font-weight:700;font-size:1.15rem;'
            f'margin:0 0 0.35rem 0;line-height:1.45;">{q["question_text"]}</p>'
            f'<p class="vf-q-reason" style="color:#334155;font-size:0.88rem;'
            f'margin:0 0 0.5rem 0;line-height:1.5;">{q.get("reason", "")}</p>'
            "</div>",
            unsafe_allow_html=True,
        )

        if not labels:
            return

        default_value = q.get("default_value") or (values[0] if values else "")
        current_selected = selections.get(qid, [])
        if not current_selected and default_value in values:
            current_selected = [default_value]

        if qtype == "multi_choice":
            incompat_map = build_incompat_map(q)
            current_selected = sanitize_selection(current_selected, incompat_map, exclusive=False)

            n_opts = len(options)
            cols_per_row = min(n_opts, 5)
            cols = st.columns(cols_per_row)
            new_selected: list[str] = []
            for i, opt in enumerate(options):
                val = opt["value"]
                lbl = opt["label"]
                checked = val in current_selected
                blocked = is_blocked(val, current_selected, incompat_map)
                display_label = f"⊘ 不可兼容 · {lbl}" if (blocked and not checked) else lbl
                with cols[i % cols_per_row]:
                    if st.checkbox(
                        display_label,
                        value=checked,
                        key=f"cq_{qid}_{q_index}_{val}",
                        disabled=(blocked and not checked),
                    ):
                        new_selected.append(val)

            cleaned = sanitize_selection(new_selected, incompat_map, exclusive=False)
            if q.get("required", True) and not cleaned and default_value in values:
                cleaned = [default_value]
            selections[qid] = cleaned

        else:
            selected_val = current_selected[0] if current_selected else default_value
            default_idx = values.index(selected_val) if selected_val in values else 0
            choice_label = st.radio(
                "请选择",
                options=labels,
                index=default_idx,
                key=f"cq_{qid}_{q_index}",
                horizontal=True,
                label_visibility="collapsed",
            )
            selections[qid] = [values[labels.index(choice_label)]]


def render_clarification_carousel(
    questions: list[dict],
    state_key: str,
    sources: dict[str, str] | None = None,
) -> dict[str, list[str]]:
    """Render all clarification questions at once in a 2-column grid layout.

    Questions are displayed side-by-side (2 per row) so users can answer them
    in parallel instead of clicking through one-at-a-time.
    """
    if not questions:
        return {}

    sources = sources or {}
    raw_selections = st.session_state.get(state_key, {}) or {}
    selections: dict[str, list[str]] = {
        str(qid): storage_to_selection(val) for qid, val in dict(raw_selections).items()
    }
    total = len(questions)

    # Progress bar
    answered = sum(
        1 for q in questions if selections.get(q["question_id"]) or q.get("default_value")
    )
    st.progress(answered / total, text=f"共 {total} 道偏好题 · 已填写 {answered}/{total}")

    # Render 2 questions per row for parallel browsing
    for row_start in range(0, total, 2):
        row_qs = questions[row_start : row_start + 2]
        if len(row_qs) == 1:
            # Odd question: full width
            _render_one_question(row_qs[0], row_start, selections)
        else:
            col_left, col_right = st.columns(2)
            with col_left:
                _render_one_question(row_qs[0], row_start, selections)
            with col_right:
                _render_one_question(row_qs[1], row_start + 1, selections)

    st.session_state[state_key] = selections
    return selections


def render_evaluation_compact(eval_data: dict) -> None:
    """Compact evaluation display with layered score breakdown."""
    if not eval_data:
        return

    overall = eval_data.get("overall_score", 0)
    offline = eval_data.get("offline_score", overall)
    vlm = eval_data.get("vlm_score")
    pct = min(overall, 100)
    st.markdown(
        f'<div style="text-align:center;margin:0.5rem 0">'
        f'<div class="vf-score-ring" style="--pct:{pct}%">{overall}</div>'
        f'<p style="margin:0.5rem 0 0;font-weight:600;color:#334155">综合评分 / 100</p>'
        f'<p style="margin:0.25rem 0;font-size:0.85rem;color:#64748b">'
        f"离线评估 {offline}" + (f" · VLM {vlm}" if vlm is not None else "") + "</p></div>",
        unsafe_allow_html=True,
    )
    st.progress(min(overall / 100.0, 1.0))

    layers = eval_data.get("evaluator_layers", [])
    if layers:
        st.caption("评估层：" + " → ".join(layers))

    breakdown = eval_data.get("score_breakdown") or {}
    if breakdown:
        with st.expander("📊 分项评分与理由", expanded=True):
            for name, item in breakdown.items():
                score = item.get("score", 0) if isinstance(item, dict) else 0
                rationale = item.get("rationale", "") if isinstance(item, dict) else str(item)
                st.markdown(f"**{name}** · {score}/100")
                st.caption(rationale)

    metrics = [
        ("需求", "requirement_match_score"),
        ("合规", "domain_compliance_score"),
        ("视觉", "visual_quality_score"),
        ("Prompt", "prompt_completeness_score"),
        ("追溯", "traceability_score"),
    ]
    pills = " ".join(
        f'<span class="vf-metric-pill">{label} {eval_data.get(key, 0)}</span>'
        for label, key in metrics
    )
    st.markdown(pills, unsafe_allow_html=True)

    warnings = eval_data.get("warnings", [])
    if warnings:
        with st.expander(f"⚠️ 警告（{len(warnings)}）"):
            for w in warnings:
                st.warning(w)

    suggestions = eval_data.get("suggestions", [])
    if suggestions:
        with st.expander(f"💡 改进建议（{len(suggestions)}）"):
            for s in suggestions:
                st.write(f"· {s}")


def render_evaluation(eval_data: dict) -> None:
    render_evaluation_compact(eval_data)


def render_asset(output_path: str, asset_url: str | None = None) -> None:
    render_asset_hero(output_path, asset_url)


def render_trace_timeline(traces: list[dict]) -> None:
    if not traces:
        st.info("暂无 Trace 记录")
        return

    total_ms = sum(t.get("duration_ms", 0) for t in traces)
    c1, c2, c3 = st.columns(3)
    c1.metric("步骤", len(traces))
    c2.metric("总耗时", f"{total_ms} ms")
    c3.metric("均耗时", f"{total_ms // max(len(traces), 1)} ms")

    pipeline = [
        t.get("metadata", {}).get("pipeline_step")
        for t in traces
        if t.get("metadata", {}).get("pipeline_step")
    ]
    if pipeline:
        st.caption("Pipeline: " + " → ".join(pipeline))

    df = pd.DataFrame(
        {"Agent": t.get("agent_name", ""), "ms": t.get("duration_ms", 0)} for t in traces
    )
    if not df.empty and df["ms"].sum() > 0:
        st.bar_chart(df.set_index("Agent"))

    rows = []
    for i, t in enumerate(traces, 1):
        row = {
            "#": i,
            "Step": t.get("metadata", {}).get("pipeline_step") or t.get("step", ""),
            "Agent": t.get("agent_name", ""),
            "ms": t.get("duration_ms", 0),
            "输出": (t.get("output_summary") or "")[:40],
        }
        rows.append(row)
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    for t in traces:
        warns = t.get("warnings") or []
        if warns:
            st.warning(f"{t.get('agent_name')}: " + "; ".join(warns))


def clarification_impact_hints(answers: list[dict]) -> list[str]:
    answer_map = {a["question_id"]: a["selected_value"] for a in answers}
    hints: list[str] = []
    mapping = [
        ("style", "风格 → Visual Spec.style"),
        ("aspect_ratio", "比例 → Visual Spec.aspect_ratio"),
        ("platform", "平台 → Visual Spec.scenario"),
        ("figure_type", "图类型 → key_elements"),
        ("slide_position", "幻灯片位置 → purpose"),
    ]
    for key, text in mapping:
        if answer_map.get(key):
            hints.append(f"`{answer_map[key]}` {text}")
    if answer_map.get("compliance_level") == "conservative":
        hints.append("保守合规 → 强化 avoid / constraints")
    if answer_map.get("output_format") == "svg":
        hints.append("SVG 输出 → 矢量图 + 清晰箭头标签")
    if answer_map.get("layout_blank") == "left":
        hints.append("左侧留白 → 标题区预留")
    return hints
