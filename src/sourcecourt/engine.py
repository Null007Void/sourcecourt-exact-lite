"""Bounded retrieval, navigation, extraction, and evidence verification core."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlsplit

from .contracts import AnswerResult, Evidence, ResultStatus
from .document import Document, Link, parse_document, rank_links
from .fetch import RetrievalError
from .model import ModelAdapter, ModelCandidate, NoModelAdapter
from .question import QuestionIntent, QuestionKind, interpret_question, relation_phrase


class Fetcher(Protocol):
    def fetch(self, url: str): ...


@dataclass(frozen=True)
class EngineLimits:
    max_pages: int = 3
    max_depth: int = 2
    max_links_per_page: int = 8
    same_origin_only: bool = True

    def __post_init__(self) -> None:
        if self.max_pages < 1 or self.max_depth < 0 or self.max_links_per_page < 1:
            raise ValueError("engine bounds must be positive")


@dataclass(frozen=True)
class RetrievalBundle:
    intent: QuestionIntent
    documents: tuple[Document, ...]
    errors: tuple[str, ...]


@dataclass(frozen=True)
class _Candidate:
    score: int
    source_url: str
    quote: str


_WORD = re.compile(r"[a-z0-9]+(?:[-'][a-z0-9]+)*")
_DATE = re.compile(
    r"\b(?:january|february|march|april|may|june|july|august|september|october|november|december)\s+\d{1,2}(?:,\s*\d{4})?\b|\b\d{4}-\d{2}-\d{2}\b",
    re.IGNORECASE,
)
_NUMBER = re.compile(r"\b\d+(?:[.,]\d+)?\b")
_MONEY = re.compile(r"(?:[$€£]\s*\d|\b\d+(?:[.,]\d+)?\s*(?:usd|dollars?|euros?|pounds?)\b)", re.IGNORECASE)

# Identifier-like value shapes for typed questions. Each pattern must match the
# whole value and nothing contextually wrong: "3.5" is not a domain, "1.1.0" is
# not a domain, "1,000" is not a port.
_VALUE_PATTERNS: dict[str, re.Pattern[str]] = {
    "domain": re.compile(
        r"\b[a-z0-9](?:[a-z0-9-]*[a-z0-9])?(?:\.[a-z0-9-]+)*\.[a-z]{2,}\b"  # host.example
        r"|\B\.[a-z]{2,}\b",  # bare TLD written as ".test"
        re.IGNORECASE,
    ),
    # A port is a 1-5 digit number that is not a fragment of something else:
    # not preceded by a digit, dot, comma or sign (so "1.1.0", "3.5", "1,000"
    # and "-8443" are excluded), not followed by a digit or percent sign, not
    # followed by a decimal continuation, and not followed by a thousands
    # group. Ordinary sentence punctuation (".", ",", ";", ")", end of
    # sentence) is allowed — "the server port is 8443." is a port, "8443%",
    # "-8443" and "−8443" are not.
    "port": re.compile(
        r"(?<![\d.,+\u2212-])\d{1,5}(?![\d%])(?!\.\d)(?!,\d{3})"
    ),
    "version": re.compile(r"\bv?\d+\.\d+(?:\.\d+)*\b", re.IGNORECASE),
    "percentage": re.compile(r"\b\d+(?:[.,]\d+)?\s?%", re.IGNORECASE),
}

# Function words a relation phrase may absorb: "for use in testing" matches the
# relation "for testing", while "for use in local testing" does not, because
# "local" is a content word.
_RELATION_FILLER = (
    "the|a|an|use|used|using|of|in|on|to|as|with|by"
)

# Value shapes that cannot identify themselves need the passage to be about
# that kind of value ("port 8443", "version 1.1.0"). Dotted names, versions and
# percentages are self-identifying and need no anchor.
_VALUE_ANCHORS: dict[str, tuple[str, ...]] = {
    "port": ("port", "ports"),
    "version": ("version", "versions", "release"),
    "domain": (),
    "percentage": (),
}


def _relation_pattern(intent: QuestionIntent) -> re.Pattern[str] | None:
    relation = relation_phrase(intent.normalized)
    if relation is None:
        return None
    preposition, term = relation
    words = [re.escape(word) for word in term.split()]
    filler = r"(?:\b(?:" + _RELATION_FILLER + r")\s+){0,3}"
    body = r"\s+".join(words)
    return re.compile(rf"\b{re.escape(preposition)}\s+{filler}{body}\b", re.IGNORECASE)


def _typed_values(kind: str, sentence: str) -> tuple[str, ...]:
    """Distinct identifier-like values of ``kind`` occurring in ``sentence``."""
    pattern = _VALUE_PATTERNS[kind]
    values: list[str] = []
    for match in pattern.finditer(sentence):
        value = match.group(0).strip()
        if kind == "port":
            digits = value.replace(",", "")
            if not digits.isdigit() or not 1 <= int(digits) <= 65535:
                continue
        if value.casefold() not in {existing.casefold() for existing in values}:
            values.append(value)
    return tuple(values)


@dataclass(frozen=True)
class _ValueCandidate:
    score: int
    source_url: str
    quote: str
    values: tuple[str, ...]


def _typed_candidates(
    intent: QuestionIntent, documents: tuple[Document, ...]
) -> list[_ValueCandidate]:
    relation = _relation_pattern(intent)
    anchors = _VALUE_ANCHORS.get(intent.value_type or "", ())
    candidates: list[_ValueCandidate] = []
    for document in documents:
        for sentence in document.sentences:
            values = _typed_values(intent.value_type, sentence)
            if not values:
                continue
            words = set(_WORD.findall(sentence.lower()))
            # A bare number is not a port unless the passage is about ports: a
            # page full of figures must not answer "which port?" with the first
            # number it happens to contain. Shapes that identify themselves
            # (dotted names, "1.1.0", "99.95%") need no anchor word.
            if anchors and not (words & set(anchors)):
                continue
            hits = len(set(intent.keywords) & words)
            relation_hit = bool(relation and relation.search(sentence))
            if not hits and not relation_hit:
                continue
            score = hits * 10 + (30 if relation_hit else 0)
            candidates.append(_ValueCandidate(score, document.url, sentence, values))
    return sorted(candidates, key=lambda item: (-item.score, item.source_url, item.quote))



def _normalized(value: str) -> str:
    return " ".join(value.split())


def verify_model_candidate(candidate: ModelCandidate, documents: tuple[Document, ...]) -> bool:
    if not candidate.answer.strip() or not candidate.evidence_quote.strip():
        return False
    for document in documents:
        if document.url != candidate.source_url:
            continue
        quote = _normalized(candidate.evidence_quote)
        text = _normalized(document.text)
        return quote in text and _normalized(candidate.answer) in quote
    return False


def _link_overlap(intent: QuestionIntent, link: Link) -> int:
    words = set(_WORD.findall(f"{link.text} {urlsplit(link.url).path}".lower()))
    return len(set(intent.keywords) & words)


def _sentence_score(intent: QuestionIntent, sentence: str) -> int:
    words = set(_WORD.findall(sentence.lower()))
    overlap = len(set(intent.keywords) & words)
    required = min(2, len(intent.keywords))
    if overlap < required:
        return 0
    cue = 0
    if intent.kind is QuestionKind.WHEN:
        if not _DATE.search(sentence):
            return 0
        cue = 3
    elif intent.kind is QuestionKind.HOW_MANY:
        if not _NUMBER.search(sentence):
            return 0
        cue = 3
    elif intent.kind is QuestionKind.HOW_MUCH:
        if not _MONEY.search(sentence):
            return 0
        cue = 3
    elif intent.kind in {QuestionKind.WHO, QuestionKind.WHERE}:
        cue = 1
    return overlap * 10 + cue


def _deterministic_candidates(intent: QuestionIntent, documents: tuple[Document, ...]) -> list[_Candidate]:
    candidates: list[_Candidate] = []
    for document in documents:
        for sentence in document.sentences:
            score = _sentence_score(intent, sentence)
            if score:
                candidates.append(_Candidate(score, document.url, sentence))
    return sorted(candidates, key=lambda item: (-item.score, item.source_url, item.quote))


class RetrievalEngine:
    def __init__(
        self,
        fetcher: Fetcher,
        *,
        model: ModelAdapter | None = None,
        limits: EngineLimits | None = None,
    ):
        self.fetcher = fetcher
        self.model = model or NoModelAdapter()
        self.limits = limits or EngineLimits()

    def retrieve(self, question: str, start_url: str) -> RetrievalBundle:
        intent = interpret_question(question)
        documents: list[Document] = []
        errors: list[str] = []
        queued: list[tuple[str, int]] = [(start_url, 0)]
        queued_urls = {start_url}
        visited_requests: set[str] = set()
        origin = None

        while queued and len(documents) < self.limits.max_pages:
            url, depth = queued.pop(0)
            if url in visited_requests:
                continue
            visited_requests.add(url)
            try:
                page = self.fetcher.fetch(url)
            except RetrievalError as exc:
                errors.append(f"{url}: {exc}")
                continue
            try:
                document = parse_document(page.final_url, page.text)
            except (ValueError, UnicodeError) as exc:
                # Defensive: retrieved content must never turn a valid question
                # into a user-input error. Treat an unparseable page as a
                # retrieval problem for that page only.
                errors.append(f"{url}: unparseable retrieved content ({type(exc).__name__})")
                continue
            documents.append(document)
            if origin is None:
                parsed = urlsplit(page.final_url)
                origin = (parsed.scheme.lower(), parsed.hostname, parsed.port)
            if depth >= self.limits.max_depth:
                continue
            ranked = rank_links(intent, document.links)
            added = 0
            for link in ranked:
                if _link_overlap(intent, link) == 0:
                    continue
                try:
                    parsed = urlsplit(link.url)
                    link_origin = (parsed.scheme.lower(), parsed.hostname, parsed.port)
                except (ValueError, UnicodeError):
                    # A retrieved link with an unusable host or port is skipped,
                    # never fatal to the answer being assembled.
                    continue
                if self.limits.same_origin_only and link_origin != origin:
                    continue
                if link.url not in queued_urls and link.url not in visited_requests:
                    queued.append((link.url, depth + 1))
                    queued_urls.add(link.url)
                    added += 1
                    if added >= self.limits.max_links_per_page:
                        break

        return RetrievalBundle(intent, tuple(documents), tuple(errors))

    def answer(self, question: str, start_url: str) -> AnswerResult:
        try:
            bundle = self.retrieve(question, start_url)
        except (TypeError, ValueError) as exc:
            return AnswerResult(ResultStatus.INVALID_INPUT, diagnostic=str(exc))

        visited = tuple(document.url for document in bundle.documents)
        if not bundle.documents:
            diagnostic = bundle.errors[0] if bundle.errors else "no page was retrieved"
            return AnswerResult(ResultStatus.RETRIEVAL_FAILED, visited_urls=visited, diagnostic=diagnostic)

        try:
            model_candidate = self.model.extract(bundle.intent, bundle.documents)
        except Exception as exc:
            model_candidate = None
            model_diagnostic = f"model adapter failed: {type(exc).__name__}"
        else:
            model_diagnostic = None

        if model_candidate is not None and verify_model_candidate(model_candidate, bundle.documents):
            evidence = Evidence(model_candidate.source_url, _normalized(model_candidate.evidence_quote))
            return AnswerResult(
                ResultStatus.ANSWERED,
                answer=_normalized(model_candidate.answer),
                source_url=model_candidate.source_url,
                evidence=(evidence,),
                visited_urls=visited,
            )

        if bundle.intent.value_type is not None:
            return self._answer_typed(bundle.intent, bundle.documents, visited)

        candidates = _deterministic_candidates(bundle.intent, bundle.documents)
        if not candidates:
            diagnostic_parts = ["no retrieved sentence sufficiently supports an answer"]
            if model_candidate is not None:
                diagnostic_parts.append("model candidate failed source verification")
            if model_diagnostic:
                diagnostic_parts.append(model_diagnostic)
            if bundle.errors:
                diagnostic_parts.append(f"{len(bundle.errors)} bounded retrieval error(s)")
            return AnswerResult(
                ResultStatus.UNSUPPORTED,
                visited_urls=visited,
                diagnostic="; ".join(diagnostic_parts),
            )

        top_score = candidates[0].score
        top: list[_Candidate] = []
        seen_quotes: set[str] = set()
        for candidate in candidates:
            if candidate.score != top_score:
                break
            normalized_quote = _normalized(candidate.quote).casefold()
            if normalized_quote not in seen_quotes:
                seen_quotes.add(normalized_quote)
                top.append(candidate)
        if len(top) > 1:
            evidence = tuple(Evidence(item.source_url, item.quote) for item in top)
            return AnswerResult(
                ResultStatus.AMBIGUOUS,
                evidence=evidence,
                visited_urls=visited,
                diagnostic="multiple equally supported answers were retrieved",
            )

        selected = top[0]
        evidence = Evidence(selected.source_url, selected.quote)
        return AnswerResult(
            ResultStatus.ANSWERED,
            answer=selected.quote,
            source_url=selected.source_url,
            evidence=(evidence,),
            visited_urls=visited,
        )

    def _answer_typed(
        self,
        intent: QuestionIntent,
        documents: tuple[Document, ...],
        visited: tuple[str, ...],
    ) -> AnswerResult:
        """Answer an identifier-value question with the value, not the sentence.

        A typed question never falls back to a sentence answer: if no retrieved
        passage states a value of the expected shape, the result is a refusal.
        Answering "the passage that mentions ports" to "what is the port" would
        be exactly the kind of plausible-but-unsupported answer this product
        exists to avoid.
        """
        candidates = _typed_candidates(intent, documents)
        if not candidates:
            return AnswerResult(
                ResultStatus.UNSUPPORTED,
                visited_urls=visited,
                diagnostic=(
                    f"no retrieved passage states a {intent.value_type} value "
                    "that the question asks for"
                ),
            )

        top_score = candidates[0].score
        top: list[_ValueCandidate] = []
        seen_quotes: set[str] = set()
        for candidate in candidates:
            if candidate.score != top_score:
                break
            normalized_quote = _normalized(candidate.quote).casefold()
            if normalized_quote not in seen_quotes:
                seen_quotes.add(normalized_quote)
                top.append(candidate)

        if len(top) > 1:
            evidence = tuple(Evidence(item.source_url, item.quote) for item in top)
            return AnswerResult(
                ResultStatus.AMBIGUOUS,
                evidence=evidence,
                visited_urls=visited,
                diagnostic="multiple equally supported answers were retrieved",
            )

        selected = top[0]
        distinct = {value.casefold(): value for value in selected.values}
        # One distinct value in the winning passage -> answer with the value it
        # actually states. Several -> answer with the passage itself rather than
        # picking one at random.
        answer = next(iter(distinct.values())) if len(distinct) == 1 else selected.quote
        evidence = Evidence(selected.source_url, selected.quote)
        return AnswerResult(
            ResultStatus.ANSWERED,
            answer=answer,
            source_url=selected.source_url,
            evidence=(evidence,),
            visited_urls=visited,
        )
