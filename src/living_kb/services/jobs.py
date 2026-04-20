from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from living_kb.config import Settings
from living_kb.models import HealthFinding, JobRun, KnowledgePage, ReviewEvent
from living_kb.services.compiler import CompilerService
from living_kb.services.health import HealthCheckService
from living_kb.utils import json_dumps, json_loads


class JobService:
    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.settings = settings

    def enqueue_compile(self, raw_id: int, run_at: datetime | None = None) -> JobRun:
        job = JobRun(
            job_type="compile_raw",
            target_raw_id=raw_id,
            scheduled_for=run_at or datetime.now(timezone.utc),
        )
        self.session.add(job)
        self.session.commit()
        self.session.refresh(job)
        return job

    def enqueue_health_check(self, run_at: datetime | None = None, reason: str = "manual") -> JobRun:
        job = JobRun(
            job_type="health_check",
            payload_json=json_dumps({"reason": reason}),
            scheduled_for=run_at or datetime.now(timezone.utc),
        )
        self.session.add(job)
        self.session.commit()
        self.session.refresh(job)
        return job

    def list_jobs(
        self,
        limit: int = 50,
        status: str | None = None,
        job_type: str | None = None,
        target_raw_id: int | None = None,
        target_page_id: int | None = None,
    ) -> list[JobRun]:
        statement = select(JobRun)
        if status:
            statement = statement.where(JobRun.status == status)
        if job_type:
            statement = statement.where(JobRun.job_type == job_type)
        if target_raw_id is not None:
            statement = statement.where(JobRun.target_raw_id == target_raw_id)
        if target_page_id is not None:
            statement = statement.where(JobRun.target_page_id == target_page_id)
        statement = statement.order_by(JobRun.created_at.desc()).limit(limit)
        return list(self.session.scalars(statement).all())

    def get_job(self, job_id: int) -> JobRun | None:
        return self.session.get(JobRun, job_id)

    def claim_job(self, job_id: int) -> JobRun | None:
        job = self.session.get(JobRun, job_id)
        if not job or job.status != "queued":
            return None
        job.status = "running"
        job.started_at = datetime.now(timezone.utc)
        self.session.commit()
        self.session.refresh(job)
        return job

    def claim_next_job(self) -> JobRun | None:
        now = datetime.now(timezone.utc)
        job = self.session.scalar(
            select(JobRun)
            .where(
                and_(
                    JobRun.status == "queued",
                    or_(JobRun.scheduled_for.is_(None), JobRun.scheduled_for <= now),
                )
            )
            .order_by(JobRun.scheduled_for.asc(), JobRun.id.asc())
        )
        if not job:
            return None

        job.status = "running"
        job.started_at = now
        self.session.commit()
        self.session.refresh(job)
        return job

    def run_job(self, job: JobRun) -> JobRun:
        try:
            if job.job_type == "compile_raw":
                if not job.target_raw_id:
                    raise ValueError("compile_raw job missing target_raw_id")
                page = CompilerService(self.session, self.settings).compile_raw(job.target_raw_id)
                job.target_page_id = page.id
                job.result_json = json_dumps(
                    {
                        "page_id": page.id,
                        "slug": page.slug,
                        "review_status": page.review_status,
                    }
                )
            elif job.job_type == "health_check":
                findings = HealthCheckService(self.session, self.settings).run()
                job.result_json = json_dumps(
                    {
                        "finding_count": len(findings),
                        "finding_ids": [finding.id for finding in findings],
                    }
                )
            else:
                raise ValueError(f"Unsupported job type: {job.job_type}")

            job.status = "completed"
            job.error_text = None
        except Exception as exc:
            self.session.rollback()
            fresh_job = self.session.get(JobRun, job.id)
            if not fresh_job:
                raise
            job = fresh_job
            job.status = "failed"
            job.error_text = str(exc)
        finally:
            job.finished_at = datetime.now(timezone.utc)
            self.session.commit()
            self.session.refresh(job)
        return job

    def ensure_scheduled_health_check(self) -> JobRun | None:
        if self.settings.health_check_interval_seconds <= 0:
            return None

        latest_health_job = self.session.scalar(
            select(JobRun)
            .where(JobRun.job_type == "health_check")
            .order_by(JobRun.created_at.desc())
        )
        now = datetime.now(timezone.utc)
        if latest_health_job and latest_health_job.created_at:
            last_run = latest_health_job.created_at
            if last_run.tzinfo is None:
                last_run = last_run.replace(tzinfo=timezone.utc)
            elapsed = (now - last_run).total_seconds()
            if elapsed < self.settings.health_check_interval_seconds:
                return None

        existing_open = self.session.scalar(
            select(JobRun).where(
                and_(JobRun.job_type == "health_check", JobRun.status.in_(["queued", "running"]))
            )
        )
        if existing_open:
            return None

        return self.enqueue_health_check(reason="scheduled")


class ReviewService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def list_queue(
        self,
        item_type: str | None = None,
        status: str | None = None,
        severity: str | None = None,
        page_slug: str | None = None,
    ) -> list[dict]:
        page_statement = select(KnowledgePage)
        finding_statement = select(HealthFinding)

        if not item_type or item_type == "page":
            page_status = status or "pending_review"
            page_statement = page_statement.where(KnowledgePage.review_status == page_status)
            if page_slug:
                page_statement = page_statement.where(KnowledgePage.slug == page_slug)
            page_items = list(self.session.scalars(page_statement).all())
        else:
            page_items = []

        if not item_type or item_type == "finding":
            finding_status = status or "open"
            finding_statement = finding_statement.where(HealthFinding.status == finding_status)
            if severity:
                finding_statement = finding_statement.where(HealthFinding.severity == severity)
            if page_slug:
                page = self.session.scalar(select(KnowledgePage).where(KnowledgePage.slug == page_slug))
                if page:
                    finding_statement = finding_statement.where(HealthFinding.page_id == page.id)
                else:
                    finding_statement = finding_statement.where(HealthFinding.page_id == -1)
            finding_items = list(self.session.scalars(finding_statement).all())
        else:
            finding_items = []

        items: list[dict] = []
        for page in page_items:
            items.append(
                {
                    "item_type": "page",
                    "id": page.id,
                    "title": page.title,
                    "status": page.review_status,
                    "page_slug": page.slug,
                    "page_id": page.id,
                    "created_at": page.updated_at or page.created_at,
                    "details": {"summary": page.summary},
                }
            )

        for finding in finding_items:
            items.append(
                {
                    "item_type": "finding",
                    "id": finding.id,
                    "title": finding.finding_type.replace("_", " ").title(),
                    "status": finding.status,
                    "severity": finding.severity,
                    "page_id": finding.page_id,
                    "created_at": finding.created_at,
                    "details": {
                        "finding": json_loads(finding.details_json, {}),
                        "review_notes": finding.review_notes,
                    },
                }
            )

        items.sort(key=lambda item: item["created_at"] or datetime.min, reverse=True)
        return items

    def approve_page(self, page_id: int, notes: str | None = None) -> KnowledgePage:
        page = self.session.get(KnowledgePage, page_id)
        if not page:
            raise ValueError(f"Page {page_id} not found")
        page.review_status = "approved"
        page.review_notes = notes
        self._record_review_event(item_type="page", action="approve", page_id=page.id, notes=notes)
        self.session.commit()
        self.session.refresh(page)
        return page

    def reject_page(self, page_id: int, notes: str | None = None) -> KnowledgePage:
        page = self.session.get(KnowledgePage, page_id)
        if not page:
            raise ValueError(f"Page {page_id} not found")
        page.review_status = "rejected"
        page.review_notes = notes
        self._record_review_event(item_type="page", action="reject", page_id=page.id, notes=notes)
        self.session.commit()
        self.session.refresh(page)
        return page

    def resolve_finding(
        self, finding_id: int, notes: str | None = None, status: str = "resolved"
    ) -> HealthFinding:
        finding = self.session.get(HealthFinding, finding_id)
        if not finding:
            raise ValueError(f"Finding {finding_id} not found")
        finding.status = status
        finding.review_notes = notes
        finding.resolved_at = datetime.now(timezone.utc)
        self._record_review_event(
            item_type="finding",
            action=status,
            page_id=finding.page_id,
            finding_id=finding.id,
            notes=notes,
        )
        self.session.commit()
        self.session.refresh(finding)
        return finding

    def _record_review_event(
        self,
        item_type: str,
        action: str,
        page_id: int | None = None,
        finding_id: int | None = None,
        notes: str | None = None,
    ) -> None:
        self.session.add(
            ReviewEvent(
                item_type=item_type,
                action=action,
                page_id=page_id,
                finding_id=finding_id,
                notes=notes,
            )
        )
