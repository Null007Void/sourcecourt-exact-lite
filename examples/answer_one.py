"""Minimal end-user example: ask one question against one website.

Run with an installed product (fresh venv, wheel install):
    python examples/answer_one.py

Note: production installs reach only public HTTPS sites. To try the
local loopback fixture used by the automated tests, see tests/ and
demo/run_demo.py.
"""

from __future__ import annotations

import json
import sys

from sourcecourt import RetrievalEngine, HttpFetcher


def main() -> int:
    question = " ".join(sys.argv[1:-1])
    start_url = sys.argv[-1] if len(sys.argv) > 2 else "https://example.com/"
    question = question or "What is this website about?"
    engine = RetrievalEngine(HttpFetcher())
    result = engine.answer(question, start_url)
    print(json.dumps({
        "status": result.status.value,
        "answer": result.answer,
        "source_url": result.source_url,
        "evidence": [e.quote for e in result.evidence],
        "visited_urls": list(result.visited_urls),
        "diagnostic": result.diagnostic,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())