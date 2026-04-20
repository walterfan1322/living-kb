from __future__ import annotations

from pathlib import Path

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from living_kb.config import Settings
from living_kb.models import KnowledgePage, PageEmbedding, QueryEvent
from living_kb.services.embeddings import cosine_similarity, get_embedding_provider
from living_kb.services.llm import QueryContextPage, get_llm_provider
from living_kb.utils import json_dumps, json_loads, tokenize


class QueryService:
    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.settings = settings

    def answer(self, question: str, top_k: int = 5) -> tuple[str, list[dict], list[str]]:
        scored_pages = self._rank_pages(question, top_k * 2)
        pages = [page for _, page in scored_pages]
        lexical_scores: dict[int, float] = {}
        question_tokens = tokenize(question)

        for page in pages:
            tags = json_loads(page.tags_json, [])
            corpus = " ".join(
                [
                    page.title,
                    page.summary,
                    " ".join(tags),
                    self._load_markdown_excerpt(page.markdown_path),
                ]
            ).lower()
            title_hits = sum(2 for token in question_tokens if token in page.title.lower())
            body_hits = sum(1 for token in question_tokens if token in corpus)
            score = float(title_hits + body_hits)
            lexical_scores[page.id] = score

        scored: list[tuple[float, KnowledgePage]] = []
        ranked_lookup = {page.id: score for score, page in scored_pages}
        for page in pages:
            combined = ranked_lookup.get(page.id, 0.0)
            if combined <= 0:
                lexical_component = lexical_scores.get(page.id, 0.0)
                combined = lexical_component * self.settings.retrieval_lexical_weight
            if combined > 0:
                scored.append((combined, page))

        scored.sort(key=lambda item: item[0], reverse=True)
        top = scored[: top_k * 2]
        context_pages = [
            QueryContextPage(
                slug=page.slug,
                title=page.title,
                summary=page.summary,
                markdown_excerpt=self._load_markdown_excerpt(page.markdown_path),
            )
            for _, page in top[:top_k]
        ]
        llm = get_llm_provider(self.settings)
        llm_result = llm.answer_question(question, context_pages)

        citations: list[dict] = []
        for score, page in top:
            if llm_result.cited_slugs and page.slug not in llm_result.cited_slugs:
                continue
            citations.append({"slug": page.slug, "title": page.title, "score": round(score, 2)})

        if not citations:
            citations = [
                {"slug": page.slug, "title": page.title, "score": round(score, 2)} for score, page in top
            ]

        suggested_actions = list(llm_result.suggested_actions)
        if top and any(score < 3 for score, _ in top):
            suggested_actions.append("Review low-confidence matches and create targeted concept pages")

        deduped_actions = list(dict.fromkeys(suggested_actions))
        confidence_score = round(
            sum(item["score"] for item in citations) / max(len(citations), 1) / 10,
            3,
        ) if citations else None
        self.session.add(
            QueryEvent(
                question=question,
                answer_preview=llm_result.answer[:1200],
                citations_json=json_dumps(citations),
                suggested_actions_json=json_dumps(deduped_actions),
                confidence_score=confidence_score,
            )
        )
        self.session.commit()
        return llm_result.answer, citations, deduped_actions

    def _rank_pages(self, question: str, limit: int) -> list[tuple[float, KnowledgePage]]:
        if self.session.bind and self.session.bind.dialect.name == "postgresql":
            try:
                ranked = self._postgres_hybrid_scores(question, limit)
                if ranked:
                    return ranked
            except Exception:
                pass
        return self._python_hybrid_scores(question, limit)

    def _postgres_hybrid_scores(self, question: str, limit: int) -> list[tuple[float, KnowledgePage]]:
        provider = get_embedding_provider(self.settings)
        query_embedding = provider.embed_text(question)
        ts_query = func.websearch_to_tsquery("simple", question)
        lexical_rank = func.ts_rank_cd(
            func.to_tsvector("simple", func.coalesce(KnowledgePage.search_text, "")),
            ts_query,
        )
        vector_similarity = 1 - PageEmbedding.embedding.cosine_distance(query_embedding)
        combined_score = (
            lexical_rank * self.settings.retrieval_lexical_weight
            + vector_similarity * 10 * self.settings.retrieval_vector_weight
        )
        statement = (
            select(KnowledgePage, combined_score.label("score"))
            .join(PageEmbedding, PageEmbedding.page_id == KnowledgePage.id)
            .where(
                or_(
                    lexical_rank > 0,
                    vector_similarity > 0.05,
                )
            )
            .order_by(combined_score.desc())
            .limit(limit)
        )
        rows = list(self.session.execute(statement).all())
        return [(float(score or 0.0), page) for page, score in rows if float(score or 0.0) > 0]

    def _python_hybrid_scores(self, question: str, limit: int) -> list[tuple[float, KnowledgePage]]:
        pages = list(self.session.scalars(select(KnowledgePage)).all())
        lexical_scores: dict[int, float] = {}
        question_tokens = tokenize(question)

        for page in pages:
            tags = json_loads(page.tags_json, [])
            corpus = " ".join(
                [
                    page.title,
                    page.summary,
                    page.search_text,
                    " ".join(tags),
                    self._load_markdown_excerpt(page.markdown_path),
                ]
            ).lower()
            title_hits = sum(2 for token in question_tokens if token in page.title.lower())
            body_hits = sum(1 for token in question_tokens if token in corpus)
            lexical_scores[page.id] = float(title_hits + body_hits)

        vector_scores = self._vector_scores(question)
        scored: list[tuple[float, KnowledgePage]] = []
        for page in pages:
            lexical_component = lexical_scores.get(page.id, 0.0)
            vector_component = vector_scores.get(page.id, 0.0)
            combined = (
                lexical_component * self.settings.retrieval_lexical_weight
                + vector_component * 10 * self.settings.retrieval_vector_weight
            )
            if combined > 0:
                scored.append((combined, page))

        scored.sort(key=lambda item: item[0], reverse=True)
        return scored[:limit]

    def _vector_scores(self, question: str) -> dict[int, float]:
        embeddings = list(self.session.scalars(select(PageEmbedding)).all())
        if not embeddings:
            return {}

        provider = get_embedding_provider(self.settings)
        query_embedding = provider.embed_text(question)
        if self.session.bind and self.session.bind.dialect.name == "postgresql":
            try:
                ranked = list(
                    self.session.execute(
                        select(
                            PageEmbedding.page_id,
                            PageEmbedding.embedding.cosine_distance(query_embedding).label("distance"),
                        )
                        .order_by("distance")
                        .limit(50)
                    ).all()
                )
                return {
                    page_id: round(max(0.0, 1.0 - float(distance or 0.0)), 4)
                    for page_id, distance in ranked
                }
            except Exception:
                pass

        scores: dict[int, float] = {}
        for item in embeddings:
            if not isinstance(item.embedding, list):
                continue
            similarity = cosine_similarity(query_embedding, item.embedding)
            scores[item.page_id] = max(scores.get(item.page_id, -1.0), round(similarity, 4))
        return scores

    def _load_markdown_excerpt(self, markdown_path: str) -> str:
        path = Path(markdown_path)
        if not path.exists():
            return ""
        return path.read_text(encoding="utf-8")[:1500]
