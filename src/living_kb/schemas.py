from datetime import datetime

from pydantic import BaseModel, Field


class IngestTextRequest(BaseModel):
    title: str
    content: str = Field(min_length=1)
    source_type: str = "manual"
    uri: str | None = None


class IngestUrlRequest(BaseModel):
    url: str


class RawDocumentResponse(BaseModel):
    raw_id: int
    source_id: int
    status: str
    title: str | None
    snapshot_path: str | None
    asset_path: str | None


class RawDocumentListItem(BaseModel):
    raw_id: int
    source_id: int
    title: str | None
    source_type: str
    status: str
    created_at: datetime | None
    snapshot_path: str | None


class RawDocumentDetailResponse(BaseModel):
    raw_id: int
    source_id: int
    title: str | None
    source_type: str
    status: str
    uri: str | None
    created_at: datetime | None
    collected_at: datetime | None
    checksum: str
    parser_version: str
    snapshot_path: str | None
    asset_path: str | None
    linked_page_slug: str | None
    linked_page_title: str | None
    linked_page_review_status: str | None
    content_preview: str


class CompileResponse(BaseModel):
    page_id: int
    slug: str
    title: str
    review_status: str
    version: int
    markdown_path: str


class QueryRequest(BaseModel):
    question: str = Field(min_length=3)
    top_k: int = Field(default=5, ge=1, le=10)


class Citation(BaseModel):
    slug: str
    title: str
    score: float


class QueryResponse(BaseModel):
    answer: str
    citations: list[Citation]
    suggested_actions: list[str]


class PageResponse(BaseModel):
    id: int
    slug: str
    title: str
    page_type: str
    summary: str
    review_status: str
    version: int
    tags: list[str]
    source_refs: list[dict]
    markdown: str
    updated_at: datetime | None


class PageListItem(BaseModel):
    id: int
    slug: str
    title: str
    page_type: str
    review_status: str
    updated_at: datetime | None


class PageRevisionResponse(BaseModel):
    id: int
    version: int
    markdown_path: str
    summary: str
    tags: list[str]
    created_at: datetime | None


class PageDiffResponse(BaseModel):
    slug: str
    from_version: int
    to_version: int
    diff: str


class CompileRunResponse(BaseModel):
    id: int
    raw_id: int | None
    page_id: int | None
    provider: str
    model_name: str
    status: str
    quality_score: float | None
    summary_length: int | None
    tag_count: int | None
    duration_ms: int | None
    error_text: str | None
    created_at: datetime | None


class ReviewEventResponse(BaseModel):
    id: int
    item_type: str
    action: str
    page_id: int | None
    finding_id: int | None
    notes: str | None
    created_at: datetime | None


class QueryEventResponse(BaseModel):
    id: int
    question: str
    answer_preview: str
    citations: list[dict]
    suggested_actions: list[str]
    confidence_score: float | None
    created_at: datetime | None


class PageLineageResponse(BaseModel):
    slug: str
    title: str
    current_version: int
    review_status: str
    revisions: list[PageRevisionResponse]
    compile_runs: list[CompileRunResponse]
    review_events: list[ReviewEventResponse]
    recent_queries: list[QueryEventResponse]


class HealthFindingResponse(BaseModel):
    id: int
    page_id: int | None
    finding_type: str
    severity: str
    status: str
    details: dict
    review_notes: str | None
    created_at: datetime | None


class DashboardResponse(BaseModel):
    total_sources: int
    total_raw_documents: int
    total_pages: int
    total_links: int
    open_findings: int
    queued_jobs: int
    running_jobs: int
    database_backend: str
    retrieval_mode: str
    embedding_provider: str
    llm_provider: str
    llm_active: bool


class JobResponse(BaseModel):
    id: int
    job_type: str
    status: str
    target_raw_id: int | None
    target_page_id: int | None
    payload: dict
    result: dict | None
    error_text: str | None
    scheduled_for: datetime | None
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime | None


class EnqueueJobRequest(BaseModel):
    run_at: datetime | None = None


class ReviewActionRequest(BaseModel):
    notes: str | None = None


class ReviewQueueItem(BaseModel):
    item_type: str
    id: int
    title: str
    status: str
    severity: str | None = None
    page_slug: str | None = None
    page_id: int | None = None
    created_at: datetime | None = None
    details: dict | None = None
