"""LangGraph workflow orchestration for VisionFlow."""

from __future__ import annotations

import time
from typing import Callable, Literal

from langgraph.graph import END, StateGraph

from app.agents.academic_agent import AcademicFigureAgent
from app.agents.asset_manager_agent import AssetManagerAgent
from app.agents.clarification_agent import ClarificationAgent
from app.agents.critic_agent import CriticAgent
from app.agents.ecommerce_agent import EcommerceAgent
from app.agents.ppt_agent import PPTVisualAgent
from app.agents.prompt_agent import PromptAgent
from app.agents.requirement_agent import RequirementAgent
from app.agents.revision_agent import RevisionAgent
from app.agents.router_agent import TaskRouterAgent
from app.agents.visual_spec_agent import VisualSpecAgent
from app.config import get_settings
from app.graph.errors import WorkflowExecutionError, WorkflowProgrammingError
from app.models.schemas import ClarificationAnswer, GenerationResult, WorkflowState, utc_now_iso


class VisionFlowGraph:
    """Multi-agent LangGraph workflow for visual content generation."""

    def __init__(self):
        self.router = TaskRouterAgent()
        self.clarification = ClarificationAgent()
        self.requirement = RequirementAgent()
        self.visual_spec_agent = VisualSpecAgent()
        self.ecommerce = EcommerceAgent()
        self.academic = AcademicFigureAgent()
        self.ppt = PPTVisualAgent()
        self.prompt = PromptAgent()
        self.asset_manager = AssetManagerAgent()
        self.critic = CriticAgent()
        self.revision = RevisionAgent()
        self._graph = self._build_graph()

    @staticmethod
    def _timed_call(
        state: WorkflowState, fn: Callable[[WorkflowState], WorkflowState]
    ) -> WorkflowState:
        """Execute an agent step and record duration_ms on the latest trace entry."""
        start = time.perf_counter()
        state = fn(state)
        duration_ms = int((time.perf_counter() - start) * 1000)
        if state.traces:
            state.traces[-1] = state.traces[-1].model_copy(update={"duration_ms": duration_ms})
        # LangGraph LastValue channels only propagate fields whose reference
        # changes. Agents append to the existing ``traces`` list in place, so we
        # rebind mutable containers to fresh references to force propagation
        # between nodes (otherwise the final state would lose all traces).
        state.traces = list(state.traces)
        state.clarification_resolved = dict(state.clarification_resolved)
        state.requirement = dict(state.requirement)
        state.domain_enrichment = dict(state.domain_enrichment)
        return state

    def _route_task(self, state: WorkflowState) -> WorkflowState:
        return self._timed_call(state, self.router.route)

    def _clarify_requirements(self, state: WorkflowState) -> WorkflowState:
        return self._timed_call(state, self.clarification.apply_in_workflow)

    def _parse_requirement(self, state: WorkflowState) -> WorkflowState:
        return self._timed_call(state, self.requirement.parse)

    def _build_visual_spec(self, state: WorkflowState) -> WorkflowState:
        return self._timed_call(state, self.visual_spec_agent.build)

    def _enrich_domain_spec(self, state: WorkflowState) -> WorkflowState:
        def _enrich(s: WorkflowState) -> WorkflowState:
            if s.task_type == "ecommerce_banner":
                return self.ecommerce.enrich(s)
            if s.task_type == "academic_figure":
                return self.academic.enrich(s)
            return self.ppt.enrich(s)

        return self._timed_call(state, _enrich)

    def _build_prompt(self, state: WorkflowState) -> WorkflowState:
        return self._timed_call(state, self.prompt.build)

    def _generate_asset(self, state: WorkflowState) -> WorkflowState:
        return self._timed_call(state, self.asset_manager.generate_asset)

    def _evaluate_asset(self, state: WorkflowState) -> WorkflowState:
        return self._timed_call(state, self.critic.evaluate)

    def _revise_if_needed(self, state: WorkflowState) -> WorkflowState:
        return self._timed_call(state, self.revision.revise_if_needed)

    def _regen_and_eval(self, state: WorkflowState) -> WorkflowState:
        """Regenerate asset and re-evaluate using the revised prompt."""
        state = self._timed_call(state, self.asset_manager.generate_asset)
        state = self._timed_call(state, self.critic.evaluate)
        return state

    def _save_assets(self, state: WorkflowState) -> WorkflowState:
        return self._timed_call(state, self.asset_manager.save_assets)

    def _should_revise(self, state: WorkflowState) -> Literal["revise", "save"]:
        if self.revision.needs_revision(state):
            return "revise"
        return "save"

    def _build_graph(self):
        graph = StateGraph(WorkflowState)

        graph.add_node("route_task", self._route_task)
        graph.add_node("clarify_requirements", self._clarify_requirements)
        graph.add_node("parse_requirement", self._parse_requirement)
        graph.add_node("build_visual_spec", self._build_visual_spec)
        graph.add_node("enrich_domain_spec", self._enrich_domain_spec)
        graph.add_node("build_prompt", self._build_prompt)
        graph.add_node("generate_asset", self._generate_asset)
        graph.add_node("evaluate_asset", self._evaluate_asset)
        graph.add_node("revise_if_needed", self._revise_if_needed)
        graph.add_node("regen_eval", self._regen_and_eval)
        graph.add_node("save_assets", self._save_assets)

        graph.set_entry_point("route_task")
        graph.add_edge("route_task", "clarify_requirements")
        graph.add_edge("clarify_requirements", "parse_requirement")
        graph.add_edge("parse_requirement", "build_visual_spec")
        graph.add_edge("build_visual_spec", "enrich_domain_spec")
        graph.add_edge("enrich_domain_spec", "build_prompt")
        graph.add_edge("build_prompt", "generate_asset")
        graph.add_edge("generate_asset", "evaluate_asset")
        graph.add_conditional_edges(
            "evaluate_asset",
            self._should_revise,
            {"revise": "revise_if_needed", "save": "save_assets"},
        )
        graph.add_edge("revise_if_needed", "regen_eval")
        graph.add_edge("regen_eval", "save_assets")
        graph.add_edge("save_assets", END)

        return graph.compile()

    def run(self, state: WorkflowState) -> WorkflowState:
        """Execute the LangGraph workflow with traceable pipeline fallback."""
        settings = get_settings()
        try:
            result = self._graph.invoke(state)
            if isinstance(result, dict):
                return WorkflowState(**result)
            return result
        except (TypeError, AttributeError, NameError, ImportError, SyntaxError) as exc:
            if settings.workflow_debug:
                raise WorkflowProgrammingError(str(exc), fallback_mode=None) from exc
            state.error_message = f"{type(exc).__name__}: {exc}"
            state.workflow_error_type = type(exc).__name__
            state.workflow_fallback = "none_programming_error"
            raise WorkflowProgrammingError(str(exc)) from exc
        except Exception as exc:
            if settings.workflow_debug:
                raise WorkflowExecutionError(str(exc), fallback_mode="pipeline") from exc
            state.error_message = f"{type(exc).__name__}: {exc}"
            state.workflow_error_type = type(exc).__name__
            state.workflow_fallback = "pipeline"
            fallback_state = run_pipeline(state)
            fallback_state.workflow_fallback = "pipeline"
            fallback_state.workflow_error_type = type(exc).__name__
            fallback_state.error_message = state.error_message
            return fallback_state

    def to_result(self, state: WorkflowState) -> GenerationResult:
        """Convert final workflow state to GenerationResult."""
        if not state.visual_spec or not state.evaluation:
            raise ValueError("Workflow incomplete: missing visual_spec or evaluation")

        return GenerationResult(
            task_id=state.task_id,
            task_type=state.task_type,
            route_reason=state.route_reason,
            visual_spec=state.visual_spec,
            prompt=state.prompt,
            output_path=state.output_path,
            report_path=state.report_path,
            evaluation=state.evaluation,
            traces=state.traces,
            clarification_answers=[
                ClarificationAnswer(question_id=k, selected_value=v)
                for k, v in state.clarification_resolved.items()
            ],
            created_at=utc_now_iso(),
        )


def run_pipeline(state: WorkflowState) -> WorkflowState:
    """Plain-function pipeline fallback when LangGraph invoke fails."""
    g = VisionFlowGraph()

    state = g._route_task(state)
    state = g._clarify_requirements(state)
    state = g._parse_requirement(state)
    state = g._build_visual_spec(state)
    state = g._enrich_domain_spec(state)
    state = g._build_prompt(state)
    state = g._generate_asset(state)
    state = g._evaluate_asset(state)

    if g.revision.needs_revision(state):
        state = g._revise_if_needed(state)
        state = g._regen_and_eval(state)

    state = g._save_assets(state)
    return state


_graph_instance: VisionFlowGraph | None = None


def get_visionflow_graph() -> VisionFlowGraph:
    global _graph_instance
    if _graph_instance is None:
        _graph_instance = VisionFlowGraph()
    return _graph_instance
