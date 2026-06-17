"""Prompt engineering agent with optional LLM enhancement."""

from __future__ import annotations

from app.llm.llm_factory import get_llm
from app.llm.parsing import llm_trace_meta, parse_json_from_text
from app.models.schemas import WorkflowState
from app.tools.diagram_generator import DiagramGenerator
from app.tools.trace_logger import append_trace

PROMPT_SYSTEM = (
    "You are PromptAgent for VisionFlow, a world-class prompt engineer for text-to-image AI models. "
    "Given a structured visual specification (and optionally DOCUMENT CONTEXT), write ONE high-quality "
    "English image-generation prompt. Return ONLY valid JSON with a single key 'prompt'.\n\n"
    "The prompt MUST be a single coherent, richly-detailed paragraph and MUST cover ALL of the following:\n"
    "1) SUBJECT: the main subject described with specific visual details (shapes, labels, colors, text overlays);\n"
    "2) LAYOUT & ELEMENTS: how key components are spatially arranged — use directional language "
    "   (left/center/right, top-to-bottom, connected by arrows, overlapping, etc.);\n"
    "3) STYLE & COLOR: art style (academic diagram / marketing banner / PPT illustration), exact color palette, "
    "   lighting mood (cool blue, warm orange, neutral white background, etc.);\n"
    "4) TYPOGRAPHY & TEXT: any on-image labels or callouts rendered exactly inside double quotes;\n"
    "5) COMPOSITION: aspect ratio guidance, focal point, depth cues;\n"
    "6) QUALITY: resolution boosters (crisp vector lines, professional print quality, sharp focus, no JPEG artifacts);\n"
    "7) AVOID: a trailing 'Avoid: ...' clause listing visual elements to exclude.\n\n"
    "Target length: 180–250 words. Be specific and concrete — the more detail, the better the result.\n"
    "If DOCUMENT CONTEXT is provided, ground every visual decision in that paper's actual pipeline, "
    "architecture names, innovation claims, and performance numbers (e.g. BLEU scores). "
    "Agent hint: prompt."
)


class PromptAgent:
    """Generate image prompt or diagram spec from visual spec."""

    def __init__(self, llm=None, requested_provider: str | None = None):
        if llm is None:
            self.llm, self.requested_provider = get_llm()
        else:
            self.llm = llm
            self.requested_provider = requested_provider or llm.provider_name
        self.diagram_gen = DiagramGenerator()

    def build(self, state: WorkflowState) -> WorkflowState:
        """Build prompt or Mermaid diagram spec."""
        if not state.visual_spec:
            raise ValueError("VisualSpec required before prompt generation")

        vs = state.visual_spec
        domain = state.domain_enrichment
        document_context = str(state.requirement.get("document_context", "") or "")
        llm_meta = llm_trace_meta(self.requested_provider, self.llm.provider_name, False, False)

        if state.task_type == "academic_figure":
            fmt = (vs.output_format or "").lower().strip()
            if fmt == "png":
                # PNG pipeline must be an image-generation prompt (no Mermaid code).
                prompt = self._build_image_prompt(vs, domain)
            else:
                mermaid = self.diagram_gen.generate_mermaid_spec(vs)
                prompt = self._build_diagram_spec(vs, mermaid, domain)
        else:
            prompt = self._build_image_prompt(vs, domain)

        llm_prompt, llm_meta = self._try_llm(vs, domain, state.task_type, document_context)
        if llm_prompt:
            # If we are generating PNG, always use the LLM-produced image prompt.
            if (
                state.task_type == "academic_figure"
                and (vs.output_format or "").lower().strip() == "png"
            ):
                prompt = llm_prompt
            else:
                if state.task_type == "academic_figure" and "mermaid" not in llm_prompt.lower():
                    prompt = self._build_diagram_spec(vs, mermaid, domain)
                    prompt += f"\n\n## LLM Enhancement\n{llm_prompt}"
                else:
                    prompt = llm_prompt

        state.prompt = prompt
        append_trace(
            state.traces,
            agent_name="PromptAgent",
            step="build_prompt",
            input_summary=vs.title,
            output_summary=prompt[:100] + "...",
            metadata={"prompt_length": len(prompt), "task_type": state.task_type, **llm_meta},
            pipeline_step="prompt_created",
        )
        return state

    def _try_llm(
        self, vs, domain: dict, task_type: str, document_context: str = ""
    ) -> tuple[str | None, dict]:
        actual = self.llm.provider_name
        fallback = False
        try:
            doc_block = ""
            if document_context:
                doc_block = f"\nDOCUMENT CONTEXT:\n{document_context[:1500]}"
            user_prompt = (
                f"task_type: {task_type}\nvisual_spec: {vs.model_dump()}\n"
                f"domain: {domain}{doc_block}"
            )
            raw = self.llm.generate_text(PROMPT_SYSTEM, user_prompt)
            parsed = parse_json_from_text(raw)
            if parsed and parsed.get("prompt"):
                return str(parsed["prompt"]), llm_trace_meta(
                    self.requested_provider,
                    actual,
                    fallback,
                    True,
                )
            if raw and not parsed and len(raw) > 30:
                return raw.strip(), llm_trace_meta(self.requested_provider, actual, fallback, True)
            return None, llm_trace_meta(self.requested_provider, actual, True, False)
        except Exception:
            return None, llm_trace_meta(self.requested_provider, actual, True, False)

    def _build_image_prompt(self, vs, domain: dict) -> str:
        """Build a vivid, paragraph-style prompt (fallback when LLM is unavailable)."""
        avoid = ", ".join(vs.avoid) if vs.avoid else "blur, watermark, clutter, distorted text"
        elements = ", ".join(vs.key_elements[:6])
        constraints = "; ".join(vs.constraints[:4])
        text_reqs = "; ".join(vs.text_requirements[:3]) if vs.text_requirements else ""
        eval_dims = ", ".join(vs.evaluation_dimensions[:3]) if vs.evaluation_dimensions else ""

        domain_extra = "professional composition, balanced layout, clean white background"
        if vs.task_type == "ecommerce_banner":
            cta = (domain.get("cta_suggestions") or ["立即抢购"])[0]
            discount = domain.get("discount_display", "")
            domain_extra = (
                f"e-commerce promotional banner, hero product photography in the center-right, "
                f'eye-catching gradient background, prominent call-to-action button labeled "{cta}"'
                + (f', price tag showing "{discount}"' if discount else "")
                + ", bold promotional typography, marketing layout optimized for mobile feeds"
            )
        elif vs.task_type == "ppt_visual":
            domain_extra = (
                "presentation slide background artwork, clean corporate design, generous white negative "
                "space on the left third for title text overlay, modern flat-3D geometric illustration style, "
                "subtle depth with layered shapes, suitable for widescreen display"
            )

        text_clause = f" Text overlays: {text_reqs}." if text_reqs else ""
        eval_clause = f" Key visual quality dimensions: {eval_dims}." if eval_dims else ""

        contrast_clause = ""
        if vs.task_type == "academic_figure":
            # Academic flow diagrams need predictable legibility.
            contrast_clause = (
                " High-contrast typography: dark/black text on a light background (avoid gray-on-dark), "
                "bold sans-serif labels, clear separation between boxes and text, and no low-contrast strokes."
            )

        sentence = (
            f"{vs.main_subject}, set in {vs.scenario}. "
            f"The composition features the following elements arranged from left to right: {elements}. "
            f"Visual style: {vs.style}; {domain_extra}. "
            f"Aspect ratio {vs.aspect_ratio}."
            f"{text_clause}"
            f" Design intent: {vs.purpose}."
            f" Layout and design constraints: {constraints}."
            f"{eval_clause}"
            f" Render at high resolution with crisp edges, sharp focus, professional print quality, "
            f"no JPEG artifacts, no noise."
            f"{contrast_clause}"
            f" Avoid: {avoid}."
        )
        return " ".join(sentence.split())

    def _build_diagram_spec(self, vs, mermaid: str, domain: dict) -> str:
        caption = domain.get("caption_suggestion", f"Figure: {vs.title}")
        lines = [
            f"# Diagram Spec: {vs.title}",
            f"Subject: {vs.main_subject}",
            f"Scene: {vs.scenario}",
            f"Style: {vs.style}",
            "Composition: top-to-bottom flowchart with labeled modules",
            f"Aspect ratio: {vs.aspect_ratio}",
            f"Constraints: {'; '.join(vs.constraints[:3])}",
            f"Avoid: {', '.join(vs.avoid)}",
            f"Caption: {caption}",
            "",
            "## Mermaid Flowchart",
            "```mermaid",
            mermaid,
            "```",
        ]
        return "\n".join(lines)
