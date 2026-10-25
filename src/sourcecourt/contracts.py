"""Internal, competition-contract-independent result types."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ResultStatus(str, Enum):
    ANSWERED = "ANSWERED"
    AMBIGUOUS = "AMBIGUOUS"
    UNSUPPORTED = "UNSUPPORTED"
    RETRIEVAL_FAILED = "RETRIEVAL_FAILED"
    INVALID_INPUT = "INVALID_INPUT"


@dataclass(frozen=True)
class Evidence:
    source_url: str
    quote: str

    def __post_init__(self) -> None:
        if not self.source_url or not self.quote.strip():
            raise ValueError("evidence requires a source URL and non-blank quote")


@dataclass(frozen=True)
class AnswerResult:
    status: ResultStatus
    answer: str | None = None
    source_url: str | None = None
    evidence: tuple[Evidence, ...] = ()
    visited_urls: tuple[str, ...] = ()
    diagnostic: str | None = None

    def __post_init__(self) -> None:
        if self.status is ResultStatus.ANSWERED:
            if not self.answer or not self.source_url or not self.evidence:
                raise ValueError("answered results require answer, source URL, and evidence")
            if any(item.source_url != self.source_url for item in self.evidence):
                raise ValueError("answered evidence must belong to the selected source URL")
        elif self.answer is not None:
            raise ValueError("non-answered results cannot contain an answer")
