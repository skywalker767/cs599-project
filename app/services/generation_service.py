"""Generation service – orchestrates workflow and persistence."""

from __future__ import annotations

import time
import uuid

from sqlalchemy.orm import Session

from app.agents.clarification_agent import ClarificationAgent
from app.agents.router_agent import TaskRouterAgent
from app.config import get_settings
from app.graph.visionflow_graph import get_visionflow_graph
from app.models.database import (
    count_task_records,
    delete_task_record,
    list_task_records,
    load_task_record,
    save_task_record,
)
from app.models.schemas import (
    ClarificationRequest,
    ClarificationResponse,
    DocumentExtractResponse,
    DocumentSummary,
    GenerationRequest,
    GenerationResult,
    PaginatedTasks,
    StatsResponse,
    TaskSummary,
    WorkflowState,
)
from app.tools.document_extractor import (
    DocumentExtractionError,
    extract_document,
    summarize_document,
)

_SCORE_BUCKETS = (
    ("90-100", 90, 100),
    ("80-89", 80, 89),
    ("70-79", 70, 79),
    ("<70", 0, 69),
)


class GenerationService:
    """High-level service for visual content generation."""

    def __init__(self):
        self.graph = get_visionflow_graph()
        self.router = TaskRouterAgent()
        self.clarification = ClarificationAgent()

    def create_task_id(self) -> str:
        return str(uuid.uuid4())[:8]

    def run_clarify(self, request: ClarificationRequest) -> ClarificationResponse:
        """Route task type and generate clarification questions."""
        gen_req = GenerationRequest(
            user_input=request.user_input,
            task_type=request.task_type or "auto",
        )
        state = WorkflowState(request=gen_req, task_id="clarify")
        state = self.router.route(state)
        questions = self.clarification.generate_questions(request.user_input, state.task_type)
        return ClarificationResponse(
            task_type=state.task_type,
            route_reason=state.route_reason,
            questions=questions,
            sources=dict(self.clarification._last_sources),
        )

    def extract_document(self, filename: str, data: bytes) -> DocumentExtractResponse:
        """Extract text from an uploaded document and distill a structured overview."""
        extraction = extract_document(filename, data)
        if extraction.needs_ocr:
            return DocumentExtractResponse(
                filename=filename,
                summary=DocumentSummary(
                    title="扫描件 PDF",
                    needs_ocr=True,
                    extraction_warning=extraction.warning,
                    char_count=0,
                ),
                document_context="",
                suggested_task_type="academic_figure",
                suggested_aspect_ratio="16:9",
            )

        text = extraction.extracted_text
        if not text.strip():
            raise DocumentExtractionError("文档内容为空或无法解析。")

        summary_dict = summarize_document(text, self.clarification.llm)
        summary_dict["needs_ocr"] = False
        summary_dict["extraction_warning"] = extraction.warning
        summary = DocumentSummary(**summary_dict)

        context_parts = [f"【文档标题】{summary.title}"]
        if summary.problem:
            context_parts.append(f"【研究问题】{summary.problem}")
        if summary.method_steps:
            context_parts.append("【方法流程】" + " → ".join(summary.method_steps))
        if summary.contributions:
            context_parts.append("【主要贡献】" + "；".join(summary.contributions))
        if summary.keywords:
            context_parts.append("【关键词】" + "、".join(summary.keywords))
        document_context = "\n".join(context_parts)

        return DocumentExtractResponse(
            filename=filename,
            summary=summary,
            document_context=document_context,
            suggested_task_type="academic_figure",
            suggested_aspect_ratio="16:9",
        )

    def run_generation(self, db: Session, request: GenerationRequest) -> GenerationResult:
        """Run the full multi-agent workflow and persist the result."""
        task_id = self.create_task_id()
        state = WorkflowState(request=request, task_id=task_id)

        start = time.perf_counter()
        try:
            result_state = self.graph.run(state)
            result = self.graph.to_result(result_state)
        except Exception as exc:
            raise RuntimeError(f"Generation failed for task {task_id}: {exc}") from exc

        result.status = "completed"
        result.duration_ms = int((time.perf_counter() - start) * 1000)
        save_task_record(db, result.model_dump(mode="json"))
        return result

    def get_task(self, db: Session, task_id: str) -> GenerationResult | None:
        data = load_task_record(db, task_id)
        if not data:
            return None
        return GenerationResult.model_validate(data)

    def delete_task(self, db: Session, task_id: str) -> bool:
        return delete_task_record(db, task_id)

    def list_tasks(self, db: Session, limit: int = 50, offset: int = 0) -> PaginatedTasks:
        rows = list_task_records(db, limit=limit, offset=offset)
        total = count_task_records(db)
        summaries: list[TaskSummary] = []
        for row in rows:
            try:
                result = GenerationResult.model_validate(row)
                summaries.append(
                    TaskSummary(
                        task_id=result.task_id,
                        task_type=result.task_type,
                        title=result.visual_spec.title,
                        overall_score=result.evaluation.overall_score,
                        output_path=result.output_path,
                        status=result.status,
                        duration_ms=result.duration_ms,
                        created_at=result.created_at,
                    )
                )
            except Exception:
                continue
        return PaginatedTasks(
            items=summaries,
            total=total,
            limit=limit,
            offset=offset,
            has_next=(offset + len(summaries)) < total,
        )

    def count_tasks(self, db: Session) -> int:
        return count_task_records(db)

    def get_stats(self, db: Session) -> StatsResponse:
        """Aggregate statistics across all stored tasks."""
        settings = get_settings()
        rows = list_task_records(db, limit=10000, offset=0)

        scores: list[int] = []
        durations: list[int] = []
        risk_total = 0
        by_type: dict[str, int] = {}
        score_sum_by_type: dict[str, int] = {}
        buckets = {name: 0 for name, _, _ in _SCORE_BUCKETS}

        for row in rows:
            try:
                result = GenerationResult.model_validate(row)
            except Exception:
                continue
            score = result.evaluation.overall_score
            scores.append(score)
            durations.append(result.duration_ms or 0)
            risk_total += result.evaluation.risk_count
            by_type[result.task_type] = by_type.get(result.task_type, 0) + 1
            score_sum_by_type[result.task_type] = score_sum_by_type.get(result.task_type, 0) + score
            for name, low, high in _SCORE_BUCKETS:
                if low <= score <= high:
                    buckets[name] += 1
                    break

        total = len(scores)
        avg_score = round(sum(scores) / total, 1) if total else 0.0
        avg_duration = int(sum(durations) / total) if total else 0
        avg_by_type = {t: round(score_sum_by_type[t] / by_type[t], 1) for t in by_type}

        return StatsResponse(
            total_tasks=count_task_records(db),
            avg_overall_score=avg_score,
            avg_duration_ms=avg_duration,
            total_risk_count=risk_total,
            by_task_type=by_type,
            avg_score_by_type=avg_by_type,
            score_buckets=buckets,
            llm_provider=settings.llm_provider,
            image_provider=settings.image_provider,
        )


_service: GenerationService | None = None


def get_generation_service() -> GenerationService:
    global _service
    if _service is None:
        _service = GenerationService()
    return _service
