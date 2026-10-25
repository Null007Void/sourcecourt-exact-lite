"""Small deterministic natural-language question interpreter."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum


class QuestionKind(str, Enum):
    WHO = "WHO"
    WHEN = "WHEN"
    WHERE = "WHERE"
    HOW_MANY = "HOW_MANY"
    HOW_MUCH = "HOW_MUCH"
    WHAT = "WHAT"
    GENERAL = "GENERAL"


@dataclass(frozen=True)
class QuestionIntent:
    original: str
    normalized: str
    kind: QuestionKind
    keywords: tuple[str, ...]
    value_type: str | None = None


_STOPWORDS = frozenset({
    "a", "an", "and", "are", "at", "be", "by", "for", "from", "in", "is",
    "it", "of", "on", "or", "the", "to", "was", "were", "what", "when",
    "where", "which", "who", "why", "how", "many", "much", "does", "do",
})
_WORD = re.compile(r"[a-z0-9]+(?:[-'][a-z0-9]+)*")

# Nouns whose question expects one identifier-like value rather than a whole
# supporting sentence. This is a small, closed, documented lexicon: it is a
# product contract, not a per-question special case. Anything not listed here
# keeps the V1.0 sentence-answer behaviour.
_VALUE_NOUNS = {
    "domain": "domain",
    "host": "domain",
    "hosts": "domain",
    "hostname": "domain",
    "hostnames": "domain",
    "domains": "domain",
    "tld": "domain",
    "tlds": "domain",
    "suffix": "domain",
    "suffixes": "domain",
    "extension": "domain",
    "extensions": "domain",
    "port": "port",
    "ports": "port",
    "version": "version",
    "versions": "version",
    "percentage": "percentage",
    "percent": "percentage",
}

# Prepositions that introduce the condition a value must satisfy
# ("the top-level domain *for testing*"). The trailing phrase is used by the
# engine as a relevance signal, never as a hardcoded answer.
_RELATION_PREPOSITIONS = ("for", "in", "on", "to", "of", "at", "with", "by")
_RELATION_MAX_TERM_WORDS = 3


def value_type_for(keywords: tuple[str, ...]) -> str | None:
    for keyword in keywords:
        kind = _VALUE_NOUNS.get(keyword)
        if kind is not None:
            return kind
    return None


def relation_phrase(normalized: str) -> tuple[str, str] | None:
    """Return ``(preposition, term)`` for the question's final prepositional phrase.

    ``"what is the top level domain for testing"`` -> ``("for", "testing")``.
    The term keeps question words in order, drops stopwords, and returns
    ``None`` when there is no usable term.
    """
    cleaned = normalized.strip().rstrip("?.! ").strip()
    if not cleaned:
        return None
    tokens = cleaned.split()
    for index in range(len(tokens) - 1, 0, -1):
        if tokens[index] in _RELATION_PREPOSITIONS:
            term_words = [word for word in tokens[index + 1 :] if word not in _STOPWORDS]
            if not term_words:
                return None
            if len(term_words) > _RELATION_MAX_TERM_WORDS:
                term_words = term_words[:_RELATION_MAX_TERM_WORDS]
            return tokens[index], " ".join(term_words)
    return None



def interpret_question(question: str, *, max_length: int = 500) -> QuestionIntent:
    if not isinstance(question, str):
        raise TypeError("question must be a string")
    if not question.strip():
        raise ValueError("question must not be blank")
    if len(question) > max_length:
        raise ValueError("question exceeds maximum length")
    if any(ord(char) < 32 and char not in "\t\r\n" for char in question):
        raise ValueError("question contains forbidden control characters")

    normalized = " ".join(question.lower().split())
    if normalized.startswith("how many "):
        kind = QuestionKind.HOW_MANY
    elif normalized.startswith("how much "):
        kind = QuestionKind.HOW_MUCH
    elif normalized.startswith("who "):
        kind = QuestionKind.WHO
    elif normalized.startswith("when "):
        kind = QuestionKind.WHEN
    elif normalized.startswith("where "):
        kind = QuestionKind.WHERE
    elif normalized.startswith(("what ", "which ")):
        kind = QuestionKind.WHAT
    else:
        kind = QuestionKind.GENERAL

    keywords = tuple(word for word in _WORD.findall(normalized) if word not in _STOPWORDS)
    if not keywords:
        raise ValueError("question has no meaningful terms")
    return QuestionIntent(
        question,
        normalized,
        kind,
        keywords,
        value_type_for(keywords),
    )
