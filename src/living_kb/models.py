from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from living_kb.db import Base
from living_kb.vector_types import EmbeddingVector


class Source(Base):
    __tablename__ = "sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_type: Mapped[str] = mapped_column(String(32), index=True)
    uri: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    author: Mapped[str | None] = mapped_column(String(255), nullable=True)
    language: Mapped[str | None] = mapped_column(String(32), nullable=True)
    checksum: Mapped[str] = mapped_column(String(64), index=True)
    collected_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    raw_documents: Mapped[list["RawDocument"]] = relationship(back_populates="source")


class RawDocument(Base):
    __tablename__ = "raw_documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"), index=True)
    parser_version: Mapped[str] = mapped_column(String(32), default="mvp-v1")
    status: Mapped[str] = mapped_column(String(32), default="ingested", index=True)
    content_text: Mapped[str] = mapped_column(Text)
    asset_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    snapshot_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    source: Mapped[Source] = relationship(back_populates="raw_documents")


class KnowledgePage(Base):
    __tablename__ = "knowledge_pages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slug: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(255), index=True)
    page_type: Mapped[str] = mapped_column(String(64), default="topic")
    summary: Mapped[str] = mapped_column(Text)
    search_text: Mapped[str] = mapped_column(Text, default="")
    tags_json: Mapped[str] = mapped_column(Text, default="[]")
    source_refs_json: Mapped[str] = mapped_column(Text, default="[]")
    markdown_path: Mapped[str] = mapped_column(String(1024))
    generated_from_raw_id: Mapped[int | None] = mapped_column(
        ForeignKey("raw_documents.id"), nullable=True, index=True
    )
    review_status: Mapped[str] = mapped_column(String(32), default="approved", index=True)
    review_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    revisions: Mapped[list["PageRevision"]] = relationship(back_populates="page")


class PageRevision(Base):
    __tablename__ = "page_revisions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    page_id: Mapped[int] = mapped_column(ForeignKey("knowledge_pages.id"), index=True)
    version: Mapped[int] = mapped_column(Integer, index=True)
    markdown_path: Mapped[str] = mapped_column(String(1024))
    summary: Mapped[str] = mapped_column(Text)
    tags_json: Mapped[str] = mapped_column(Text, default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    page: Mapped[KnowledgePage] = relationship(back_populates="revisions")


class PageLink(Base):
    __tablename__ = "page_links"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    from_page_id: Mapped[int] = mapped_column(ForeignKey("knowledge_pages.id"), index=True)
    to_page_id: Mapped[int] = mapped_column(ForeignKey("knowledge_pages.id"), index=True)
    relation_type: Mapped[str] = mapped_column(String(64), default="related_to")
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class HealthFinding(Base):
    __tablename__ = "health_findings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    page_id: Mapped[int | None] = mapped_column(
        ForeignKey("knowledge_pages.id"), nullable=True, index=True
    )
    finding_type: Mapped[str] = mapped_column(String(64), index=True)
    severity: Mapped[str] = mapped_column(String(16), default="medium")
    status: Mapped[str] = mapped_column(String(32), default="open", index=True)
    details_json: Mapped[str] = mapped_column(Text, default="{}")
    review_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class JobRun(Base):
    __tablename__ = "job_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_type: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(32), default="queued", index=True)
    target_raw_id: Mapped[int | None] = mapped_column(
        ForeignKey("raw_documents.id"), nullable=True, index=True
    )
    target_page_id: Mapped[int | None] = mapped_column(
        ForeignKey("knowledge_pages.id"), nullable=True, index=True
    )
    payload_json: Mapped[str] = mapped_column(Text, default="{}")
    result_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    scheduled_for: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class CompileRun(Base):
    __tablename__ = "compile_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    raw_id: Mapped[int | None] = mapped_column(ForeignKey("raw_documents.id"), nullable=True, index=True)
    page_id: Mapped[int | None] = mapped_column(
        ForeignKey("knowledge_pages.id"), nullable=True, index=True
    )
    provider: Mapped[str] = mapped_column(String(64), default="heuristic", index=True)
    model_name: Mapped[str] = mapped_column(String(128), default="local-heuristic")
    status: Mapped[str] = mapped_column(String(32), default="completed", index=True)
    quality_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    summary_length: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tag_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class ReviewEvent(Base):
    __tablename__ = "review_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    item_type: Mapped[str] = mapped_column(String(32), index=True)
    action: Mapped[str] = mapped_column(String(32), index=True)
    page_id: Mapped[int | None] = mapped_column(
        ForeignKey("knowledge_pages.id"), nullable=True, index=True
    )
    finding_id: Mapped[int | None] = mapped_column(
        ForeignKey("health_findings.id"), nullable=True, index=True
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class QueryEvent(Base):
    __tablename__ = "query_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    question: Mapped[str] = mapped_column(Text)
    answer_preview: Mapped[str] = mapped_column(Text)
    citations_json: Mapped[str] = mapped_column(Text, default="[]")
    suggested_actions_json: Mapped[str] = mapped_column(Text, default="[]")
    confidence_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class PageEmbedding(Base):
    __tablename__ = "page_embeddings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    page_id: Mapped[int] = mapped_column(ForeignKey("knowledge_pages.id"), index=True)
    chunk_index: Mapped[int] = mapped_column(Integer, default=0)
    content: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list[float]] = mapped_column(EmbeddingVector(1536))
    provider: Mapped[str] = mapped_column(String(64), default="deterministic")
    model_name: Mapped[str] = mapped_column(String(128), default="local-hash")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
