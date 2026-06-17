"""Asset generation and persistence agent."""

from __future__ import annotations

from app.config import get_settings
from app.models.schemas import WorkflowState
from app.tools.aspect_ratio import resolve_aspect_ratio
from app.tools.asset_store import save_json, save_text
from app.tools.diagram_generator import DiagramGenerator
from app.tools.image_factory import get_image_generator
from app.tools.trace_logger import TraceLogger, append_trace


class AssetManagerAgent:
    """Generate visual assets and persist all outputs."""

    def __init__(self):
        self.image_gen = get_image_generator()
        self.diagram_gen = DiagramGenerator()

    def generate_asset(self, state: WorkflowState) -> WorkflowState:
        """Call Image or Diagram tool based on task_type."""
        if not state.visual_spec:
            raise ValueError("VisualSpec required for asset generation")

        vs = state.visual_spec
        title = vs.title
        settings = get_settings()
        resolution = resolve_aspect_ratio(vs.aspect_ratio)

        generation_mode = "real"
        provider = getattr(self.image_gen, "provider_name", settings.image_provider)

        append_trace(
            state.traces,
            agent_name="AssetManagerAgent",
            step="select_provider",
            input_summary=settings.image_provider,
            output_summary=f"provider={provider}, mode={getattr(self.image_gen, 'mode', 'real')}",
            metadata={
                "provider": provider,
                "image_provider": settings.image_provider,
                "generation_mode": getattr(self.image_gen, "mode", "real"),
            },
            pipeline_step="provider_selected",
        )

        if state.task_type == "academic_figure":
            fmt = (vs.output_format or "").lower().strip()
            if fmt == "png":
                path = self.image_gen.generate(
                    state.task_id,
                    state.task_type,
                    title,
                    state.prompt,
                    aspect_ratio=vs.aspect_ratio,
                )
                generation_mode = getattr(self.image_gen, "mode", "real")
            else:
                path = self.diagram_gen.generate(state.task_id, vs)
                provider = "diagram_generator"
                generation_mode = "svg"
        else:
            path = self.image_gen.generate(
                state.task_id,
                state.task_type,
                title,
                state.prompt,
                aspect_ratio=vs.aspect_ratio,
            )
            generation_mode = getattr(self.image_gen, "mode", "real")

        state.output_path = str(path)
        append_trace(
            state.traces,
            agent_name="AssetManagerAgent",
            step="generate_asset",
            input_summary=state.task_type,
            output_summary=str(path.name),
            metadata={
                "output_path": str(path),
                "provider": provider,
                "image_provider": provider,
                "generation_mode": generation_mode,
                "task_type": state.task_type,
                "requested_aspect_ratio": resolution.requested_ratio,
                "resolved_width": resolution.width,
                "resolved_height": resolution.height,
                "aspect_ratio_requested": resolution.requested_ratio,
                "aspect_ratio_normalized": resolution.size,
                "width": resolution.width,
                "height": resolution.height,
                "orientation": resolution.orientation,
                "size_normalized": resolution.normalized,
                "normalization_reason": resolution.normalization_reason,
            },
            pipeline_step="output_generated",
            warnings=[resolution.normalization_reason] if resolution.normalization_reason else [],
        )
        return state

    def save_assets(self, state: WorkflowState) -> WorkflowState:
        """Save prompt, evaluation report, and trace to storage."""
        task_id = state.task_id

        prompt_path = save_text(task_id, "prompt", "prompt.txt", state.prompt)
        report_data = state.evaluation.model_dump() if state.evaluation else {}
        report_path = save_json(task_id, "report", "evaluation.json", report_data)

        logger = TraceLogger(state.traces)
        trace_path = logger.save(task_id)

        state.report_path = str(report_path)
        append_trace(
            state.traces,
            agent_name="AssetManagerAgent",
            step="save_assets",
            input_summary=task_id,
            output_summary=f"prompt={prompt_path.name}, report={report_path.name}",
            metadata={
                "prompt_path": str(prompt_path),
                "report_path": str(report_path),
                "trace_path": str(trace_path),
                "output_path": state.output_path,
                "evaluation_overall": (
                    state.evaluation.overall_score if state.evaluation else None
                ),
            },
        )
        return state
