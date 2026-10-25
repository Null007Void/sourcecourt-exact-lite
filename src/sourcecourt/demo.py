"""Shipped demo: run the full question-answering workflow on a local fixture.

This is a DEMO entry point, clearly separated from the production CLI. It
starts a temporary loopback HTTP fixture site and runs the production
`sourcecourt.cli.main` entry point against it through the documented
test-and-demo fetcher seam (production fetchers refuse loopback by the
accepted SSRF design). The production claim that this package makes —
source-bound answers from real, reachable HTTP/HTTPS sites — is exercised by
the `sourcecourt ask` command itself, not by this demo.

Runs entirely offline. Exit 0 on completion.
"""

from __future__ import annotations

import threading
from contextlib import redirect_stdout
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import StringIO

from . import EngineLimits, FetchLimits, HttpFetcher, RetrievalEngine
from .cli import main as cli_main

_PAGES = {
    "/": (
        b"<html><body><h1>SourceCourt Demo Site</h1>"
        b"<a href='/facts'>SourceCourt launch facts</a>"
        b"<a href='/unrelated'>Weather report</a></body></html>",
        200,
    ),
    "/facts": (
        b"<html><body><p>The SourceCourt launch date is October 27, 2026.</p>"
        b"</body></html>",
        200,
    ),
    "/unrelated": (
        b"<html><body><p>Mild weather today with light rain expected.</p>"
        b"</body></html>",
        200,
    ),
}


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802 - http.server API
        body, status = _PAGES.get(self.path, (b"not found", 404))
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):  # noqa: A002 - http.server API
        return


def _fixture_fetcher() -> HttpFetcher:
    return HttpFetcher.for_local_fixture_tests(
        FetchLimits(timeout_seconds=5, max_bytes=200000)
    )


def main() -> int:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        engine = RetrievalEngine(
            _fixture_fetcher(), limits=EngineLimits(max_pages=3, max_depth=2)
        )
        direct = engine.answer("When is the SourceCourt launch date?", base + "/facts")
        print("== installed API demo (engine.answer) ==")
        print("status:", direct.status.value)
        print("answer:", direct.answer)
        print("source:", direct.source_url)
        print()

        for label, argv, fetcher in [
            ("CLI ask (shipped entry point, demo seam)", ["ask", "When is the SourceCourt launch date?", base + "/facts"], _fixture_fetcher()),
            ("CLI refused answer (site lacks the fact)", ["ask", "What is the capital of France?", base + "/unrelated"], _fixture_fetcher()),
        ]:
            buffer = StringIO()
            with redirect_stdout(buffer):
                code = cli_main(argv, fetcher=fetcher)
            print(f"== {label} == exit {code}")
            print(buffer.getvalue().strip())
            print()

        final = engine.answer("When is the SourceCourt launch date?", base + "/facts")
        ok = final.status.value == "ANSWERED" and "October 27, 2026" in (final.answer or "")
        print("DEMO COMPLETE:", "ANSWERED end-to-end confirmed" if ok else "FAILED")
        return 0 if ok else 1
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


if __name__ == "__main__":
    raise SystemExit(main())