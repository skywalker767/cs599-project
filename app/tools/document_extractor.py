"""Extract and summarize uploaded documents (PDF / text) for figure generation."""

from __future__ import annotations

import io
import re
from dataclasses import dataclass

from app.config import get_settings
from app.llm.parsing import parse_json_from_text

MAX_CHARS = 12000  # cap text fed to the LLM to control latency/cost

DOC_SUMMARY_SYSTEM = (
    "You are DocumentDigestAgent for VisionFlow. You read an academic paper or technical "
    "document and distill it into a structured overview that will drive a one-figure visual "
    "summary (graphical abstract). "
    "Return ONLY valid JSON with EXACTLY these keys:\n"
    "  title: string — the paper title (keep original language).\n"
    "  problem: string — the core problem/motivation in <=50 Chinese chars.\n"
    "  method_steps: list[string] — 4-7 ordered stage names describing the full pipeline "
    "    (e.g. 'Input Embedding', 'Multi-Head Attention', 'FFN', 'Output Projection').\n"
    "  contributions: list[string] — 3-5 specific innovation bullets "
    "    (include concrete numbers if present, e.g. 'BLEU +2.0 on WMT EN-DE').\n"
    "  keywords: list[string] — 4-7 technical keyword strings.\n"
    "  architecture_highlights: list[string] — 2-4 key architectural components or design choices "
    "    worth illustrating (e.g. 'Scaled Dot-Product Attention', 'Positional Encoding', "
    "    'Residual Connection + LayerNorm').\n"
    "  performance_metrics: list[string] — 0-3 key benchmark results to annotate on the figure "
    "    (e.g. 'WMT EN-DE: 28.4 BLEU', 'WMT EN-FR: 41.0 BLEU').\n"
    "  suggested_input: string — a RICH, DETAILED Chinese instruction (100-180 chars) to generate "
    "    a graphical-abstract figure. MUST mention: (1) paper title, (2) every pipeline stage in "
    "    order, (3) at least one key innovation point, (4) any notable performance metric, "
    "    (5) desired layout style (left-to-right flow, encoder-decoder split, etc.).\n"
    "Keep technical terms in their original English. Use Chinese for narrative descriptions. "
    "Agent hint: document_digest."
)


class DocumentExtractionError(RuntimeError):
    """Raised when a document cannot be parsed."""


@dataclass
class DocumentExtractionResult:
    """Structured PDF/text extraction outcome."""

    extracted_text: str
    needs_ocr: bool = False
    warning: str | None = None
    page_count: int = 0
    file_type: str = "unknown"


def extract_document(filename: str, data: bytes) -> DocumentExtractionResult:
    """Extract plain text from a PDF or text/markdown upload with OCR hints."""
    name = (filename or "").lower()
    if name.endswith(".pdf"):
        return _extract_pdf_structured(data)
    if name.endswith((".txt", ".md", ".markdown")):
        text = _normalize(data.decode("utf-8", errors="ignore"))
        if not text.strip():
            raise DocumentExtractionError("文本文件内容为空。")
        return DocumentExtractionResult(
            extracted_text=text,
            file_type="text",
            page_count=1,
        )
    # Unsupported explicit types
    known_bad = (".doc", ".docx", ".xlsx", ".pptx", ".zip")
    if any(name.endswith(ext) for ext in known_bad):
        raise DocumentExtractionError(f"不支持的文件类型：{filename}。请上传 PDF 或 TXT/Markdown。")
    # Fallback: try PDF first, then utf-8 text
    try:
        return _extract_pdf_structured(data)
    except DocumentExtractionError:
        text = _normalize(data.decode("utf-8", errors="ignore"))
        if not text.strip():
            raise DocumentExtractionError(
                f"无法解析文件 {filename}：不是有效的 PDF 或文本。"
            ) from None
        return DocumentExtractionResult(extracted_text=text, file_type="text")


def extract_text(filename: str, data: bytes) -> str:
    """Backward-compatible text extraction (raises on empty / scanned-only PDF)."""
    result = extract_document(filename, data)
    if result.needs_ocr:
        raise DocumentExtractionError(
            result.warning or "未能从 PDF 中提取到文字（可能是扫描件/图片型 PDF）。"
        )
    if not result.extracted_text.strip():
        raise DocumentExtractionError("文档内容为空或无法解析。")
    return result.extracted_text


def _extract_pdf_structured(data: bytes) -> DocumentExtractionResult:
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover
        raise DocumentExtractionError(
            "pypdf 未安装，无法解析 PDF。请运行 pip install pypdf"
        ) from exc

    try:
        reader = PdfReader(io.BytesIO(data))
    except Exception as exc:
        raise DocumentExtractionError(f"PDF 解析失败：{exc}") from exc

    page_count = len(reader.pages)
    if page_count == 0:
        raise DocumentExtractionError("PDF 为空（0 页），无法提取内容。")

    parts: list[str] = []
    for page in reader.pages:
        try:
            parts.append(page.extract_text() or "")
        except Exception:
            continue
    text = _normalize("\n".join(parts))

    if not text.strip():
        settings = get_settings()
        ocr = (settings.ocr_provider or "none").lower().strip()
        warning = (
            "未能从 PDF 中提取到可搜索文字，该文件可能是扫描件或图片型 PDF。"
            "当前 OCR_PROVIDER=none，未启用 OCR。"
        )
        if ocr != "none":
            warning += f" 已配置 OCR_PROVIDER={ocr}，但 OCR 集成尚未在此版本中启用。"
        return DocumentExtractionResult(
            extracted_text="",
            needs_ocr=True,
            warning=warning,
            page_count=page_count,
            file_type="pdf",
        )

    return DocumentExtractionResult(
        extracted_text=text,
        needs_ocr=False,
        page_count=page_count,
        file_type="pdf",
    )


def _normalize(text: str) -> str:
    text = text.replace("\x00", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def summarize_document(text: str, llm) -> dict:
    """Use the LLM to distill the document into a structured overview dict.

    Falls back to a heuristic summary when the LLM is unavailable or fails.
    """
    snippet = text[:MAX_CHARS]
    try:
        user_prompt = (
            "请阅读以下文档内容并生成结构化概述（用于生成一张论文概览图）。\n\n"
            f"=== 文档内容（截断至 {MAX_CHARS} 字）===\n{snippet}"
        )
        raw = llm.generate_text(DOC_SUMMARY_SYSTEM, user_prompt)
        parsed = parse_json_from_text(raw)
        if parsed and parsed.get("method_steps"):
            return _sanitize_summary(parsed, text)
    except Exception:
        pass
    return _heuristic_summary(text)


def _sanitize_summary(parsed: dict, text: str) -> dict:
    def _str_list(value, limit: int) -> list[str]:
        if not isinstance(value, list):
            return []
        out = [str(v).strip() for v in value if str(v).strip()]
        return out[:limit]

    title = str(parsed.get("title") or "").strip()[:120] or _guess_title(text)
    steps = _str_list(parsed.get("method_steps"), 7) or ["问题定义", "方法设计", "实验验证", "结论"]
    contributions = _str_list(parsed.get("contributions"), 5)
    keywords = _str_list(parsed.get("keywords"), 7)
    arch_highlights = _str_list(parsed.get("architecture_highlights"), 4)
    perf_metrics = _str_list(parsed.get("performance_metrics"), 3)
    problem = str(parsed.get("problem") or "").strip()[:200]
    suggested = str(parsed.get("suggested_input") or "").strip()
    if not suggested:
        suggested = _build_suggested_input(
            title, steps, contributions, arch_highlights, perf_metrics
        )

    return {
        "title": title,
        "problem": problem,
        "method_steps": steps,
        "contributions": contributions,
        "keywords": keywords,
        "architecture_highlights": arch_highlights,
        "performance_metrics": perf_metrics,
        "suggested_input": suggested,
        "char_count": len(text),
        "needs_ocr": False,
        "extraction_warning": None,
    }


def _heuristic_summary(text: str) -> dict:
    title = _guess_title(text)
    steps = ["数据/输入", "方法核心", "实验评估", "结果输出"]
    return {
        "title": title,
        "problem": "",
        "method_steps": steps,
        "contributions": [],
        "keywords": [],
        "architecture_highlights": [],
        "performance_metrics": [],
        "suggested_input": _build_suggested_input(title, steps, [], [], []),
        "char_count": len(text),
        "needs_ocr": False,
        "extraction_warning": None,
    }


def _guess_title(text: str) -> str:
    for line in text.splitlines():
        cleaned = line.strip()
        if 10 <= len(cleaned) <= 120:
            return cleaned[:120]
    return "上传文档"


def _build_suggested_input(
    title: str,
    steps: list[str],
    contributions: list[str],
    arch_highlights: list[str],
    perf_metrics: list[str],
) -> str:
    chain = " → ".join(steps) if steps else "方法流程"
    contrib_note = ""
    if contributions:
        contrib_note = f"核心创新点：{contributions[0]}。"
    arch_note = ""
    if arch_highlights:
        arch_note = f"重点标注架构要素：{'、'.join(arch_highlights[:3])}。"
    perf_note = ""
    if perf_metrics:
        perf_note = f"在图中标注性能指标：{'；'.join(perf_metrics[:2])}。"
    return (
        f"为论文《{title}》生成一张学术风格图形摘要（graphical abstract），"
        f"用左到右带箭头流程图展示方法流程：{chain}。"
        f"{contrib_note}"
        f"{arch_note}"
        f"{perf_note}"
        f"配色采用学术蓝灰，圆角矩形模块，清晰标注每个阶段名称，输出高清矢量图风格。"
    )
