"""SourceCourt Exact Lite V1 - bounded website question answering.

Accepts a natural-language question plus a starting HTTPS URL, retrieves a
bounded set of pages from that website, and returns a status with a
source-bound textual answer and quote-level evidence, deliberately refusing
(UNSUPPORTED or AMBIGUOUS) instead of guessing when the pages do not support an
answer.

The retrieval and security core is byte-frozen at engineering checkpoint
M4-019G (45/45 warning-strict tests, independent local security review PASS).
V1.1.0 adds paragraph-aware text segmentation and typed value answers; the
security guarantees above are unchanged and re-verified.
"""

from __future__ import annotations

from .contracts import AnswerResult, Evidence, ResultStatus
from .document import Document, Link, parse_document, rank_links
from .engine import EngineLimits, RetrievalEngine, RetrievalBundle, verify_model_candidate
from .fetch import FetchLimits, HttpFetcher, RetrievedPage, RetrievalError
from .model import ModelAdapter, ModelCandidate, NoModelAdapter
from .question import QuestionIntent, QuestionKind, interpret_question

__version__ = "1.1.2"

__all__ = [
    "AnswerResult",
    "Document",
    "EngineLimits",
    "Evidence",
    "FetchLimits",
    "HttpFetcher",
    "Link",
    "ModelAdapter",
    "ModelCandidate",
    "NoModelAdapter",
    "QuestionIntent",
    "QuestionKind",
    "RetrievalBundle",
    "RetrievalEngine",
    "RetrievedPage",
    "ResultStatus",
    "RetrievalError",
    "interpret_question",
    "parse_document",
    "rank_links",
    "verify_model_candidate",
]
