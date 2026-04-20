from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Protocol

from pydantic import BaseModel, Field

from living_kb.config import Settings
from living_kb.utils import extract_keywords, sentence_split, summarize_text


class CompileDocumentResult(BaseModel):
    title: str
    summary: str = Field(min_length=1)
    tags: list[str] = Field(default_factory=list)
    page_type: str = "topic"
    key_points: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)


class QueryAnswerResult(BaseModel):
    answer: str = Field(min_length=1)
    cited_slugs: list[str] = Field(default_factory=list)
    suggested_actions: list[str] = Field(default_factory=list)


@dataclass
class QueryContextPage:
    slug: str
    title: str
    summary: str
    markdown_excerpt: str


class LLMProvider(Protocol):
    def compile_document(self, title_hint: str | None, raw_text: str) -> CompileDocumentResult: ...

    def answer_question(
        self, question: str, pages: list[QueryContextPage]
    ) -> QueryAnswerResult: ...


class HeuristicLLMProvider:
    def compile_document(self, title_hint: str | None, raw_text: str) -> CompileDocumentResult:
        title = title_hint or self._infer_title(raw_text)
        tags = extract_keywords(raw_text)
        summary = summarize_text(raw_text)
        page_type = self._infer_page_type(tags)
        key_points = sentence_split(raw_text)[:5]
        open_questions = self._infer_open_questions(raw_text)
        return CompileDocumentResult(
            title=title,
            summary=summary,
            tags=tags,
            page_type=page_type,
            key_points=key_points,
            open_questions=open_questions,
        )

    def answer_question(self, question: str, pages: list[QueryContextPage]) -> QueryAnswerResult:
        if not pages:
            return QueryAnswerResult(
                answer=(
                    "The current knowledge base does not have enough material to answer this yet. "
                    "Ingest a related source or run another compilation pass."
                ),
                suggested_actions=[
                    "Ingest at least one relevant source",
                    "Run compile on new raw documents",
                ],
            )

        lines = ["Based on the current knowledge base:"]
        for page in pages:
            lines.append(f"- {page.title}: {page.summary}")

        suggested_actions: list[str] = []
        if len(pages) < 3:
            suggested_actions.append("Add more sources to improve coverage for this topic")

        return QueryAnswerResult(
            answer="\n".join(lines),
            cited_slugs=[page.slug for page in pages],
            suggested_actions=suggested_actions,
        )

    def _infer_title(self, text: str) -> str:
        sentences = sentence_split(text)
        if not sentences:
            return "Untitled Raw Document"
        return sentences[0][:120]

    def _infer_page_type(self, tags: list[str]) -> str:
        if any(tag in {"person", "researcher", "founder"} for tag in tags):
            return "person"
        if any(tag in {"paper", "study", "benchmark"} for tag in tags):
            return "paper"
        return "topic"

    def _infer_open_questions(self, raw_text: str) -> list[str]:
        if "?" in raw_text:
            return [part.strip() for part in raw_text.split("?") if part.strip()][:3]
        return [
            "What additional sources would deepen this topic?",
            "Which related concepts should be linked next?",
        ]


class OpenAILLMProvider:
    def __init__(self, settings: Settings) -> None:
        from openai import OpenAI

        if not settings.openai_api_key:
            raise ValueError("OPENAI_API_KEY is missing")

        self.model = settings.openai_model
        self.client = OpenAI(api_key=settings.openai_api_key)

    def compile_document(self, title_hint: str | None, raw_text: str) -> CompileDocumentResult:
        prompt = (
            "You are compiling a living knowledge base page from a raw source. "
            "Produce a compact but information-dense structured summary. "
            "Prefer stable technical language, avoid hype, and keep tags short."
        )
        title_line = title_hint or "No title provided"
        response = self.client.responses.parse(
            model=self.model,
            input=[
                {"role": "system", "content": prompt},
                {
                    "role": "user",
                    "content": (
                        f"Title hint: {title_line}\n\n"
                        "Create a knowledge page draft from the following raw material:\n\n"
                        f"{raw_text[:120000]}"
                    ),
                },
            ],
            text_format=CompileDocumentResult,
        )
        return response.output_parsed

    def answer_question(self, question: str, pages: list[QueryContextPage]) -> QueryAnswerResult:
        context_blocks = []
        for page in pages:
            context_blocks.append(
                "\n".join(
                    [
                        f"slug: {page.slug}",
                        f"title: {page.title}",
                        f"summary: {page.summary}",
                        f"excerpt: {page.markdown_excerpt[:1600]}",
                    ]
                )
            )

        response = self.client.responses.parse(
            model=self.model,
            input=[
                {
                    "role": "system",
                    "content": (
                        "You answer questions using only the supplied knowledge-base context. "
                        "If evidence is weak, say so clearly. Cite by returning matching page slugs."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Question:\n{question}\n\n"
                        "Knowledge pages:\n\n"
                        + "\n\n---\n\n".join(context_blocks)
                    ),
                },
            ],
            text_format=QueryAnswerResult,
        )
        return response.output_parsed


class MiniMaxLLMProvider:
    def __init__(self, settings: Settings) -> None:
        from openai import OpenAI

        if not settings.minimax_api_key:
            raise ValueError("MINIMAX_API_KEY is missing")

        self.model = settings.minimax_model
        self.client = OpenAI(
            api_key=settings.minimax_api_key,
            base_url=settings.minimax_base_url,
        )

    def compile_document(self, title_hint: str | None, raw_text: str) -> CompileDocumentResult:
        title_line = title_hint or "No title provided"
        content = self._complete(
            system_prompt=(
                "You compile a living knowledge base page from raw source material. "
                "Return only valid JSON with keys: title, summary, tags, page_type, key_points, open_questions. "
                "Keep tags short, technical, and lowercase. Avoid markdown and commentary outside JSON."
            ),
            user_prompt=(
                f"Title hint: {title_line}\n\n"
                "Create a knowledge page draft from the following raw material:\n\n"
                f"{raw_text[:120000]}"
            ),
        )
        return CompileDocumentResult.model_validate(self._extract_json(content))

    def answer_question(self, question: str, pages: list[QueryContextPage]) -> QueryAnswerResult:
        context_blocks = []
        for page in pages:
            context_blocks.append(
                "\n".join(
                    [
                        f"slug: {page.slug}",
                        f"title: {page.title}",
                        f"summary: {page.summary}",
                        f"excerpt: {page.markdown_excerpt[:1600]}",
                    ]
                )
            )

        content = self._complete(
            system_prompt=(
                "You answer questions using only the supplied knowledge-base context. "
                "Return only valid JSON with keys: answer, cited_slugs, suggested_actions. "
                "If evidence is weak, say so clearly in answer."
            ),
            user_prompt=(
                f"Question:\n{question}\n\n"
                "Knowledge pages:\n\n"
                + "\n\n---\n\n".join(context_blocks)
            ),
        )
        return QueryAnswerResult.model_validate(self._extract_json(content))

    def _complete(self, system_prompt: str, user_prompt: str) -> str:
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.2,
        )
        content = response.choices[0].message.content or ""
        if not content.strip():
            raise ValueError("MiniMax returned empty content")
        return content

    def _extract_json(self, content: str) -> dict:
        content = content.strip()
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", content, re.DOTALL)
            if not match:
                raise ValueError("MiniMax response did not contain valid JSON") from None
            return json.loads(match.group(0))


def get_llm_provider(settings: Settings) -> LLMProvider:
    if settings.llm_provider.lower() == "openai" and settings.openai_api_key:
        try:
            return OpenAILLMProvider(settings)
        except Exception:
            return HeuristicLLMProvider()
    if settings.llm_provider.lower() == "minimax" and settings.minimax_api_key:
        try:
            return MiniMaxLLMProvider(settings)
        except Exception:
            return HeuristicLLMProvider()
    return HeuristicLLMProvider()


def describe_llm_provider(provider: LLMProvider) -> tuple[str, str]:
    if isinstance(provider, OpenAILLMProvider):
        return ("openai", provider.model)
    if isinstance(provider, MiniMaxLLMProvider):
        return ("minimax", provider.model)
    return ("heuristic", "local-heuristic")
