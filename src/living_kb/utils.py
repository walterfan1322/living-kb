from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from pathlib import Path


STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "has",
    "in",
    "is",
    "it",
    "of",
    "on",
    "or",
    "that",
    "the",
    "to",
    "was",
    "were",
    "with",
    "this",
    "these",
    "those",
    "their",
    "into",
    "about",
    "also",
}


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def slugify(text: str) -> str:
    lowered = text.lower().strip()
    lowered = re.sub(r"[^\w\s-]", "", lowered)
    lowered = re.sub(r"[-\s]+", "-", lowered)
    return lowered.strip("-") or "untitled"


def tokenize(text: str) -> list[str]:
    return [token.lower() for token in re.findall(r"\w+", text.lower()) if len(token) > 2]


def sentence_split(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?。！？])\s+", text.strip())
    return [part.strip() for part in parts if part.strip()]


def summarize_text(text: str, max_sentences: int = 3, max_chars: int = 600) -> str:
    sentences = sentence_split(text)
    summary = " ".join(sentences[:max_sentences]) if sentences else text[:max_chars]
    return summary[:max_chars].strip()


def extract_keywords(text: str, limit: int = 6) -> list[str]:
    tokens = [token for token in tokenize(text) if token not in STOPWORDS]
    counts = Counter(tokens)
    return [token for token, _ in counts.most_common(limit)]


def json_dumps(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2)


def json_loads(value: str | None, fallback: object) -> object:
    if not value:
        return fallback
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return fallback


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def jaccard_similarity(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    union = left | right
    if not union:
        return 0.0
    return len(left & right) / len(union)
