import asyncio
import json
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Query
from fastapi.responses import FileResponse, StreamingResponse

from app.schemas import (
    ArtifactListResponse,
    CreateTaskResponse,
    PlanReviewDecisionRequest,
    PlanReviewDecisionResponse,
    PlanReviewResponse,
    ResearchResultResponse,
    ResearchTaskCreate,
    ResearchTaskResponse,
    TaskListResponse,
)
from app.services.task_service import task_manager


router = APIRouter(prefix="/api/v1/research-tasks", tags=["research-tasks"])


@router.post("", response_model=CreateTaskResponse, status_code=202)
async def create_research_task(payload: ResearchTaskCreate):
    return await task_manager.create_task(payload.model_dump())


@router.get("", response_model=TaskListResponse)
async def list_research_tasks(
    status: str | None = Query(default=None),
    created_after: datetime | None = Query(default=None),
    created_before: datetime | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
):
    return await task_manager.list_tasks(
        status=status,
        created_after=created_after,
        created_before=created_before,
        page=page,
        page_size=page_size,
    )


@router.get("/{task_id}", response_model=ResearchTaskResponse)
async def get_research_task(task_id: str):
    return await task_manager.get_task(task_id)


@router.get("/{task_id}/plan-review", response_model=PlanReviewResponse)
async def get_plan_review(task_id: str):
    return await task_manager.get_plan_review(task_id)


@router.post("/{task_id}/plan-review", response_model=PlanReviewDecisionResponse)
async def submit_plan_review(task_id: str, payload: PlanReviewDecisionRequest):
    return await task_manager.decide_plan_review(
        task_id,
        decision=payload.decision,
        feedback=payload.feedback,
    )


@router.get("/{task_id}/result", response_model=ResearchResultResponse)
async def get_research_result(task_id: str):
    return await task_manager.get_result(task_id)


@router.get("/{task_id}/artifacts", response_model=ArtifactListResponse)
async def list_artifacts(task_id: str):
    return await task_manager.get_artifacts(task_id)


@router.get("/{task_id}/artifacts/{format}/content", response_class=FileResponse)
async def download_artifact(task_id: str, format: str):
    path: Path = await task_manager.get_artifact_path(task_id, format)
    return FileResponse(path, filename=path.name)


@router.get("/{task_id}/events")
async def stream_task_events(task_id: str):
    async def event_generator():
        queue = await task_manager.subscribe(task_id)
        try:
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15)
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"
                    continue

                payload = {
                    "type": event["type"],
                    "data": event["data"],
                }
                yield (
                    "data: "
                    + json.dumps(payload, ensure_ascii=False, default=str)
                    + "\n\n"
                )
        finally:
            await task_manager.unsubscribe(task_id, queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
