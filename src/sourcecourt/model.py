"""Provider-neutral model extraction interface.

Implementations may use AMD inference later, but this package makes no claim that
model inference is currently configured or verified.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .document import Document
from .question import QuestionIntent


@dataclass(frozen=True)
class ModelCandidate:
    answer: str
    source_url: str
    evidence_quote: str


class ModelAdapter(Protocol):
    name: str

    def extract(
        self, intent: QuestionIntent, documents: tuple[Document, ...]
    ) -> ModelCandidate | None:
        """Return a candidate answer, never release authority or an unverified result."""
        ...


class NoModelAdapter:
    """Default adapter: deterministic extraction only; no inference claim."""

    name = "none"

    def extract(self, intent: QuestionIntent, documents: tuple[Document, ...]) -> None:
        return None
