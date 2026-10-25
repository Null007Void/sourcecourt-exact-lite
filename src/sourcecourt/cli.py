"""Command-line entry point for SourceCourt Exact Lite V1.1.

Usage:
  sourcecourt ask QUESTION START_URL [--json]

Exit codes (the only values this program produces):

  0  ANSWERED, or an explicit refusal (UNSUPPORTED / AMBIGUOUS)
  2  RETRIEVAL_FAILED, INVALID_INPUT, an unexpected error, or a usage error
     (argparse exits 2 before this function returns)

There is no exit code 1.
"""

from __future__ import annotations

import argparse
import json
import sys

from . import __version__
from .contracts import ResultStatus
from .engine import EngineLimits, RetrievalEngine
from .fetch import FetchLimits, HttpFetcher

_ANSWER_CODE = 0
_REFUSAL_CODE = 0
_FAILURE_CODE = 2

_EXIT_EPILOG = """\
exit codes:
  0  ANSWERED, or an explicit refusal (UNSUPPORTED / AMBIGUOUS)
  2  RETRIEVAL_FAILED, INVALID_INPUT, unexpected error, or usage error

Answer shape:
  Questions that ask for an identifier-like value (domain/TLD, port, version,
  percentage) are answered with that value when exactly one appears in the
  supporting passage; every other question is answered with the supporting
  sentence. Evidence always quotes the passage verbatim.
"""



def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sourcecourt",
        description=(
            "Bounded website question answering: retrieve a small, same-origin "
            "set of pages from a starting HTTPS URL and return a source-bound "
            "textual answer with quote evidence, or an explicit refusal."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=_EXIT_EPILOG,
    )
    parser.add_argument(
        "--version", action="version", version=f"sourcecourt {__version__}"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    ask = sub.add_parser(
        "ask",
        help="answer one natural-language question against one website",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=_EXIT_EPILOG,
    )
    ask.add_argument("question", help="natural-language question (max 500 characters)")
    ask.add_argument("start_url", help="absolute HTTPS URL of the starting page")
    ask.add_argument("--json", action="store_true", help="print the JSON result record")

    return parser


def _limits() -> tuple[FetchLimits, EngineLimits]:
    return FetchLimits(), EngineLimits()


def main(argv: list[str] | None = None, *, fetcher: HttpFetcher | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    fetch_limits, engine_limits = _limits()
    engine = RetrievalEngine(
        fetcher if fetcher is not None else HttpFetcher(fetch_limits),
        limits=engine_limits,
    )
    try:
        result = engine.answer(args.question, args.start_url)
    except Exception as exc:  # noqa: BLE001 - the CLI must never traceback
        payload = {
            "status": "UNEXPECTED_ERROR",
            "diagnostic": f"{type(exc).__name__}: {exc}",
        }
        print(json.dumps(payload, ensure_ascii=True, indent=2))
        return _FAILURE_CODE

    record = {
        "status": result.status.value,
        "answer": result.answer,
        "source_url": result.source_url,
        "evidence": [
            {"source_url": item.source_url, "quote": item.quote}
            for item in result.evidence
        ],
        "visited_urls": list(result.visited_urls),
        "diagnostic": result.diagnostic,
    }
    if args.json:
        print(json.dumps(record, ensure_ascii=True, indent=2))
    else:
        _print_human(record)

    if result.status is ResultStatus.ANSWERED:
        return _ANSWER_CODE
    if result.status in {ResultStatus.AMBIGUOUS, ResultStatus.UNSUPPORTED}:
        return _REFUSAL_CODE
    return _FAILURE_CODE


def _print_human(record: dict) -> None:
    print(f"status: {record['status']}")
    if record["answer"] is not None:
        print(f"answer: {record['answer']}")
        print(f"source: {record['source_url']}")
        if record["evidence"]:
            quote = record["evidence"][0]["quote"]
            print(f"evidence: {quote}")
    elif record["evidence"]:
        print("evidence candidates:")
        for item in record["evidence"]:
            print(f"  - {item['source_url']}: {item['quote']}")
    if record["diagnostic"]:
        print(f"diagnostic: {record['diagnostic']}")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())