"""Product-mode acceptance tests for SourceCourt Exact Lite V1.

These tests exercise the product's public workflow using the exact mechanism
the documented fresh-install walkthrough uses: a loopback HTTP fixture site.
They validate the product claim within its supported mode of use and mirror
the security-review-isolated pattern already accepted in the engineering core
(HttpFetcher.for_local_fixture_tests accepts only literal loopback).

The private demo driver (demo/run_demo.py) additionally drives the real
production CLI entry point against these fixtures via subprocess.
"""

import io
import json
import sys
import threading
import unittest
from contextlib import redirect_stderr, redirect_stdout
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_PRODUCT = _HERE.parent
_SRC = _PRODUCT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import sourcecourt  # noqa: E402  (path setup must precede imports)
from sourcecourt.cli import main as cli_main  # noqa: E402
from sourcecourt.engine import EngineLimits, RetrievalEngine  # noqa: E402
from sourcecourt.fetch import FetchLimits, HttpFetcher  # noqa: E402


class _FixtureSiteHandler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802 - http.server API
        pages = {
            "/": (
                b"<html><body>"
                b"<a href='/about'>About SourceCourt</a>"
                b"<a href='/facts'>SourceCourt launch facts</a>"
                b"<a href='/unrelated'>Weather report</a>"
                b"</body></html>",
                200,
            ),
            "/about": (
                b"<html><body>"
                b"<p>About page.</p>"
                b"<a href='/facts'>SourceCourt launch facts</a>"
                b"</body></html>",
                200,
            ),
            "/facts": (
                b"<html><body>"
                b"<p>The SourceCourt launch date is October 27, 2026.</p>"
                b"</body></html>",
                200,
            ),
            "/unrelated": (
                b"<html><body>"
                b"<p>Today the weather is mild with light rain expected.</p>"
                b"</body></html>",
                200,
            ),
            "/conflict": (
                b"<html><body>"
                b"<a href='/a'>SourceCourt launch date notes</a>"
                b"<a href='/b'>SourceCourt launch date notes</a>"
                b"</body></html>",
                200,
            ),
            "/a": (
                b"<html><body>"
                b"<p>The SourceCourt launch date is October 27, 2026.</p>"
                b"</body></html>",
                200,
            ),
            "/b": (
                b"<html><body>"
                b"<p>The SourceCourt launch date is October 28, 2026.</p>"
                b"</body></html>",
                200,
            ),
        }
        body, status = pages.get(self.path, (b"not found", 404))
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):  # noqa: A002 - http.server API
        return


class _FixtureSite:
    def __init__(self):
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), _FixtureSiteHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def stop(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)


class ProductWorkflowTests(unittest.TestCase):
    """Engine-level workflow checks on the exact shipped surface."""

    @classmethod
    def setUpClass(cls):
        cls.site = _FixtureSite()

    @classmethod
    def tearDownClass(cls):
        cls.site.stop()

    def _engine(self, limits: EngineLimits | None = None) -> RetrievalEngine:
        return RetrievalEngine(
            HttpFetcher.for_local_fixture_tests(
                FetchLimits(timeout_seconds=5, max_bytes=200000)
            ),
            limits=limits,
        )

    def test_package_exports_public_contract(self):
        for name in (
            "RetrievalEngine",
            "EngineLimits",
            "HttpFetcher",
            "FetchLimits",
            "RetrievalError",
            "ResultStatus",
            "AnswerResult",
            "Evidence",
            "interpret_question",
            "__version__",
        ):
            self.assertTrue(hasattr(sourcecourt, name), name)
        self.assertEqual(sourcecourt.__version__, "1.1.2")

    def test_workflow_answers_two_hop_question(self):
        result = self._engine(EngineLimits(max_pages=3, max_depth=2)).answer(
            "When is the SourceCourt launch date?", self.site.base + "/about"
        )
        self.assertEqual(result.status, sourcecourt.ResultStatus.ANSWERED)
        self.assertEqual(result.answer, "The SourceCourt launch date is October 27, 2026.")
        self.assertEqual(result.source_url, self.site.base + "/facts")
        self.assertTrue(result.evidence)
        self.assertIn("October 27, 2026", result.evidence[0].quote)

    def test_workflow_refuses_unsupported_site(self):
        result = self._engine().answer("How many pages does the weather report have?", self.site.base + "/unrelated")
        self.assertIn(
            result.status,
            {sourcecourt.ResultStatus.UNSUPPORTED, sourcecourt.ResultStatus.RETRIEVAL_FAILED},
        )
        self.assertIsNone(result.answer)

    def test_workflow_refuses_offsite_question(self):
        result = self._engine(
            EngineLimits(max_pages=3, max_depth=2)
        ).answer(
            "What is the capital of France?", self.site.base + "/"
        )
        self.assertEqual(result.status, sourcecourt.ResultStatus.UNSUPPORTED)

    def test_workflow_flags_conflicting_pages_as_ambiguous(self):
        result = self._engine(EngineLimits(max_pages=3, max_depth=2)).answer(
            "When is the SourceCourt launch date?", self.site.base + "/conflict"
        )
        self.assertEqual(result.status, sourcecourt.ResultStatus.AMBIGUOUS)
        self.assertEqual(len(result.evidence), 2)

    def test_production_fetcher_preserves_ssrf_protection(self):
        fetcher = HttpFetcher()
        with self.assertRaises(sourcecourt.RetrievalError):
            fetcher.fetch("http://127.0.0.1:9/")

    def _fixture_fetcher(self):
        return HttpFetcher.for_local_fixture_tests(
            FetchLimits(timeout_seconds=5, max_bytes=200000)
        )

    def test_cli_ask_json_answers_via_public_entry_point(self):
        out, code = self._run_cli(
            ["ask", "When is the SourceCourt launch date?", self.site.base + "/facts", "--json"],
            fetcher=self._fixture_fetcher(),
        )
        self.assertEqual(code, 0, out)
        record = json.loads(out)
        self.assertEqual(record["status"], "ANSWERED")
        self.assertIn("October 27, 2026", record["answer"])
        self.assertEqual(record["source_url"], self.site.base + "/facts")

    def test_cli_ask_json_refuses_unsupported(self):
        out, code = self._run_cli(
            ["ask", "What is the capital of France?", self.site.base + "/", "--json"],
            fetcher=self._fixture_fetcher(),
        )
        self.assertEqual(code, 0, out)
        record = json.loads(out)
        self.assertEqual(record["status"], "UNSUPPORTED")
        self.assertIsNone(record["answer"])

    def test_cli_ask_json_reports_start_failure_with_exit_2(self):
        out, code = self._run_cli(
            ["ask", "When is the launch?", self.site.base + "/absent", "--json"],
            fetcher=self._fixture_fetcher(),
        )
        self.assertEqual(code, 2, out)
        record = json.loads(out)
        self.assertEqual(record["status"], "RETRIEVAL_FAILED")

    def test_cli_default_fetcher_refuses_loopback(self):
        """The unmodified production CLI path retains the SSRF guard."""
        out, code = self._run_cli(
            ["ask", "When is the launch?", self.site.base + "/facts", "--json"]
        )
        self.assertEqual(code, 2, out)
        record = json.loads(out)
        self.assertEqual(record["status"], "RETRIEVAL_FAILED")
        self.assertIn("non-public destination is forbidden", record["diagnostic"])

    def _run_cli(self, argv, fetcher=None):
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = cli_main(argv, fetcher=fetcher)
        return stdout.getvalue(), code


if __name__ == "__main__":
    unittest.main()