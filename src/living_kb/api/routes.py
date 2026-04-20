from __future__ import annotations

import difflib
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from living_kb.config import Settings, get_settings
from living_kb.db import get_session
from living_kb.models import (
    CompileRun,
    HealthFinding,
    JobRun,
    KnowledgePage,
    PageLink,
    PageRevision,
    QueryEvent,
    RawDocument,
    ReviewEvent,
    Source,
)
from living_kb.schemas import (
    CompileRunResponse,
    CompileResponse,
    DashboardResponse,
    EnqueueJobRequest,
    HealthFindingResponse,
    IngestTextRequest,
    IngestUrlRequest,
    JobResponse,
    PageDiffResponse,
    PageLineageResponse,
    PageListItem,
    PageRevisionResponse,
    PageResponse,
    QueryRequest,
    QueryEventResponse,
    QueryResponse,
    RawDocumentDetailResponse,
    RawDocumentListItem,
    RawDocumentResponse,
    ReviewActionRequest,
    ReviewEventResponse,
    ReviewQueueItem,
)
from living_kb.services.compiler import CompilerService
from living_kb.services.health import HealthCheckService
from living_kb.services.ingestion import IngestionService
from living_kb.services.jobs import JobService, ReviewService
from living_kb.services.query import QueryService
from living_kb.services.embeddings import describe_embedding_provider, get_embedding_provider
from living_kb.utils import json_loads


router = APIRouter(prefix="/api", tags=["living-kb"])


def _raw_response(raw: RawDocument, title: str | None) -> RawDocumentResponse:
    return RawDocumentResponse(
        raw_id=raw.id,
        source_id=raw.source_id,
        status=raw.status,
        title=title,
        snapshot_path=raw.snapshot_path,
        asset_path=raw.asset_path,
    )


def _job_response(job: JobRun) -> JobResponse:
    return JobResponse(
        id=job.id,
        job_type=job.job_type,
        status=job.status,
        target_raw_id=job.target_raw_id,
        target_page_id=job.target_page_id,
        payload=json_loads(job.payload_json, {}),
        result=json_loads(job.result_json, None) if job.result_json else None,
        error_text=job.error_text,
        scheduled_for=job.scheduled_for,
        started_at=job.started_at,
        finished_at=job.finished_at,
        created_at=job.created_at,
    )


def _compile_run_response(run: CompileRun) -> CompileRunResponse:
    return CompileRunResponse(
        id=run.id,
        raw_id=run.raw_id,
        page_id=run.page_id,
        provider=run.provider,
        model_name=run.model_name,
        status=run.status,
        quality_score=run.quality_score,
        summary_length=run.summary_length,
        tag_count=run.tag_count,
        duration_ms=run.duration_ms,
        error_text=run.error_text,
        created_at=run.created_at,
    )


def _review_event_response(event: ReviewEvent) -> ReviewEventResponse:
    return ReviewEventResponse(
        id=event.id,
        item_type=event.item_type,
        action=event.action,
        page_id=event.page_id,
        finding_id=event.finding_id,
        notes=event.notes,
        created_at=event.created_at,
    )


def _query_event_response(event: QueryEvent) -> QueryEventResponse:
    return QueryEventResponse(
        id=event.id,
        question=event.question,
        answer_preview=event.answer_preview,
        citations=list(json_loads(event.citations_json, [])),
        suggested_actions=list(json_loads(event.suggested_actions_json, [])),
        confidence_score=event.confidence_score,
        created_at=event.created_at,
    )


@router.post("/ingest/text", response_model=RawDocumentResponse)
def ingest_text(
    payload: IngestTextRequest,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> RawDocumentResponse:
    raw = IngestionService(session, settings).ingest_text(
        title=payload.title,
        content=payload.content,
        source_type=payload.source_type,
        uri=payload.uri,
    )
    return _raw_response(raw, payload.title)


@router.post("/ingest/url", response_model=RawDocumentResponse)
def ingest_url(
    payload: IngestUrlRequest,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> RawDocumentResponse:
    try:
        raw = IngestionService(session, settings).ingest_url(payload.url)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    source = session.get(Source, raw.source_id)
    return _raw_response(raw, source.title if source else payload.url)


@router.post("/ingest/file", response_model=RawDocumentResponse)
async def ingest_file(
    file: UploadFile = File(...),
    source_type: str = Form(default="file"),
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> RawDocumentResponse:
    data = await file.read()
    service = IngestionService(session, settings)
    suffix = Path(file.filename or "").suffix.lower()

    if suffix == ".pdf":
        raw = service.ingest_pdf(file.filename or "upload.pdf", data)
    elif suffix in {".png", ".jpg", ".jpeg", ".webp"}:
        raw = service.ingest_image(file.filename or "image", data)
    else:
        raw = service.ingest_plain_file(file.filename or "upload.txt", data)

    source = session.get(Source, raw.source_id)
    title = source.title if source else file.filename
    return _raw_response(raw, title)


@router.post("/compile/{raw_id}", response_model=CompileResponse)
def compile_raw(
    raw_id: int,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> CompileResponse:
    try:
        page = CompilerService(session, settings).compile_raw(raw_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return CompileResponse(
        page_id=page.id,
        slug=page.slug,
        title=page.title,
        review_status=page.review_status,
        version=page.version,
        markdown_path=page.markdown_path,
    )


@router.post("/query", response_model=QueryResponse)
def query(
    payload: QueryRequest,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> QueryResponse:
    answer, citations, actions = QueryService(session, settings).answer(payload.question, payload.top_k)
    return QueryResponse(answer=answer, citations=citations, suggested_actions=actions)


@router.post("/health-check", response_model=list[HealthFindingResponse])
def run_health_check(
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> list[HealthFindingResponse]:
    findings = HealthCheckService(session, settings).run()
    return [
        HealthFindingResponse(
            id=finding.id,
            page_id=finding.page_id,
            finding_type=finding.finding_type,
            severity=finding.severity,
            status=finding.status,
            details=json_loads(finding.details_json, {}),
            review_notes=finding.review_notes,
            created_at=finding.created_at,
        )
        for finding in findings
    ]


@router.get("/raw-documents", response_model=list[RawDocumentListItem])
def list_raw_documents(session: Session = Depends(get_session)) -> list[RawDocumentListItem]:
    raws = list(
        session.execute(
            select(RawDocument, Source)
            .join(Source, Source.id == RawDocument.source_id)
            .order_by(RawDocument.created_at.desc())
            .limit(50)
        ).all()
    )
    return [
        RawDocumentListItem(
            raw_id=raw.id,
            source_id=source.id,
            title=source.title,
            source_type=source.source_type,
            status=raw.status,
            created_at=raw.created_at,
            snapshot_path=raw.snapshot_path,
        )
        for raw, source in raws
    ]


@router.get("/raw-documents/{raw_id}", response_model=RawDocumentDetailResponse)
def get_raw_document(raw_id: int, session: Session = Depends(get_session)) -> RawDocumentDetailResponse:
    row = session.execute(
        select(RawDocument, Source).join(Source, Source.id == RawDocument.source_id).where(RawDocument.id == raw_id)
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail=f"Raw document {raw_id} not found")

    raw, source = row
    linked_page = session.scalar(
        select(KnowledgePage)
        .where(KnowledgePage.generated_from_raw_id == raw.id)
        .order_by(KnowledgePage.updated_at.desc())
    )
    return RawDocumentDetailResponse(
        raw_id=raw.id,
        source_id=source.id,
        title=source.title,
        source_type=source.source_type,
        status=raw.status,
        uri=source.uri,
        created_at=raw.created_at,
        collected_at=source.collected_at,
        checksum=source.checksum,
        parser_version=raw.parser_version,
        snapshot_path=raw.snapshot_path,
        asset_path=raw.asset_path,
        linked_page_slug=linked_page.slug if linked_page else None,
        linked_page_title=linked_page.title if linked_page else None,
        linked_page_review_status=linked_page.review_status if linked_page else None,
        content_preview=raw.content_text[:4000],
    )


@router.get("/pages", response_model=list[PageListItem])
def list_pages(session: Session = Depends(get_session)) -> list[PageListItem]:
    pages = list(session.scalars(select(KnowledgePage).order_by(KnowledgePage.updated_at.desc()).limit(50)).all())
    return [
        PageListItem(
            id=page.id,
            slug=page.slug,
            title=page.title,
            page_type=page.page_type,
            review_status=page.review_status,
            updated_at=page.updated_at,
        )
        for page in pages
    ]


@router.get("/compile-runs", response_model=list[CompileRunResponse])
def list_compile_runs(
    page_slug: str | None = None,
    raw_id: int | None = None,
    status: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    session: Session = Depends(get_session),
) -> list[CompileRunResponse]:
    statement = select(CompileRun)
    if raw_id is not None:
        statement = statement.where(CompileRun.raw_id == raw_id)
    if status:
        statement = statement.where(CompileRun.status == status)
    if page_slug:
        page = session.scalar(select(KnowledgePage).where(KnowledgePage.slug == page_slug))
        if page:
            statement = statement.where(CompileRun.page_id == page.id)
        else:
            statement = statement.where(CompileRun.page_id == -1)
    runs = list(session.scalars(statement.order_by(CompileRun.created_at.desc()).limit(limit)).all())
    return [_compile_run_response(run) for run in runs]


@router.get("/review-events", response_model=list[ReviewEventResponse])
def list_review_events(
    page_slug: str | None = None,
    item_type: str | None = None,
    action: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    session: Session = Depends(get_session),
) -> list[ReviewEventResponse]:
    statement = select(ReviewEvent)
    if item_type:
        statement = statement.where(ReviewEvent.item_type == item_type)
    if action:
        statement = statement.where(ReviewEvent.action == action)
    if page_slug:
        page = session.scalar(select(KnowledgePage).where(KnowledgePage.slug == page_slug))
        if page:
            statement = statement.where(ReviewEvent.page_id == page.id)
        else:
            statement = statement.where(ReviewEvent.page_id == -1)
    events = list(session.scalars(statement.order_by(ReviewEvent.created_at.desc()).limit(limit)).all())
    return [_review_event_response(event) for event in events]


@router.get("/query-events", response_model=list[QueryEventResponse])
def list_query_events(
    page_slug: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    session: Session = Depends(get_session),
) -> list[QueryEventResponse]:
    events = list(session.scalars(select(QueryEvent).order_by(QueryEvent.created_at.desc()).limit(limit)).all())
    if page_slug:
        events = [
            event
            for event in events
            if any(citation.get("slug") == page_slug for citation in json_loads(event.citations_json, []))
        ]
    return [_query_event_response(event) for event in events]


@router.get("/pages/{slug}/revisions", response_model=list[PageRevisionResponse])
def list_page_revisions(slug: str, session: Session = Depends(get_session)) -> list[PageRevisionResponse]:
    page = session.scalar(select(KnowledgePage).where(KnowledgePage.slug == slug))
    if not page:
        raise HTTPException(status_code=404, detail=f"Page '{slug}' not found")

    revisions = list(
        session.scalars(
            select(PageRevision).where(PageRevision.page_id == page.id).order_by(PageRevision.version.desc())
        ).all()
    )
    return [
        PageRevisionResponse(
            id=revision.id,
            version=revision.version,
            markdown_path=revision.markdown_path,
            summary=revision.summary,
            tags=list(json_loads(revision.tags_json, [])),
            created_at=revision.created_at,
        )
        for revision in revisions
    ]


@router.get("/pages/{slug}/diff", response_model=PageDiffResponse)
def page_diff(
    slug: str,
    from_version: int | None = None,
    to_version: int | None = None,
    session: Session = Depends(get_session),
) -> PageDiffResponse:
    page = session.scalar(select(KnowledgePage).where(KnowledgePage.slug == slug))
    if not page:
        raise HTTPException(status_code=404, detail=f"Page '{slug}' not found")

    revisions = list(
        session.scalars(
            select(PageRevision).where(PageRevision.page_id == page.id).order_by(PageRevision.version.asc())
        ).all()
    )
    if len(revisions) < 2:
        raise HTTPException(status_code=400, detail="At least two revisions are required to compute a diff")

    if from_version is None or to_version is None:
        from_revision = revisions[-2]
        to_revision = revisions[-1]
    else:
        revision_by_version = {revision.version: revision for revision in revisions}
        from_revision = revision_by_version.get(from_version)
        to_revision = revision_by_version.get(to_version)
        if not from_revision or not to_revision:
            raise HTTPException(status_code=404, detail="Requested revisions not found")

    from_text = Path(from_revision.markdown_path).read_text(encoding="utf-8").splitlines()
    to_text = Path(to_revision.markdown_path).read_text(encoding="utf-8").splitlines()
    diff = "\n".join(
        difflib.unified_diff(
            from_text,
            to_text,
            fromfile=f"{slug}@v{from_revision.version}",
            tofile=f"{slug}@v{to_revision.version}",
            lineterm="",
        )
    )
    return PageDiffResponse(
        slug=slug,
        from_version=from_revision.version,
        to_version=to_revision.version,
        diff=diff or "No textual differences detected.",
    )


@router.get("/pages/{slug}/lineage", response_model=PageLineageResponse)
def page_lineage(slug: str, session: Session = Depends(get_session)) -> PageLineageResponse:
    page = session.scalar(select(KnowledgePage).where(KnowledgePage.slug == slug))
    if not page:
        raise HTTPException(status_code=404, detail=f"Page '{slug}' not found")

    revisions = list(
        session.scalars(
            select(PageRevision).where(PageRevision.page_id == page.id).order_by(PageRevision.version.desc())
        ).all()
    )
    compile_runs = list(
        session.scalars(
            select(CompileRun).where(CompileRun.page_id == page.id).order_by(CompileRun.created_at.desc())
        ).all()
    )
    review_events = list(
        session.scalars(
            select(ReviewEvent).where(ReviewEvent.page_id == page.id).order_by(ReviewEvent.created_at.desc())
        ).all()
    )
    query_events = list(session.scalars(select(QueryEvent).order_by(QueryEvent.created_at.desc()).limit(100)).all())
    query_events = [
        event
        for event in query_events
        if any(citation.get("slug") == slug for citation in json_loads(event.citations_json, []))
    ][:20]

    return PageLineageResponse(
        slug=page.slug,
        title=page.title,
        current_version=page.version,
        review_status=page.review_status,
        revisions=[
            PageRevisionResponse(
                id=revision.id,
                version=revision.version,
                markdown_path=revision.markdown_path,
                summary=revision.summary,
                tags=list(json_loads(revision.tags_json, [])),
                created_at=revision.created_at,
            )
            for revision in revisions
        ],
        compile_runs=[_compile_run_response(run) for run in compile_runs],
        review_events=[_review_event_response(event) for event in review_events],
        recent_queries=[_query_event_response(event) for event in query_events],
    )


@router.get("/pages/{slug}", response_model=PageResponse)
def get_page(slug: str, session: Session = Depends(get_session)) -> PageResponse:
    page = session.scalar(select(KnowledgePage).where(KnowledgePage.slug == slug))
    if not page:
        raise HTTPException(status_code=404, detail=f"Page '{slug}' not found")

    markdown = Path(page.markdown_path).read_text(encoding="utf-8")
    return PageResponse(
        id=page.id,
        slug=page.slug,
        title=page.title,
        page_type=page.page_type,
        summary=page.summary,
        review_status=page.review_status,
        version=page.version,
        tags=list(json_loads(page.tags_json, [])),
        source_refs=list(json_loads(page.source_refs_json, [])),
        markdown=markdown,
        updated_at=page.updated_at,
    )


@router.get("/dashboard", response_model=DashboardResponse)
def dashboard(
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> DashboardResponse:
    total_sources = session.scalar(select(func.count()).select_from(Source)) or 0
    total_raw_documents = session.scalar(select(func.count()).select_from(RawDocument)) or 0
    total_pages = session.scalar(select(func.count()).select_from(KnowledgePage)) or 0
    total_links = session.scalar(select(func.count()).select_from(PageLink)) or 0
    open_findings = session.scalar(
        select(func.count()).select_from(HealthFinding).where(HealthFinding.status == "open")
    ) or 0
    queued_jobs = session.scalar(
        select(func.count()).select_from(JobRun).where(JobRun.status == "queued")
    ) or 0
    running_jobs = session.scalar(
        select(func.count()).select_from(JobRun).where(JobRun.status == "running")
    ) or 0
    embedding_provider_name, _ = describe_embedding_provider(get_embedding_provider(settings), settings)
    llm_provider = settings.llm_provider.lower()
    llm_active = (
        (llm_provider == "openai" and bool(settings.openai_api_key))
        or (llm_provider == "minimax" and bool(settings.minimax_api_key))
    )
    return DashboardResponse(
        total_sources=total_sources,
        total_raw_documents=total_raw_documents,
        total_pages=total_pages,
        total_links=total_links,
        open_findings=open_findings,
        queued_jobs=queued_jobs,
        running_jobs=running_jobs,
        database_backend="postgresql" if settings.is_postgres else "sqlite",
        retrieval_mode="hybrid" if settings.is_postgres else "local-fallback",
        embedding_provider=embedding_provider_name,
        llm_provider=llm_provider,
        llm_active=llm_active,
    )


@router.post("/jobs/compile/{raw_id}", response_model=JobResponse)
def enqueue_compile_job(
    raw_id: int,
    payload: EnqueueJobRequest,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> JobResponse:
    if not session.get(RawDocument, raw_id):
        raise HTTPException(status_code=404, detail=f"Raw document {raw_id} not found")
    job = JobService(session, settings).enqueue_compile(raw_id, payload.run_at)
    return _job_response(job)


@router.post("/jobs/health-check", response_model=JobResponse)
def enqueue_health_job(
    payload: EnqueueJobRequest,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> JobResponse:
    job = JobService(session, settings).enqueue_health_check(payload.run_at)
    return _job_response(job)


@router.get("/jobs", response_model=list[JobResponse])
def list_jobs(
    status: str | None = None,
    job_type: str | None = None,
    target_raw_id: int | None = None,
    target_page_id: int | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> list[JobResponse]:
    jobs = JobService(session, settings).list_jobs(
        limit=limit,
        status=status,
        job_type=job_type,
        target_raw_id=target_raw_id,
        target_page_id=target_page_id,
    )
    return [_job_response(job) for job in jobs]


@router.get("/jobs/{job_id}", response_model=JobResponse)
def get_job(
    job_id: int,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> JobResponse:
    job = JobService(session, settings).get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    return _job_response(job)


@router.post("/jobs/run-once", response_model=JobResponse | None)
async def run_one_job(
    request: Request,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> JobResponse | None:
    scheduler = getattr(request.app.state, "scheduler", None)
    executed_job = None
    refreshed = None
    if scheduler:
        executed_job = await scheduler.run_once()
    if not executed_job:
        jobs = JobService(session, settings)
        jobs.ensure_scheduled_health_check()
        next_job = jobs.claim_next_job()
        if next_job:
            executed_job = jobs.run_job(next_job)
    if executed_job:
        refreshed = JobService(session, settings).get_job(executed_job.id)
    if refreshed:
        return _job_response(refreshed)
    return None


@router.post("/jobs/run-all", response_model=list[JobResponse])
def run_all_jobs(
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> list[JobResponse]:
    jobs = JobService(session, settings)
    executed: list[JobResponse] = []
    while True:
        next_job = jobs.claim_next_job()
        if not next_job:
            break
        executed_job = jobs.run_job(next_job)
        executed.append(_job_response(executed_job))
    return executed


@router.post("/jobs/{job_id}/run", response_model=JobResponse)
def run_specific_job(
    job_id: int,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> JobResponse:
    jobs = JobService(session, settings)
    job = jobs.claim_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Queued job {job_id} not found")
    return _job_response(jobs.run_job(job))


@router.get("/review-queue", response_model=list[ReviewQueueItem])
def review_queue(
    item_type: str | None = None,
    status: str | None = None,
    severity: str | None = None,
    page_slug: str | None = None,
    session: Session = Depends(get_session),
) -> list[ReviewQueueItem]:
    items = ReviewService(session).list_queue(
        item_type=item_type,
        status=status,
        severity=severity,
        page_slug=page_slug,
    )
    return [ReviewQueueItem(**item) for item in items]


@router.post("/review/pages/{page_id}/approve", response_model=PageResponse)
def approve_page(
    page_id: int,
    payload: ReviewActionRequest,
    session: Session = Depends(get_session),
) -> PageResponse:
    try:
        page = ReviewService(session).approve_page(page_id, payload.notes)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    markdown = Path(page.markdown_path).read_text(encoding="utf-8")
    return PageResponse(
        id=page.id,
        slug=page.slug,
        title=page.title,
        page_type=page.page_type,
        summary=page.summary,
        review_status=page.review_status,
        version=page.version,
        tags=list(json_loads(page.tags_json, [])),
        source_refs=list(json_loads(page.source_refs_json, [])),
        markdown=markdown,
        updated_at=page.updated_at,
    )


@router.post("/review/pages/{page_id}/reject", response_model=PageResponse)
def reject_page(
    page_id: int,
    payload: ReviewActionRequest,
    session: Session = Depends(get_session),
) -> PageResponse:
    try:
        page = ReviewService(session).reject_page(page_id, payload.notes)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    markdown = Path(page.markdown_path).read_text(encoding="utf-8")
    return PageResponse(
        id=page.id,
        slug=page.slug,
        title=page.title,
        page_type=page.page_type,
        summary=page.summary,
        review_status=page.review_status,
        version=page.version,
        tags=list(json_loads(page.tags_json, [])),
        source_refs=list(json_loads(page.source_refs_json, [])),
        markdown=markdown,
        updated_at=page.updated_at,
    )


@router.post("/review/findings/{finding_id}/resolve", response_model=HealthFindingResponse)
def resolve_finding(
    finding_id: int,
    payload: ReviewActionRequest,
    session: Session = Depends(get_session),
) -> HealthFindingResponse:
    try:
        finding = ReviewService(session).resolve_finding(finding_id, payload.notes, status="resolved")
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return HealthFindingResponse(
        id=finding.id,
        page_id=finding.page_id,
        finding_type=finding.finding_type,
        severity=finding.severity,
        status=finding.status,
        details=json_loads(finding.details_json, {}),
        review_notes=finding.review_notes,
        created_at=finding.created_at,
    )


@router.post("/review/findings/{finding_id}/dismiss", response_model=HealthFindingResponse)
def dismiss_finding(
    finding_id: int,
    payload: ReviewActionRequest,
    session: Session = Depends(get_session),
) -> HealthFindingResponse:
    try:
        finding = ReviewService(session).resolve_finding(finding_id, payload.notes, status="dismissed")
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return HealthFindingResponse(
        id=finding.id,
        page_id=finding.page_id,
        finding_type=finding.finding_type,
        severity=finding.severity,
        status=finding.status,
        details=json_loads(finding.details_json, {}),
        review_notes=finding.review_notes,
        created_at=finding.created_at,
    )
