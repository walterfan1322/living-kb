from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter

from sqlalchemy import delete, or_, select
from sqlalchemy.orm import Session

from living_kb.config import Settings
from living_kb.models import CompileRun, KnowledgePage, PageEmbedding, PageLink, PageRevision, RawDocument, Source
from living_kb.services.embeddings import describe_embedding_provider, get_embedding_provider
from living_kb.services.llm import describe_llm_provider, get_llm_provider
from living_kb.utils import jaccard_similarity, json_dumps, json_loads, slugify, write_text


class CompilerService:
    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.settings = settings

    def compile_raw(self, raw_id: int) -> KnowledgePage:
        started = perf_counter()
        raw = self.session.get(RawDocument, raw_id)
        if not raw:
            raise ValueError(f"Raw document {raw_id} not found")

        source = self.session.get(Source, raw.source_id)
        if not source:
            raise ValueError(f"Source for raw document {raw_id} not found")

        llm = get_llm_provider(self.settings)
        provider_name, model_name = describe_llm_provider(llm)

        try:
            compiled = llm.compile_document(source.title, raw.content_text)
            title = compiled.title.strip() or source.title or "Untitled Raw Document"
            tags = list(dict.fromkeys(tag.strip().lower() for tag in compiled.tags if tag.strip()))[:10]
            summary = compiled.summary.strip()
            slug = slugify(title)
            page = self.session.scalar(select(KnowledgePage).where(KnowledgePage.slug == slug))
            source_refs = [
                {
                    "source_id": source.id,
                    "raw_document_id": raw.id,
                    "title": source.title,
                    "uri": source.uri,
                    "compiled_at": datetime.now(timezone.utc).isoformat(),
                }
            ]
            search_text = self._build_search_text(
                title=title,
                summary=summary,
                tags=tags,
                raw_text=raw.content_text,
                key_points=compiled.key_points,
                open_questions=compiled.open_questions,
            )

            if page:
                page.summary = summary
                page.page_type = compiled.page_type
                page.search_text = search_text
                page.tags_json = json_dumps(tags)
                page.source_refs_json = json_dumps(source_refs)
                page.generated_from_raw_id = raw.id
                page.version += 1
                page.review_status = "pending_review"
            else:
                page = KnowledgePage(
                    slug=slug,
                    title=title,
                    page_type=compiled.page_type,
                    summary=summary,
                    search_text=search_text,
                    tags_json=json_dumps(tags),
                    source_refs_json=json_dumps(source_refs),
                    markdown_path=str(self.settings.pages_dir / f"{slug}.md"),
                    generated_from_raw_id=raw.id,
                    review_status="pending_review",
                    version=1,
                )
                self.session.add(page)
                self.session.flush()

            markdown_path = Path(page.markdown_path)
            markdown = self._render_markdown(
                page.title,
                page.page_type,
                page.summary,
                tags,
                source_refs,
                raw.content_text,
                compiled.key_points,
                compiled.open_questions,
            )
            write_text(markdown_path, markdown)
            self._write_revision(page, markdown, tags)
            self._write_embedding(page, markdown)

            raw.status = "compiled"
            self.session.flush()
            self._refresh_links(page, tags)
            self._record_compile_run(
                raw_id=raw.id,
                page_id=page.id,
                provider=provider_name,
                model_name=model_name,
                status="completed",
                summary=summary,
                tags=tags,
                duration_ms=int((perf_counter() - started) * 1000),
                error_text=None,
            )
            self.session.commit()
            self.session.refresh(page)
            return page
        except Exception as exc:
            self.session.rollback()
            self._record_compile_run(
                raw_id=raw.id,
                page_id=None,
                provider=provider_name,
                model_name=model_name,
                status="failed",
                summary=None,
                tags=[],
                duration_ms=int((perf_counter() - started) * 1000),
                error_text=str(exc),
            )
            self.session.commit()
            raise

    def _write_revision(self, page: KnowledgePage, markdown: str, tags: list[str]) -> None:
        revision_path = self.settings.revisions_dir / f"{page.slug}_v{page.version}.md"
        write_text(revision_path, markdown)
        self.session.add(
            PageRevision(
                page_id=page.id,
                version=page.version,
                markdown_path=str(revision_path),
                summary=page.summary,
                tags_json=json_dumps(tags),
            )
        )

    def _write_embedding(self, page: KnowledgePage, markdown: str) -> None:
        content = "\n".join([page.title, page.summary, markdown[:2500]])
        provider = get_embedding_provider(self.settings)
        provider_name, model_name = describe_embedding_provider(provider, self.settings)
        embedding = provider.embed_text(content)
        self.session.execute(delete(PageEmbedding).where(PageEmbedding.page_id == page.id))
        self.session.add(
            PageEmbedding(
                page_id=page.id,
                chunk_index=0,
                content=content[:8000],
                embedding=embedding,
                provider=provider_name,
                model_name=model_name,
            )
        )

    def _record_compile_run(
        self,
        raw_id: int,
        page_id: int | None,
        provider: str,
        model_name: str,
        status: str,
        summary: str | None,
        tags: list[str],
        duration_ms: int,
        error_text: str | None,
    ) -> None:
        summary_length = len(summary) if summary else None
        quality_score = None
        if status == "completed" and summary:
            quality_score = round(
                min(1.0, 0.35 + min(summary_length, 400) / 800 + min(len(tags), 8) / 20),
                3,
            )

        self.session.add(
            CompileRun(
                raw_id=raw_id,
                page_id=page_id,
                provider=provider,
                model_name=model_name,
                status=status,
                quality_score=quality_score,
                summary_length=summary_length,
                tag_count=len(tags),
                duration_ms=duration_ms,
                error_text=error_text,
            )
        )

    def _render_markdown(
        self,
        title: str,
        page_type: str,
        summary: str,
        tags: list[str],
        source_refs: list[dict],
        raw_text: str,
        key_points: list[str],
        open_questions: list[str],
    ) -> str:
        preview = raw_text[:2500].strip()
        frontmatter = "\n".join(
            [
                "---",
                f'title: "{title.replace(chr(34), "")}"',
                'status: "active"',
                f'page_type: "{page_type}"',
                f'tags: [{", ".join(f"""\"{tag}\"""" for tag in tags)}]',
                "---",
                "",
            ]
        )
        sections = [
            frontmatter,
            f"# {title}",
            "",
            "## Summary",
            summary or "No summary available yet.",
            "",
            "## Key Points",
            "\n".join(f"- {point}" for point in key_points) or "- None yet.",
            "",
            "## Open Questions",
            "\n".join(f"- {question}" for question in open_questions) or "- None yet.",
            "",
            "## Source References",
            json_dumps(source_refs),
            "",
            "## Raw Context Preview",
            preview or "No raw content available.",
            "",
        ]
        return "\n".join(sections)

    def _build_search_text(
        self,
        title: str,
        summary: str,
        tags: list[str],
        raw_text: str,
        key_points: list[str],
        open_questions: list[str],
    ) -> str:
        return "\n".join(
            [
                title.strip(),
                summary.strip(),
                " ".join(tags).strip(),
                "\n".join(key_points).strip(),
                "\n".join(open_questions).strip(),
                raw_text[:4000].strip(),
            ]
        ).strip()

    def _refresh_links(self, page: KnowledgePage, tags: list[str]) -> None:
        self.session.execute(
            delete(PageLink).where(
                or_(PageLink.from_page_id == page.id, PageLink.to_page_id == page.id)
            )
        )
        other_pages = list(
            self.session.scalars(select(KnowledgePage).where(KnowledgePage.id != page.id)).all()
        )
        page_tags = set(tags)
        for other in other_pages:
            other_tags = set(json_loads(other.tags_json, []))
            confidence = jaccard_similarity(page_tags, other_tags)
            if confidence < 0.2:
                continue

            self.session.add(
                PageLink(
                    from_page_id=page.id,
                    to_page_id=other.id,
                    relation_type="related_to",
                    confidence=round(confidence, 3),
                )
            )
            self.session.add(
                PageLink(
                    from_page_id=other.id,
                    to_page_id=page.id,
                    relation_type="related_to",
                    confidence=round(confidence, 3),
                )
            )
