"""Layered quality evaluator: deterministic + heuristic + optional VLM."""

from __future__ import annotations

import json
import logging
import math
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

from app.config import get_settings
from app.models.schemas import AgentTrace, EvaluationReport, VisualSpec
from app.tools.aspect_ratio import resolve_aspect_ratio

logger = logging.getLogger(__name__)

RISK_WORDS = [
    "最好",
    "第一",
    "绝对",
    "100%",
    "best ever",
    "guaranteed",
    "永远",
    "国家级",
    "顶级",
    "唯一",
    "#1",
]

_DOMAIN_KEYWORDS = {
    "ecommerce_banner": ["product", "sale", "banner", "商品", "促销", "cta", "购买"],
    "academic_figure": ["flowchart", "diagram", "pipeline", "模块", "箭头", "流程"],
    "ppt_visual": ["presentation", "slide", "cover", "汇报", "标题", "infographic", "教学"],
}

_ASPECT_TOLERANCE = 0.12  # 12% relative size tolerance for spec compliance


@dataclass
class ImageStats:
    width: int = 0
    height: int = 0
    entropy: float = 0.0
    color_variance: float = 0.0
    edge_density: float = 0.0
    brightness: float = 0.0
    contrast: float = 0.0
    is_blank_like: bool = False
    is_corrupted: bool = False
    warnings: list[str] = field(default_factory=list)


@dataclass
class LayerScore:
    score: int
    rationale: str


class DeterministicEvaluator:
    """Offline format, spec, and structural checks."""

    def evaluate(
        self,
        visual_spec: VisualSpec,
        prompt: str,
        output_path: Path | None,
        trace_count: int,
        traces: list[AgentTrace] | None = None,
    ) -> dict[str, LayerScore]:
        scores: dict[str, LayerScore] = {}

        scores["format_validity"] = self._format_validity(output_path)
        scores["spec_compliance"] = self._spec_compliance(visual_spec, output_path)
        scores["semantic_alignment"] = self._semantic_alignment(visual_spec, prompt)
        scores["reproducibility_score"] = self._reproducibility(trace_count, traces)
        scores["task_specific_score"] = self._task_specific(visual_spec, prompt, output_path)

        return scores

    def _format_validity(self, output_path: Path | None) -> LayerScore:
        if not output_path or not output_path.exists():
            return LayerScore(15, "输出文件不存在，无法验证格式。")

        size = output_path.stat().st_size
        if size < 50:
            return LayerScore(25, f"文件过小（{size} bytes），可能不是有效图像。")

        suffix = output_path.suffix.lower()
        if suffix == ".svg":
            return self._validate_svg(output_path)
        if suffix == ".png":
            return self._validate_png(output_path)
        return LayerScore(45, f"未知扩展名 {suffix}，仅做存在性检查。")

    def _validate_png(self, path: Path) -> LayerScore:
        try:
            from PIL import Image

            with Image.open(path) as img:
                w, h = img.size
                if w < 8 or h < 8:
                    return LayerScore(35, f"PNG 尺寸异常偏小（{w}x{h}）。")
                if img.format and img.format.upper() != "PNG":
                    return LayerScore(50, f"扩展名为 .png 但实际格式为 {img.format}。")
                # Blank / solid detection via pixel spread
                gray = img.convert("L")
                pixels = list(gray.getdata())
                spread = max(pixels) - min(pixels) if pixels else 0
                if spread < 3:
                    return LayerScore(30, f"PNG 疑似纯色/空白图（亮度跨度 {spread}）。")
                return LayerScore(90, f"有效 PNG，尺寸 {w}x{h}，像素有信息量。")
        except Exception as exc:
            return LayerScore(40, f"无法解析 PNG：{exc}")

    def _validate_svg(self, path: Path) -> LayerScore:
        try:
            tree = ET.parse(path)
            root = tree.getroot()
            tag_names = {el.tag.split("}")[-1] for el in root.iter()}
            has_shapes = bool(tag_names & {"rect", "path", "line", "circle", "polygon", "text"})
            view_box = root.get("viewBox") or root.get("viewbox")
            text_nodes = [el.text for el in root.iter() if el.text and el.text.strip()]
            parts = ["SVG XML 可解析"]
            score = 70
            if view_box:
                score += 10
                parts.append("含 viewBox")
            if has_shapes:
                score += 10
                parts.append("含图形节点")
            if text_nodes:
                score += 5
                parts.append(f"含 {len(text_nodes)} 个文本节点")
            else:
                parts.append("未发现文本/shape 内容")
                score -= 5
            return LayerScore(min(100, score), "；".join(parts) + "。")
        except ET.ParseError as exc:
            return LayerScore(25, f"SVG XML 解析失败：{exc}")

    def _spec_compliance(self, spec: VisualSpec, output_path: Path | None) -> LayerScore:
        base = 55
        notes: list[str] = []
        required = [
            spec.title,
            spec.scenario,
            spec.purpose,
            spec.style,
            spec.main_subject,
            spec.aspect_ratio,
            spec.output_format,
        ]
        filled = sum(1 for v in required if v and str(v).strip())
        base += int((filled / len(required)) * 25)
        notes.append(f"Visual Spec 必填字段覆盖 {filled}/{len(required)}")

        if output_path and output_path.exists() and output_path.suffix.lower() == ".png":
            try:
                from PIL import Image

                with Image.open(output_path) as img:
                    w, h = img.size
                    expected = resolve_aspect_ratio(spec.aspect_ratio)
                    ew, eh = expected.width, expected.height
                    wr = abs(w - ew) / max(ew, 1)
                    hr = abs(h - eh) / max(eh, 1)
                    if wr <= _ASPECT_TOLERANCE and hr <= _ASPECT_TOLERANCE:
                        base += 15
                        notes.append(f"输出尺寸 {w}x{h} 符合规格 {ew}x{eh}")
                    else:
                        base -= 20
                        notes.append(
                            f"输出尺寸 {w}x{h} 与规格 {ew}x{eh} 偏差较大（wr={wr:.0%}, hr={hr:.0%}）"
                        )
            except Exception:
                notes.append("无法读取 PNG 尺寸进行规格比对")

        return LayerScore(max(0, min(100, base)), "；".join(notes) + "。")

    def _semantic_alignment(self, spec: VisualSpec, prompt: str) -> LayerScore:
        score = 45
        notes: list[str] = []
        pl = prompt.lower()
        if spec.main_subject and spec.main_subject.lower() in pl:
            score += 25
            notes.append("prompt 包含 main_subject")
        matched = sum(1 for el in spec.key_elements[:6] if el and el.lower() in pl)
        score += min(20, matched * 7)
        notes.append(f"key_elements 命中 {matched}/{min(len(spec.key_elements), 6)}")
        if spec.purpose and len(spec.purpose) > 5:
            score += 5
        return LayerScore(min(100, score), "；".join(notes) + "。")

    def _reproducibility(self, trace_count: int, traces: list[AgentTrace] | None) -> LayerScore:
        score = min(100, 25 + trace_count * 6)
        notes = [f"trace 步骤数 {trace_count}"]
        if traces:
            agents = {t.agent_name for t in traces}
            expected = {
                "TaskRouterAgent",
                "VisualSpecAgent",
                "AssetManagerAgent",
                "CriticAgent",
            }
            coverage = len(agents & expected) / len(expected)
            score = min(100, int(score * 0.5 + coverage * 50))
            notes.append(f"核心 Agent 覆盖 {len(agents & expected)}/{len(expected)}")
        return LayerScore(score, "；".join(notes) + "。")

    def _task_specific(
        self,
        spec: VisualSpec,
        prompt: str,
        output_path: Path | None,
    ) -> LayerScore:
        score = 55
        notes: list[str] = []
        pl = prompt.lower()
        keywords = _DOMAIN_KEYWORDS.get(spec.task_type, [])
        hits = sum(1 for k in keywords if k.lower() in pl)
        score += min(25, hits * 8)
        notes.append(f"领域关键词命中 {hits}/{len(keywords)}")

        if spec.task_type == "ecommerce_banner" and spec.product_poster:
            pp = spec.product_poster
            if pp.cta:
                score += 5
                notes.append("含 CTA 字段")
        elif spec.task_type == "academic_figure" and spec.academic:
            if spec.academic.caption and output_path and output_path.suffix.lower() == ".svg":
                try:
                    tree = ET.parse(output_path)
                    texts = " ".join(el.text or "" for el in tree.getroot().iter() if el.text)
                    if spec.academic.caption[:15] in texts:
                        score += 10
                        notes.append("SVG 含预期 caption")
                except ET.ParseError:
                    pass
        elif spec.task_type == "ppt_visual" and spec.educational and spec.educational.topic:
            score += 5
            notes.append("含教学主题字段")

        return LayerScore(min(100, score), "；".join(notes) + "。")


class HeuristicVisualEvaluator:
    """Offline PNG statistics – entropy, contrast, edges, blank detection."""

    def analyze_png(self, path: Path) -> ImageStats:
        stats = ImageStats()
        try:
            from PIL import Image, ImageFilter, ImageStat

            with Image.open(path) as img:
                stats.width, stats.height = img.size
                rgb = img.convert("RGB")
                gray = rgb.convert("L")

                hist = gray.histogram()
                total = sum(hist) or 1
                entropy = -sum((c / total) * math.log2(c / total) for c in hist if c > 0)
                stats.entropy = round(entropy, 3)

                st = ImageStat.Stat(rgb)
                stats.color_variance = round(
                    sum(st.var) / max(len(st.var), 1),
                    2,
                )
                stats.brightness = round(st.mean[0], 2)
                stats.contrast = round(st.stddev[0], 2)

                edges = gray.filter(ImageFilter.FIND_EDGES)
                edge_st = ImageStat.Stat(edges)
                stats.edge_density = round(edge_st.mean[0] / 255.0, 4)

                spread = max(gray.getdata()) - min(gray.getdata())
                stats.is_blank_like = (
                    spread < 5
                    or stats.color_variance < 10
                    or (stats.entropy < 1.0 and stats.contrast < 8)
                )
                stats.is_corrupted = stats.width < 4 or stats.height < 4
        except Exception as exc:
            stats.is_corrupted = True
            stats.warnings.append(f"图像统计失败：{exc}")
        return stats

    def evaluate_png(self, path: Path | None) -> dict[str, LayerScore]:
        if not path or not path.exists() or path.suffix.lower() != ".png":
            return {
                "layout_quality": LayerScore(60, "非 PNG 输出，跳过像素级启发式分析。"),
                "aesthetics": LayerScore(60, "非 PNG 输出，跳过美学启发式分析。"),
            }

        stats = self.analyze_png(path)
        if stats.is_corrupted:
            return {
                "layout_quality": LayerScore(20, "图像损坏或无法读取。"),
                "aesthetics": LayerScore(15, "图像损坏，无法评估美学。"),
            }

        layout = 50
        layout_notes = [
            f"尺寸 {stats.width}x{stats.height}",
            f"edge_density={stats.edge_density:.3f}",
        ]
        if stats.edge_density < 0.02:
            layout -= 25
            layout_notes.append("边缘密度极低，布局可能过于单调")
        elif stats.edge_density > 0.08:
            layout += 20
            layout_notes.append("边缘密度适中，有一定结构")
        else:
            layout += 10

        if stats.is_blank_like:
            layout -= 30
            layout_notes.append("疑似空白/纯色图")

        aesthetics = 50
        aest_notes = [
            f"entropy={stats.entropy}",
            f"variance={stats.color_variance}",
            f"contrast={stats.contrast}",
        ]
        if stats.is_blank_like:
            aesthetics = 15
            aest_notes.append("极低信息量，美学分大幅降低")
        else:
            if stats.entropy > 4.0:
                aesthetics += 20
                aest_notes.append("熵值健康，色彩分布丰富")
            elif stats.entropy < 2.0:
                aesthetics -= 15
                aest_notes.append("熵值偏低，画面可能单调")
            if stats.color_variance > 500:
                aesthetics += 15
            if 40 < stats.brightness < 210:
                aesthetics += 10
            if stats.contrast > 25:
                aesthetics += 10

        return {
            "layout_quality": LayerScore(
                max(0, min(100, layout)),
                "；".join(layout_notes) + "。",
            ),
            "aesthetics": LayerScore(
                max(0, min(100, aesthetics)),
                "；".join(aest_notes) + "。",
            ),
        }


class VLMEvaluator:
    """Optional vision-language model scoring when API key is configured."""

    VLM_SYSTEM = (
        "You are a visual quality critic. Score the described image on 0-100 for: "
        "semantic_alignment, aesthetics, layout_quality, text_legibility, task_specific_quality. "
        "Return ONLY JSON: "
        '{"semantic_alignment":N,"aesthetics":N,"layout_quality":N,'
        '"text_legibility":N,"task_specific_quality":N,"rationale":"..."}'
    )

    def is_available(self) -> bool:
        settings = get_settings()
        provider = (settings.vision_evaluator_provider or "none").lower().strip()
        if provider != "openai":
            return False
        key = (settings.openai_api_key or "").strip()
        return bool(key)

    def evaluate(
        self,
        visual_spec: VisualSpec,
        prompt: str,
        output_path: Path | None,
    ) -> tuple[dict[str, LayerScore], int | None]:
        if not self.is_available() or not output_path or not output_path.exists():
            return {}, None

        try:
            import base64

            import httpx

            settings = get_settings()
            if output_path.suffix.lower() == ".svg":
                return {}, None  # VLM path expects raster for now

            image_b64 = base64.b64encode(output_path.read_bytes()).decode("ascii")
            payload = {
                "model": settings.openai_model,
                "messages": [
                    {"role": "system", "content": self.VLM_SYSTEM},
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": (
                                    f"task_type={visual_spec.task_type}\n"
                                    f"spec={visual_spec.model_dump_json()[:1500]}\n"
                                    f"prompt={prompt[:800]}"
                                ),
                            },
                            {
                                "type": "image_url",
                                "image_url": {"url": f"data:image/png;base64,{image_b64}"},
                            },
                        ],
                    },
                ],
                "max_tokens": 400,
            }
            headers = {
                "Authorization": f"Bearer {settings.openai_api_key}",
                "Content-Type": "application/json",
            }
            url = f"{settings.openai_base_url.rstrip('/')}/chat/completions"
            with httpx.Client(timeout=60.0) as client:
                resp = client.post(url, headers=headers, json=payload)
                if resp.status_code >= 400:
                    logger.warning("VLM evaluator HTTP %s", resp.status_code)
                    return {}, None
                content = resp.json()["choices"][0]["message"]["content"]
            parsed = json.loads(content.strip().strip("`").replace("json\n", ""))
            rationale = str(parsed.get("rationale", "VLM 评估完成"))
            layers = {
                "semantic_alignment": LayerScore(
                    int(parsed.get("semantic_alignment", 70)),
                    f"[VLM] {rationale}",
                ),
                "layout_quality": LayerScore(
                    int(parsed.get("layout_quality", 70)),
                    "[VLM] layout_quality",
                ),
                "aesthetics": LayerScore(
                    int(parsed.get("aesthetics", 70)),
                    "[VLM] aesthetics",
                ),
            }
            vlm_overall = int(
                sum(
                    parsed.get(k, 70)
                    for k in (
                        "semantic_alignment",
                        "aesthetics",
                        "layout_quality",
                        "text_legibility",
                        "task_specific_quality",
                    )
                )
                / 5
            )
            return layers, vlm_overall
        except Exception as exc:
            logger.warning("VLM evaluator failed: %s", exc)
            return {}, None


class Evaluator:
    """Facade combining deterministic, heuristic, and optional VLM layers."""

    def __init__(self) -> None:
        self.deterministic = DeterministicEvaluator()
        self.heuristic = HeuristicVisualEvaluator()
        self.vlm = VLMEvaluator()

    def evaluate(
        self,
        visual_spec: VisualSpec,
        prompt: str,
        output_path: Path | None,
        trace_count: int,
        traces: list[AgentTrace] | None = None,
    ) -> EvaluationReport:
        det = self.deterministic.evaluate(
            visual_spec,
            prompt,
            output_path,
            trace_count,
            traces,
        )
        heur = self.heuristic.evaluate_png(output_path)

        layers: dict[str, LayerScore] = {**det, **heur}
        active_layers = ["deterministic", "heuristic"]

        vlm_overall: int | None = None
        if self.vlm.is_available():
            vlm_layers, vlm_overall = self.vlm.evaluate(visual_spec, prompt, output_path)
            if vlm_layers:
                active_layers.append("vlm")
                for key, val in vlm_layers.items():
                    if key in layers:
                        # Blend offline + VLM for semantic/layout/aesthetics
                        layers[key] = LayerScore(
                            int(layers[key].score * 0.4 + val.score * 0.6),
                            layers[key].rationale + " " + val.rationale,
                        )
                    else:
                        layers[key] = val

        # Risk penalty
        combined_text = prompt + " " + " ".join(visual_spec.text_requirements)
        risk_count = sum(1 for w in RISK_WORDS if w.lower() in combined_text.lower())
        warnings: list[str] = []
        suggestions: list[str] = []
        if risk_count:
            warnings.append(f"检测到 {risk_count} 个风险宣传词。")
            suggestions.append("移除绝对化宣传用语，降低合规风险。")

        breakdown = {k: {"score": v.score, "rationale": v.rationale} for k, v in layers.items()}

        core_keys = [
            "format_validity",
            "spec_compliance",
            "semantic_alignment",
            "layout_quality",
            "aesthetics",
            "task_specific_score",
            "reproducibility_score",
        ]
        offline_vals = [layers[k].score for k in core_keys if k in layers]
        offline_score = int(sum(offline_vals) / max(len(offline_vals), 1)) - risk_count * 3
        offline_score = max(0, min(100, offline_score))

        overall = offline_score
        if vlm_overall is not None:
            overall = int(offline_score * 0.55 + vlm_overall * 0.45)
            overall = max(0, min(100, overall - risk_count * 2))

        # Legacy five dimensions for API compatibility
        req_score = layers.get("semantic_alignment", LayerScore(50, "")).score
        domain_score = layers.get("task_specific_score", LayerScore(50, "")).score
        visual_score = layers.get("format_validity", LayerScore(50, "")).score
        prompt_score = min(100, 45 + len(prompt.split()) // 3)
        trace_score = layers.get("reproducibility_score", LayerScore(50, "")).score

        metric_scores = {k: v.score for k, v in layers.items()}
        metric_scores["offline_overall"] = offline_score
        metric_scores["overall_weighted"] = overall
        if vlm_overall is not None:
            metric_scores["vlm_overall"] = vlm_overall
        metric_scores["risk_penalty"] = max(0, 100 - risk_count * 15)

        comments = [f"{k}: {v.score}/100 — {v.rationale}" for k, v in layers.items()]

        if layers.get("format_validity", LayerScore(0, "")).score < 60:
            suggestions.append("重新生成视觉资产，确保文件存在且格式有效。")
        if layers.get("spec_compliance", LayerScore(0, "")).score < 70:
            suggestions.append("补充 Visual Spec 必填字段并确保输出尺寸符合比例。")
        if layers.get("semantic_alignment", LayerScore(0, "")).score < 70:
            suggestions.append("使 prompt 与 main_subject、key_elements 更一致。")

        return EvaluationReport(
            requirement_match_score=req_score,
            domain_compliance_score=domain_score,
            visual_quality_score=visual_score,
            prompt_completeness_score=prompt_score,
            traceability_score=trace_score,
            risk_count=risk_count,
            overall_score=overall,
            offline_score=offline_score,
            vlm_score=vlm_overall,
            evaluator_layers=active_layers,
            score_breakdown=breakdown,
            comments=comments,
            suggestions=suggestions,
            metric_scores=metric_scores,
            warnings=warnings,
        )
