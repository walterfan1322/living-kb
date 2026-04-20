"""initial schema

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-04-20 00:00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector


revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "sources",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source_type", sa.String(length=32), nullable=False),
        sa.Column("uri", sa.String(length=1024), nullable=True),
        sa.Column("title", sa.String(length=255), nullable=True),
        sa.Column("author", sa.String(length=255), nullable=True),
        sa.Column("language", sa.String(length=32), nullable=True),
        sa.Column("checksum", sa.String(length=64), nullable=False),
        sa.Column("collected_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_sources_source_type", "sources", ["source_type"])
    op.create_index("ix_sources_checksum", "sources", ["checksum"])

    op.create_table(
        "raw_documents",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source_id", sa.Integer(), sa.ForeignKey("sources.id"), nullable=False),
        sa.Column("parser_version", sa.String(length=32), nullable=False, server_default="mvp-v1"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="ingested"),
        sa.Column("content_text", sa.Text(), nullable=False),
        sa.Column("asset_path", sa.String(length=1024), nullable=True),
        sa.Column("snapshot_path", sa.String(length=1024), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_raw_documents_source_id", "raw_documents", ["source_id"])
    op.create_index("ix_raw_documents_status", "raw_documents", ["status"])

    op.create_table(
        "knowledge_pages",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("slug", sa.String(length=255), nullable=False, unique=True),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("page_type", sa.String(length=64), nullable=False, server_default="topic"),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("search_text", sa.Text(), nullable=False, server_default=""),
        sa.Column("tags_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("source_refs_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("markdown_path", sa.String(length=1024), nullable=False),
        sa.Column("generated_from_raw_id", sa.Integer(), sa.ForeignKey("raw_documents.id"), nullable=True),
        sa.Column("review_status", sa.String(length=32), nullable=False, server_default="approved"),
        sa.Column("review_notes", sa.Text(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_knowledge_pages_slug", "knowledge_pages", ["slug"], unique=True)
    op.create_index("ix_knowledge_pages_title", "knowledge_pages", ["title"])
    op.create_index("ix_knowledge_pages_review_status", "knowledge_pages", ["review_status"])
    op.create_index("ix_knowledge_pages_generated_from_raw_id", "knowledge_pages", ["generated_from_raw_id"])
    if bind.dialect.name == "postgresql":
        op.execute(
            "CREATE INDEX ix_knowledge_pages_search_text_fts "
            "ON knowledge_pages USING GIN (to_tsvector('simple', coalesce(search_text, '')))"
        )

    op.create_table(
        "page_revisions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("page_id", sa.Integer(), sa.ForeignKey("knowledge_pages.id"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("markdown_path", sa.String(length=1024), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("tags_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_page_revisions_page_id", "page_revisions", ["page_id"])
    op.create_index("ix_page_revisions_version", "page_revisions", ["version"])

    op.create_table(
        "page_links",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("from_page_id", sa.Integer(), sa.ForeignKey("knowledge_pages.id"), nullable=False),
        sa.Column("to_page_id", sa.Integer(), sa.ForeignKey("knowledge_pages.id"), nullable=False),
        sa.Column("relation_type", sa.String(length=64), nullable=False, server_default="related_to"),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_page_links_from_page_id", "page_links", ["from_page_id"])
    op.create_index("ix_page_links_to_page_id", "page_links", ["to_page_id"])

    op.create_table(
        "health_findings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("page_id", sa.Integer(), sa.ForeignKey("knowledge_pages.id"), nullable=True),
        sa.Column("finding_type", sa.String(length=64), nullable=False),
        sa.Column("severity", sa.String(length=16), nullable=False, server_default="medium"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="open"),
        sa.Column("details_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("review_notes", sa.Text(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_health_findings_page_id", "health_findings", ["page_id"])
    op.create_index("ix_health_findings_finding_type", "health_findings", ["finding_type"])
    op.create_index("ix_health_findings_status", "health_findings", ["status"])

    op.create_table(
        "job_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("job_type", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="queued"),
        sa.Column("target_raw_id", sa.Integer(), sa.ForeignKey("raw_documents.id"), nullable=True),
        sa.Column("target_page_id", sa.Integer(), sa.ForeignKey("knowledge_pages.id"), nullable=True),
        sa.Column("payload_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("result_json", sa.Text(), nullable=True),
        sa.Column("error_text", sa.Text(), nullable=True),
        sa.Column("scheduled_for", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_job_runs_job_type", "job_runs", ["job_type"])
    op.create_index("ix_job_runs_status", "job_runs", ["status"])
    op.create_index("ix_job_runs_target_raw_id", "job_runs", ["target_raw_id"])
    op.create_index("ix_job_runs_target_page_id", "job_runs", ["target_page_id"])
    op.create_index("ix_job_runs_scheduled_for", "job_runs", ["scheduled_for"])

    op.create_table(
        "compile_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("raw_id", sa.Integer(), sa.ForeignKey("raw_documents.id"), nullable=True),
        sa.Column("page_id", sa.Integer(), sa.ForeignKey("knowledge_pages.id"), nullable=True),
        sa.Column("provider", sa.String(length=64), nullable=False, server_default="heuristic"),
        sa.Column("model_name", sa.String(length=128), nullable=False, server_default="local-heuristic"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="completed"),
        sa.Column("quality_score", sa.Float(), nullable=True),
        sa.Column("summary_length", sa.Integer(), nullable=True),
        sa.Column("tag_count", sa.Integer(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("error_text", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_compile_runs_raw_id", "compile_runs", ["raw_id"])
    op.create_index("ix_compile_runs_page_id", "compile_runs", ["page_id"])
    op.create_index("ix_compile_runs_provider", "compile_runs", ["provider"])
    op.create_index("ix_compile_runs_status", "compile_runs", ["status"])

    op.create_table(
        "review_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("item_type", sa.String(length=32), nullable=False),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column("page_id", sa.Integer(), sa.ForeignKey("knowledge_pages.id"), nullable=True),
        sa.Column("finding_id", sa.Integer(), sa.ForeignKey("health_findings.id"), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_review_events_item_type", "review_events", ["item_type"])
    op.create_index("ix_review_events_action", "review_events", ["action"])
    op.create_index("ix_review_events_page_id", "review_events", ["page_id"])
    op.create_index("ix_review_events_finding_id", "review_events", ["finding_id"])

    op.create_table(
        "query_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("answer_preview", sa.Text(), nullable=False),
        sa.Column("citations_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("suggested_actions_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("confidence_score", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "page_embeddings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("page_id", sa.Integer(), sa.ForeignKey("knowledge_pages.id"), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("embedding", Vector(1536), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False, server_default="deterministic"),
        sa.Column("model_name", sa.String(length=128), nullable=False, server_default="local-hash"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_page_embeddings_page_id", "page_embeddings", ["page_id"])
    if bind.dialect.name == "postgresql":
        op.execute(
            "CREATE INDEX ix_page_embeddings_embedding_cosine "
            "ON page_embeddings USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100)"
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP INDEX IF EXISTS ix_page_embeddings_embedding_cosine")
    op.drop_index("ix_page_embeddings_page_id", table_name="page_embeddings")
    op.drop_table("page_embeddings")
    op.drop_table("query_events")
    op.drop_index("ix_review_events_finding_id", table_name="review_events")
    op.drop_index("ix_review_events_page_id", table_name="review_events")
    op.drop_index("ix_review_events_action", table_name="review_events")
    op.drop_index("ix_review_events_item_type", table_name="review_events")
    op.drop_table("review_events")
    op.drop_index("ix_compile_runs_status", table_name="compile_runs")
    op.drop_index("ix_compile_runs_provider", table_name="compile_runs")
    op.drop_index("ix_compile_runs_page_id", table_name="compile_runs")
    op.drop_index("ix_compile_runs_raw_id", table_name="compile_runs")
    op.drop_table("compile_runs")
    op.drop_index("ix_job_runs_scheduled_for", table_name="job_runs")
    op.drop_index("ix_job_runs_target_page_id", table_name="job_runs")
    op.drop_index("ix_job_runs_target_raw_id", table_name="job_runs")
    op.drop_index("ix_job_runs_status", table_name="job_runs")
    op.drop_index("ix_job_runs_job_type", table_name="job_runs")
    op.drop_table("job_runs")
    op.drop_index("ix_health_findings_status", table_name="health_findings")
    op.drop_index("ix_health_findings_finding_type", table_name="health_findings")
    op.drop_index("ix_health_findings_page_id", table_name="health_findings")
    op.drop_table("health_findings")
    op.drop_index("ix_page_links_to_page_id", table_name="page_links")
    op.drop_index("ix_page_links_from_page_id", table_name="page_links")
    op.drop_table("page_links")
    op.drop_index("ix_page_revisions_version", table_name="page_revisions")
    op.drop_index("ix_page_revisions_page_id", table_name="page_revisions")
    op.drop_table("page_revisions")
    if bind.dialect.name == "postgresql":
        op.execute("DROP INDEX IF EXISTS ix_knowledge_pages_search_text_fts")
    op.drop_index("ix_knowledge_pages_generated_from_raw_id", table_name="knowledge_pages")
    op.drop_index("ix_knowledge_pages_review_status", table_name="knowledge_pages")
    op.drop_index("ix_knowledge_pages_title", table_name="knowledge_pages")
    op.drop_index("ix_knowledge_pages_slug", table_name="knowledge_pages")
    op.drop_table("knowledge_pages")
    op.drop_index("ix_raw_documents_status", table_name="raw_documents")
    op.drop_index("ix_raw_documents_source_id", table_name="raw_documents")
    op.drop_table("raw_documents")
    op.drop_index("ix_sources_checksum", table_name="sources")
    op.drop_index("ix_sources_source_type", table_name="sources")
    op.drop_table("sources")
