from __future__ import annotations

import hashlib
import math
from typing import Protocol

from living_kb.config import Settings
from living_kb.utils import tokenize


class EmbeddingProvider(Protocol):
    def embed_text(self, text: str) -> list[float]: ...


class DeterministicEmbeddingProvider:
    def __init__(self, dimensions: int) -> None:
        self.dimensions = dimensions

    def embed_text(self, text: str) -> list[float]:
        vector = [0.0] * self.dimensions
        tokens = tokenize(text) or ["empty"]
        for token in tokens:
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            bucket = int.from_bytes(digest[:4], "big") % self.dimensions
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vector[bucket] += sign
        return self._normalize(vector)

    def _normalize(self, vector: list[float]) -> list[float]:
        magnitude = math.sqrt(sum(value * value for value in vector)) or 1.0
        return [value / magnitude for value in vector]


class OpenAIEmbeddingProvider:
    def __init__(self, settings: Settings) -> None:
        from openai import OpenAI

        if not settings.openai_api_key:
            raise ValueError("OPENAI_API_KEY is missing")
        self.model = settings.openai_embedding_model
        self.client = OpenAI(api_key=settings.openai_api_key)

    def embed_text(self, text: str) -> list[float]:
        response = self.client.embeddings.create(
            model=self.model,
            input=text[:20000],
        )
        return list(response.data[0].embedding)


def get_embedding_provider(settings: Settings) -> EmbeddingProvider:
    mode = settings.embedding_provider.lower()
    if mode in {"openai", "auto"} and settings.openai_api_key:
        try:
            return OpenAIEmbeddingProvider(settings)
        except Exception:
            return DeterministicEmbeddingProvider(settings.embedding_dimensions)
    return DeterministicEmbeddingProvider(settings.embedding_dimensions)


def describe_embedding_provider(provider: EmbeddingProvider, settings: Settings) -> tuple[str, str]:
    if isinstance(provider, OpenAIEmbeddingProvider):
        return ("openai", settings.openai_embedding_model)
    return ("deterministic", f"local-hash-{settings.embedding_dimensions}")


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right:
        return 0.0
    return sum(l * r for l, r in zip(left, right))
