import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from sourcecourt.contracts import ResultStatus
from sourcecourt.engine import EngineLimits, RetrievalEngine
from sourcecourt.fetch import FetchLimits, HttpFetcher


class SiteHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/":
            body = b"<html><body><a href='/facts'>Official SourceCourt launch details</a></body></html>"
            status = 200
        elif self.path == "/facts":
            body = b"<html><body><p>The SourceCourt launch date is October 27, 2026.</p></body></html>"
            status = 200
        else:
            body = b"not found"
            status = 404
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        return


class LocalHttpIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), SiteHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=1)

    def test_real_http_retrieval_navigation_extraction_and_source_binding(self):
        engine = RetrievalEngine(
            HttpFetcher.for_local_fixture_tests(
                FetchLimits(timeout_seconds=1, max_bytes=4096)
            ),
            limits=EngineLimits(max_pages=2, max_depth=1),
        )
        result = engine.answer("When is the SourceCourt launch date?", self.base + "/")
        self.assertEqual(result.status, ResultStatus.ANSWERED)
        self.assertEqual(result.source_url, self.base + "/facts")
        self.assertEqual(result.answer, "The SourceCourt launch date is October 27, 2026.")
        self.assertEqual(result.evidence[0].source_url, result.source_url)
        self.assertEqual(result.evidence[0].quote, result.answer)


if __name__ == "__main__":
    unittest.main()
