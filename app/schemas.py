from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class PublishFormats(BaseModel):
    markdown: bool = False
    pdf: bool = False
    docx: bool = False

    @model_validator(mode="after")
    def at_least_one_enabled(self) -> "PublishFormats":
        if not any((self.markdown, self.pdf, self.docx)):
            raise ValueError("at least one publish format must be enabled")
        return self


class ResearchTaskCreate(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    model: str = Field(min_length=1, max_length=200)
    source: Literal["web"] = "web"
    language: str = Field(default="English", min_length=1, max_length=100)
    max_sections: int = Field(default=3, ge=1, le=20)
    max_plan_revisions: int = Field(default=3, ge=0, le=20)
    publish_formats: PublishFormats
    include_human_feedback: bool = False
    follow_guidelines: bool = False
    guidelines: list[str] = Field(default_factory=list)
    verbose: bool = False

    @field_validator("guidelines")
    @classmethod
    def guidelines_must_not_be_blank(cls, value: list[str]) -> list[str]:
        for item in value:
            if not item.strip():
                raise ValueError("guidelines must not contain empty strings")
        return value

    @model_validator(mode="after")
    def guidelines_required_when_enabled(self) -> "ResearchTaskCreate":
        if self.follow_guidelines and not self.guidelines:
            raise ValueError(
                "guidelines must contain at least one item when follow_guidelines is true"
            )
        return self


class CreateTaskResponse(BaseModel):
    id: str
    status: str
    current_stage: str
    created_at: datetime
    links: dict[str, str | None]


class TaskListItem(BaseModel):
    id: str
    status: str
    current_stage: str
    query: str
    created_at: datetime
    finished_at: datetime | None
    result_available: bool
    warnings_count: int


class TaskListResponse(BaseModel):
    items: list[TaskListItem]
    pagination: dict[str, int]


class TaskError(BaseModel):
    code: str
    message: str
    retryable: bool
    occurred_at: datetime


class TaskProgress(BaseModel):
    planned_sections: int | None
    completed_sections: int
    plan_revision_count: int


class ResearchTaskResponse(BaseModel):
    id: str
    status: str
    current_stage: str
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    request: ResearchTaskCreate
    progress: TaskProgress
    result_available: bool
    warnings_count: int
    error: TaskError | None
    links: dict[str, str | None]


class PlanModel(BaseModel):
    title: str
    date: str
    sections: list[str]


class PlanReviewResponse(BaseModel):
    task_id: str
    status: str
    decision: str | None
    revision_count: int
    max_plan_revisions: int
    plan: PlanModel
    feedback: str | None
    created_at: datetime
    decided_at: datetime | None
    links: dict[str, str]


class PlanReviewDecisionRequest(BaseModel):
    decision: Literal["accept", "revise"]
    feedback: str | None = None

    @model_validator(mode="after")
    def feedback_rules(self) -> "PlanReviewDecisionRequest":
        if self.decision == "revise" and (not self.feedback or not self.feedback.strip()):
            raise ValueError("feedback is required when decision is revise")
        if self.decision == "accept" and self.feedback:
            raise ValueError("feedback must be null when decision is accept")
        return self


class PlanReviewDecisionResponse(BaseModel):
    task_id: str
    review: dict[str, Any]
    task_status: str
    task_url: str


class HumanReviewResult(BaseModel):
    feedback: str | None
    revision_count: int


class LayoutHeaders(BaseModel):
    title: str | None = None
    date: str | None = None
    introduction: str | None = None
    table_of_contents: str | None = None
    conclusion: str | None = None
    references: str | None = None


class LayoutResult(BaseModel):
    headers: LayoutHeaders
    introduction: str
    table_of_contents: str
    conclusion: str


class SectionResearch(BaseModel):
    section: str
    content: str | None


class ResultWarning(BaseModel):
    code: str
    section: str | None = None
    format: str | None = None
    message: str


class ResearchResultPayload(BaseModel):
    initial_research: str
    plan: PlanModel
    human_review: HumanReviewResult
    layout: LayoutResult
    section_research: list[SectionResearch]
    sources: list[str]
    report_markdown: str


class ResearchResultResponse(BaseModel):
    task_id: str
    status: str
    completed_at: datetime
    result: ResearchResultPayload
    warnings: list[ResultWarning]


class ArtifactItem(BaseModel):
    id: str
    format: str
    status: Literal["available"]
    file_name: str
    media_type: str
    size_bytes: int
    created_at: datetime
    download_url: str


class ArtifactListResponse(BaseModel):
    task_id: str
    items: list[ArtifactItem]
    missing_formats: list[str]
