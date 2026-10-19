import asyncio
import os
import re
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class ServiceError(Exception):
    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        *,
        retryable: bool = False,
        details: list[dict[str, Any]] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.retryable = retryable
        self.details = details or []


@dataclass
class TaskRecord:
    id: str
    status: str = "queued"
    current_stage: str = "initial_research"
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    started_at: datetime | None = None
    finished_at: datetime | None = None
    request: dict[str, Any] = field(default_factory=dict)
    progress: dict[str, Any] = field(
        default_factory=lambda: {
            "planned_sections": None,
            "completed_sections": 0,
            "plan_revision_count": 0,
        }
    )
    result: dict[str, Any] | None = None
    warnings: list[dict[str, Any]] = field(default_factory=list)
    error: dict[str, Any] | None = None
    output_dir: str | None = None
    review: dict[str, Any] | None = None
    review_future: asyncio.Future | None = None


class TaskManager:
    FORMAT_MAP = {
        "markdown": (".md", "text/markdown; charset=utf-8"),
        "pdf": (".pdf", "application/pdf"),
        "docx": (
            ".docx",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ),
    }

    VALID_STATUSES = {
        "queued",
        "running",
        "awaiting_plan_review",
        "completed",
        "completed_with_warnings",
        "failed",
    }

    def __init__(self) -> None:
        self._tasks: dict[str, TaskRecord] = {}
        self._lock = threading.RLock()
        self._timeout_seconds = float(
            os.environ.get("RESEARCH_TASK_TIMEOUT_SECONDS", "1800")
        )

    async def create_task(self, payload: dict[str, Any]) -> dict[str, Any]:
        task_id = str(uuid.uuid4())
        record = TaskRecord(id=task_id, request=payload)
        with self._lock:
            self._tasks[task_id] = record

        asyncio.create_task(self._run_task(record))
        return self._to_create_response(record)

    async def list_tasks(
        self,
        *,
        status: str | None,
        created_after: datetime | None,
        created_before: datetime | None,
        page: int,
        page_size: int,
    ) -> dict[str, Any]:
        if status is not None and status not in self.VALID_STATUSES:
            raise ServiceError(
                422,
                "VALIDATION_ERROR",
                "status is not a valid task status",
                details=[{"field": "status", "reason": "invalid enum value"}],
            )

        if created_after is not None and created_after.tzinfo is None:
            created_after = created_after.replace(tzinfo=timezone.utc)
        if created_before is not None and created_before.tzinfo is None:
            created_before = created_before.replace(tzinfo=timezone.utc)

        with self._lock:
            records = list(self._tasks.values())

        records.sort(key=lambda item: item.created_at, reverse=True)
        if status is not None:
            records = [item for item in records if item.status == status]
        if created_after is not None:
            records = [item for item in records if item.created_at >= created_after]
        if created_before is not None:
            records = [item for item in records if item.created_at <= created_before]

        total = len(records)
        start = (page - 1) * page_size
        stop = start + page_size
        total_pages = (total + page_size - 1) // page_size if total else 1

        return {
            "items": [self._to_list_item(item) for item in records[start:stop]],
            "pagination": {
                "page": page,
                "page_size": page_size,
                "total": total,
                "total_pages": total_pages,
            },
        }

    async def get_task(self, task_id: str) -> dict[str, Any]:
        return self._to_task_response(self._get_record(task_id))

    async def get_plan_review(self, task_id: str) -> dict[str, Any]:
        record = self._get_record(task_id)
        if not record.request.get("include_human_feedback"):
            raise ServiceError(
                409,
                "HUMAN_REVIEW_DISABLED",
                "Human plan review is disabled for this task.",
            )
        if record.review is None:
            raise ServiceError(
                409,
                "PLAN_REVIEW_NOT_READY",
                "The research plan has not been generated yet.",
            )
        return self._to_plan_review_response(record)

    async def decide_plan_review(
        self,
        task_id: str,
        *,
        decision: str,
        feedback: str | None,
    ) -> dict[str, Any]:
        record = self._get_record(task_id)
        if not record.request.get("include_human_feedback"):
            raise ServiceError(
                409,
                "HUMAN_REVIEW_DISABLED",
                "Human plan review is disabled for this task.",
            )
        if record.review is None or record.review.get("status") != "pending":
            raise ServiceError(
                409,
                "PLAN_REVIEW_NOT_PENDING",
                "There is no pending plan review for this task.",
            )
        if record.review_future is None:
            raise ServiceError(
                409,
                "PLAN_REVIEW_NOT_PENDING",
                "There is no pending plan review for this task.",
            )

        max_plan_revisions = record.request["max_plan_revisions"]
        current_count = record.progress["plan_revision_count"]
        if decision == "revise" and current_count >= max_plan_revisions:
            raise ServiceError(
                409,
                "PLAN_REVISION_LIMIT_EXCEEDED",
                "The configured plan revision limit has been exceeded.",
            )

        with self._lock:
            now = datetime.now(timezone.utc)
            review = record.review
            review["status"] = (
                "accepted" if decision == "accept" else "revision_requested"
            )
            review["decision"] = decision
            review["feedback"] = feedback
            review["decided_at"] = now
            if decision == "revise":
                record.progress["plan_revision_count"] = current_count + 1
                review["revision_count"] = current_count + 1
                record.status = "running"
                record.current_stage = "planning"
            else:
                review["revision_count"] = current_count
                record.status = "running"
                record.current_stage = "section_research"

            future = record.review_future
            future.set_result(review)

        return {
            "task_id": task_id,
            "review": dict(review),
            "task_status": record.status,
            "task_url": self._task_url(task_id),
        }

    async def get_result(self, task_id: str) -> dict[str, Any]:
        record = self._get_record(task_id)
        if record.status == "failed":
            raise ServiceError(
                409,
                "TASK_FAILED",
                "The task failed and no result is available.",
            )
        if record.status not in {"completed", "completed_with_warnings"}:
            raise ServiceError(
                409,
                "TASK_NOT_COMPLETED",
                "The task has not completed yet.",
            )
        return {
            "task_id": record.id,
            "status": record.status,
            "completed_at": record.finished_at,
            "result": record.result,
            "warnings": record.warnings,
        }

    async def get_artifacts(self, task_id: str) -> dict[str, Any]:
        record = self._get_record(task_id)
        self._require_artifacts_ready(record)
        items, missing = self._scan_artifacts(record)
        return {
            "task_id": record.id,
            "items": items,
            "missing_formats": missing,
        }

    async def get_artifact_path(self, task_id: str, format_: str) -> Path:
        record = self._get_record(task_id)
        self._require_artifacts_ready(record)
        if format_ not in self.FORMAT_MAP:
            raise ServiceError(
                404,
                "ARTIFACT_NOT_FOUND",
                f"Unknown artifact format: {format_}",
            )
        extension = self.FORMAT_MAP[format_][0]
        if not record.output_dir:
            raise ServiceError(
                404,
                "ARTIFACT_NOT_FOUND",
                f"No {format_} artifact is available.",
            )

        output_dir = Path(record.output_dir)
        matches = list(output_dir.glob(f"*{extension}"))
        if not matches:
            raise ServiceError(
                404,
                "ARTIFACT_NOT_FOUND",
                f"No {format_} artifact is available.",
            )
        return max(matches, key=lambda path: path.stat().st_mtime)

    async def _run_task(self, record: TaskRecord) -> None:
        with self._lock:
            record.status = "running"
            record.started_at = datetime.now(timezone.utc)

        try:
            record.output_dir = self._create_output_dir(record)
            execution = await asyncio.wait_for(
                self._execute(record),
                timeout=self._timeout_seconds,
            )
            warnings = execution["warnings"]
            with self._lock:
                record.result = execution["result"]
                record.warnings = warnings
                record.status = (
                    "completed_with_warnings" if warnings else "completed"
                )
                record.current_stage = "finished"
                record.finished_at = datetime.now(timezone.utc)
                record.error = None
        except asyncio.TimeoutError:
            self._fail_task(
                record,
                code="TASK_TIMEOUT",
                message="The research task timed out.",
                retryable=True,
            )
        except ServiceError as exc:
            self._fail_task(
                record,
                code=exc.code,
                message=exc.message,
                retryable=exc.retryable,
            )
        except Exception as exc:  # pragma: no cover - defensive boundary
            code, retryable = self._classify_exception(exc)
            self._fail_task(
                record,
                code=code,
                message=f"{type(exc).__name__}: {str(exc)[:500]}",
                retryable=retryable,
            )

    async def _execute(self, record: TaskRecord) -> dict[str, Any]:
        from multi_agents.agents import (
            EditorAgent,
            PublisherAgent,
            ResearchAgent,
            WriterAgent,
        )

        task = dict(record.request)
        research_agent = ResearchAgent(headers={})
        editor_agent = EditorAgent(headers={})
        writer_agent = WriterAgent(headers={})
        publisher_agent = PublisherAgent(record.output_dir or "", headers={})

        self._update_stage(record, "initial_research")
        initial_result = await research_agent.run_initial_research({"task": task})
        initial_research = initial_result.get("initial_research")
        if not isinstance(initial_research, str) or not initial_research:
            raise ServiceError(
                502,
                "INVALID_MODEL_RESPONSE",
                "Initial research did not return usable text.",
                retryable=True,
            )

        plan_state: dict[str, Any] = {
            "task": task,
            "initial_research": initial_research,
            "human_feedback": None,
        }

        self._update_stage(record, "planning")
        plan = await editor_agent.plan_research(plan_state)
        self._validate_plan(plan)

        human_feedback: str | None = None
        if task.get("include_human_feedback"):
            while True:
                review = await self._wait_for_review(record, plan)
                if review["decision"] == "accept":
                    human_feedback = None
                    break

                human_feedback = review["feedback"]
                self._update_stage(record, "planning")
                plan_state["human_feedback"] = human_feedback
                plan = await editor_agent.plan_research(plan_state)
                self._validate_plan(plan)

        sections = plan["sections"]
        self._update_stage(record, "section_research")
        parallel_result = await editor_agent.run_parallel_research(
            {
                "task": task,
                "sections": sections,
                "title": plan["title"],
            }
        )
        research_data = parallel_result.get("research_data", [])
        if not isinstance(research_data, list):
            research_data = []

        self._update_progress(
            record,
            planned_sections=len(sections),
            completed_sections=self._count_completed_sections(sections, research_data),
        )

        self._update_stage(record, "writing")
        writer_result = await writer_agent.run(
            {
                "task": task,
                "title": plan["title"],
                "research_data": research_data,
            }
        )
        if not isinstance(writer_result, dict):
            raise ServiceError(
                502,
                "INVALID_MODEL_RESPONSE",
                "The report writer did not return a valid layout.",
                retryable=True,
            )

        publisher_state = {
            "task": task,
            "title": plan["title"],
            "date": plan.get("date"),
            "headers": writer_result.get("headers", {}),
            "introduction": writer_result.get("introduction", ""),
            "table_of_contents": writer_result.get("table_of_contents", ""),
            "conclusion": writer_result.get("conclusion", ""),
            "research_data": research_data,
            "sources": writer_result.get("sources", []),
        }

        self._update_stage(record, "publishing")
        publisher_result = await publisher_agent.run(publisher_state)
        report_markdown = (
            publisher_result.get("report", "")
            if isinstance(publisher_result, dict)
            else ""
        )

        section_research, section_warnings = self._build_section_research(
            sections, research_data
        )
        _, missing_formats = self._scan_artifacts(record)
        format_warnings = [
            {
                "code": "ARTIFACT_CONVERSION_FAILED",
                "format": format_,
                "message": f"The {format_} artifact could not be generated.",
            }
            for format_ in missing_formats
        ]

        result = {
            "initial_research": initial_research,
            "plan": plan,
            "human_review": {
                "feedback": human_feedback,
                "revision_count": record.progress["plan_revision_count"],
            },
            "layout": {
                "headers": writer_result.get("headers", {}),
                "introduction": writer_result.get("introduction", ""),
                "table_of_contents": writer_result.get("table_of_contents", ""),
                "conclusion": writer_result.get("conclusion", ""),
            },
            "section_research": section_research,
            "sources": writer_result.get("sources", []),
            "report_markdown": report_markdown,
        }

        return {
            "result": result,
            "warnings": [*section_warnings, *format_warnings],
        }

    async def _wait_for_review(
        self,
        record: TaskRecord,
        plan: dict[str, Any],
    ) -> dict[str, Any]:
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        review = {
            "status": "pending",
            "decision": None,
            "revision_count": record.progress["plan_revision_count"],
            "max_plan_revisions": record.request["max_plan_revisions"],
            "plan": plan,
            "feedback": None,
            "created_at": datetime.now(timezone.utc),
            "decided_at": None,
        }
        with self._lock:
            record.review = review
            record.review_future = future
            record.status = "awaiting_plan_review"
            record.current_stage = "human_review"

        try:
            return await future
        finally:
            with self._lock:
                record.review_future = None

    def _create_output_dir(self, record: TaskRecord) -> str:
        safe_query = self._sanitize_filename(record.request["query"][:40])
        output_dir = PROJECT_ROOT / "outputs" / f"run_{record.id}_{safe_query}"
        output_dir.mkdir(parents=True, exist_ok=True)
        return str(output_dir)

    @staticmethod
    def _sanitize_filename(value: str) -> str:
        return re.sub(r'[<>:"/\\|?*]', "_", value)

    def _validate_plan(self, plan: Any) -> None:
        if not isinstance(plan, dict) or not isinstance(plan.get("sections"), list):
            raise ServiceError(
                502,
                "INVALID_MODEL_RESPONSE",
                "The research planner did not return a valid outline.",
                retryable=True,
            )

    def _build_section_research(
        self,
        sections: list[str],
        research_data: list[Any],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        items: list[dict[str, Any]] = []
        warnings: list[dict[str, Any]] = []
        for index, section in enumerate(sections):
            raw = research_data[index] if index < len(research_data) else None
            content = raw.get(section) if isinstance(raw, dict) else raw
            items.append({"section": section, "content": content})
            if content is None:
                warnings.append(
                    {
                        "code": "SECTION_RESEARCH_FAILED",
                        "section": section,
                        "message": (
                            "Section research failed, but the remaining report "
                            "was generated."
                        ),
                    }
                )
        return items, warnings

    def _count_completed_sections(
        self,
        sections: list[str],
        research_data: list[Any],
    ) -> int:
        total = 0
        for index, section in enumerate(sections):
            if index >= len(research_data):
                continue
            raw = research_data[index]
            content = raw.get(section) if isinstance(raw, dict) else raw
            if content is not None:
                total += 1
        return total

    def _scan_artifacts(
        self,
        record: TaskRecord,
    ) -> tuple[list[dict[str, Any]], list[str]]:
        if not record.output_dir:
            return [], []
        output_dir = Path(record.output_dir)
        items: list[dict[str, Any]] = []
        missing: list[str] = []
        publish_formats = record.request.get("publish_formats", {})

        for format_, (extension, media_type) in self.FORMAT_MAP.items():
            if not publish_formats.get(format_):
                continue
            matches = list(output_dir.glob(f"*{extension}"))
            if not matches:
                missing.append(format_)
                continue
            path = max(matches, key=lambda item: item.stat().st_mtime)
            stat = path.stat()
            items.append(
                {
                    "id": format_,
                    "format": format_,
                    "status": "available",
                    "file_name": path.name,
                    "media_type": media_type,
                    "size_bytes": stat.st_size,
                    "created_at": datetime.fromtimestamp(
                        stat.st_mtime,
                        tz=timezone.utc,
                    ),
                    "download_url": (
                        f"{self._task_url(record.id)}/artifacts/{format_}/content"
                    ),
                }
            )

        return items, missing

    def _require_artifacts_ready(self, record: TaskRecord) -> None:
        if record.status not in {"completed", "completed_with_warnings"}:
            raise ServiceError(
                409,
                "TASK_NOT_COMPLETED",
                "The task has not completed yet.",
            )

    def _fail_task(
        self,
        record: TaskRecord,
        *,
        code: str,
        message: str,
        retryable: bool,
    ) -> None:
        with self._lock:
            record.status = "failed"
            record.finished_at = datetime.now(timezone.utc)
            record.error = {
                "code": code,
                "message": message,
                "retryable": retryable,
                "occurred_at": record.finished_at,
            }
            if record.review_future and not record.review_future.done():
                record.review_future.cancel()

    def _classify_exception(self, exc: Exception) -> tuple[str, bool]:
        name = f"{type(exc).__module__}.{type(exc).__name__}".lower()
        message = str(exc).lower()
        if "api_key" in message or "api key" in message or "authentication" in message:
            return "MODEL_NOT_CONFIGURED", False
        if "openai" in name or "model" in message or "llm" in message:
            return "MODEL_CALL_FAILED", True
        if any(word in name for word in ("search", "retriever", "scraper", "tavily")):
            return "SEARCH_PROVIDER_FAILED", True
        return "INTERNAL_ERROR", False

    def _get_record(self, task_id: str) -> TaskRecord:
        with self._lock:
            record = self._tasks.get(task_id)
        if record is None:
            raise ServiceError(404, "TASK_NOT_FOUND", "Task not found.")
        return record

    def _update_stage(self, record: TaskRecord, stage: str) -> None:
        with self._lock:
            record.current_stage = stage
            if record.status in {"queued", "awaiting_plan_review"}:
                record.status = "running"

    def _update_progress(
        self,
        record: TaskRecord,
        *,
        planned_sections: int | None = None,
        completed_sections: int | None = None,
        plan_revision_count: int | None = None,
    ) -> None:
        with self._lock:
            if planned_sections is not None:
                record.progress["planned_sections"] = planned_sections
            if completed_sections is not None:
                record.progress["completed_sections"] = completed_sections
            if plan_revision_count is not None:
                record.progress["plan_revision_count"] = plan_revision_count

    def _task_url(self, task_id: str) -> str:
        return f"/api/v1/research-tasks/{task_id}"

    def _links(self, record: TaskRecord) -> dict[str, str | None]:
        base = self._task_url(record.id)
        return {
            "self": base,
            "result": f"{base}/result",
            "plan_review": (
                f"{base}/plan-review"
                if record.request.get("include_human_feedback")
                else None
            ),
            "artifacts": f"{base}/artifacts",
        }

    def _to_create_response(self, record: TaskRecord) -> dict[str, Any]:
        return {
            "id": record.id,
            "status": record.status,
            "current_stage": record.current_stage,
            "created_at": record.created_at,
            "links": self._links(record),
        }

    def _to_list_item(self, record: TaskRecord) -> dict[str, Any]:
        return {
            "id": record.id,
            "status": record.status,
            "current_stage": record.current_stage,
            "query": record.request.get("query", ""),
            "created_at": record.created_at,
            "finished_at": record.finished_at,
            "result_available": record.status
            in {"completed", "completed_with_warnings"},
            "warnings_count": len(record.warnings),
        }

    def _to_task_response(self, record: TaskRecord) -> dict[str, Any]:
        return {
            "id": record.id,
            "status": record.status,
            "current_stage": record.current_stage,
            "created_at": record.created_at,
            "started_at": record.started_at,
            "finished_at": record.finished_at,
            "request": record.request,
            "progress": record.progress,
            "result_available": record.status
            in {"completed", "completed_with_warnings"},
            "warnings_count": len(record.warnings),
            "error": record.error,
            "links": self._links(record),
        }

    def _to_plan_review_response(self, record: TaskRecord) -> dict[str, Any]:
        if record.review is None:
            raise ServiceError(
                409,
                "PLAN_REVIEW_NOT_READY",
                "The research plan has not been generated yet.",
            )
        return {
            "task_id": record.id,
            **record.review,
            "links": {
                "task": self._task_url(record.id),
                "submit": f"{self._task_url(record.id)}/plan-review",
            },
        }


task_manager = TaskManager()
