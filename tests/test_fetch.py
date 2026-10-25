import os
import socket
import sys
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from sourcecourt.fetch import FetchLimits, HttpFetcher, RetrievalError


class FixtureHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/slow-headers":
            parts = (
                b"HTTP/1.1 200 OK\r\n",
                b"Content-Type: text/plain; charset=utf-8\r\n",
                b"Content-Length: 2\r\n",
                b"Connection: close\r\n",
                b"\r\n",
            )
            try:
                for part in parts:
                    self.wfile.write(part)
                    self.wfile.flush()
                    time.sleep(0.09)
                self.wfile.write(b"ok")
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass
            return
        if self.path == "/drip":
            body = b"abcde"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            try:
                for byte in body:
                    self.wfile.write(bytes((byte,)))
                    self.wfile.flush()
                    time.sleep(0.04)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass
            return
        if self.path == "/ok":
            body = b"<html><body><h1>Facts</h1><p>Launch date: October 27, 2026.</p></body></html>"
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
        elif self.path == "/empty":
            body = b""
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
        elif self.path == "/large":
            body = b"x" * 300
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
        elif self.path == "/binary":
            body = b"\x00\x01"
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
        elif self.path == "/malformed":
            body = b"\xff\xfe"
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
        elif self.path == "/slow":
            time.sleep(0.2)
            body = b"late"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
        elif self.path == "/redirect":
            body = b""
            self.send_response(302)
            self.send_header("Location", "/ok")
        elif self.path == "/redirect-private":
            body = b""
            self.send_response(302)
            self.send_header("Location", "http://10.0.0.1/secret")
        elif self.path == "/slow-redirect-1":
            time.sleep(0.06)
            body = b""
            self.send_response(302)
            self.send_header("Location", "/slow-redirect-2")
        elif self.path == "/slow-redirect-2":
            time.sleep(0.06)
            body = b""
            self.send_response(302)
            self.send_header("Location", "/ok")
        elif self.path == "/redirect-long":
            body = b""
            self.send_response(302)
            self.send_header("Location", "/" + "a" * 2100)
        elif self.path.startswith("/" + "a" * 2100):
            body = b"long redirect accepted"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
        else:
            body = b"missing"
            self.send_response(404)
            self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass

    def log_message(self, format, *args):
        return


class CloseTrackingSocket:
    def __init__(self, wrapped=None):
        self.wrapped = wrapped
        self.close_count = 0

    def __getattr__(self, name):
        if self.wrapped is None:
            raise AttributeError(name)
        return getattr(self.wrapped, name)

    def close(self):
        self.close_count += 1
        if self.wrapped is not None:
            self.wrapped.close()


class HttpFetcherTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), FixtureHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=1)

    def test_fetches_http_text_with_bounded_metadata(self):
        page = HttpFetcher.for_local_fixture_tests().fetch(self.base + "/ok")
        self.assertEqual(page.status_code, 200)
        self.assertEqual(page.final_url, self.base + "/ok")
        self.assertIn("Launch date", page.text)
        self.assertEqual(page.content_type, "text/html")

    def test_accepts_empty_declared_text_body(self):
        page = HttpFetcher.for_local_fixture_tests().fetch(self.base + "/empty")
        self.assertEqual(page.text, "")

    def test_follows_bounded_redirect(self):
        page = HttpFetcher.for_local_fixture_tests(
            FetchLimits(max_redirects=1)
        ).fetch(self.base + "/redirect")
        self.assertEqual(page.final_url, self.base + "/ok")

    def test_production_fetcher_blocks_non_public_destinations(self):
        blocked = (
            "http://127.0.0.1/",
            "http://10.0.0.1/",
            "http://169.254.169.254/latest/meta-data/",
            "http://0.0.0.0/",
            "http://224.0.0.1/",
            "http://192.0.2.1/",
            "http://[::1]/",
        )
        for url in blocked:
            with self.subTest(url=url), self.assertRaisesRegex(
                RetrievalError, "non-public"
            ):
                HttpFetcher().fetch(url)

    def test_dns_resolution_rejects_mixed_public_and_private_answers(self):
        answers = [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 80)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 80)),
        ]
        with patch("sourcecourt.fetch.socket.getaddrinfo", return_value=answers):
            with self.assertRaisesRegex(RetrievalError, "non-public"):
                HttpFetcher(FetchLimits(timeout_seconds=0.1)).fetch(
                    "http://public.example/"
                )

    def test_overall_deadline_bounds_dns_resolution(self):
        answers = [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 80)),
        ]

        def slow_resolution(*args, **kwargs):
            time.sleep(0.2)
            return answers

        started = time.monotonic()
        with patch(
            "sourcecourt.fetch.socket.getaddrinfo", side_effect=slow_resolution
        ), patch("sourcecourt.fetch._connect_pinned") as connector:
            with self.assertRaisesRegex(RetrievalError, "timed out"):
                HttpFetcher(FetchLimits(timeout_seconds=0.05)).fetch(
                    "http://public.example/"
                )
        self.assertLess(time.monotonic() - started, 0.15)
        connector.assert_not_called()

    def test_connected_socket_closes_if_deadline_expires_before_connection_owns_it(self):
        connected_socket = CloseTrackingSocket()
        with patch(
            "sourcecourt.fetch._connect_pinned", return_value=connected_socket
        ), patch(
            "sourcecourt.fetch._remaining",
            side_effect=[1.0, RetrievalError("retrieval timed out")],
        ):
            with self.assertRaisesRegex(RetrievalError, "timed out"):
                HttpFetcher.for_local_fixture_tests().fetch(self.base + "/ok")
        self.assertEqual(connected_socket.close_count, 1)

    def test_connected_socket_closes_if_http_connection_initialization_raises(self):
        connected_socket = CloseTrackingSocket()
        with patch(
            "sourcecourt.fetch._connect_pinned", return_value=connected_socket
        ), patch(
            "sourcecourt.fetch.http.client.HTTPConnection",
            side_effect=OSError("construction failed"),
        ):
            with self.assertRaisesRegex(RetrievalError, "construction failed"):
                HttpFetcher.for_local_fixture_tests().fetch(self.base + "/ok")
        self.assertEqual(connected_socket.close_count, 1)

    def test_connected_sockets_close_once_after_normal_and_redirect_responses(self):
        from sourcecourt.fetch import _connect_pinned

        for path, expected_connections in (("/ok", 1), ("/redirect", 2)):
            tracked_sockets = []

            def connect_and_track(*args, **kwargs):
                tracked = CloseTrackingSocket(_connect_pinned(*args, **kwargs))
                tracked_sockets.append(tracked)
                return tracked

            with self.subTest(path=path), patch(
                "sourcecourt.fetch._connect_pinned", side_effect=connect_and_track
            ):
                page = HttpFetcher.for_local_fixture_tests(
                    FetchLimits(max_redirects=1)
                ).fetch(self.base + path)
            self.assertEqual(page.status_code, 200)
            self.assertEqual(len(tracked_sockets), expected_connections)
            self.assertEqual(
                [tracked.close_count for tracked in tracked_sockets],
                [1] * expected_connections,
            )

    def test_deadline_socket_defers_and_deduplicates_close_while_reader_owns_it(self):
        from sourcecourt.fetch import _DeadlineSocket

        connected_socket = CloseTrackingSocket()
        owned_socket = _DeadlineSocket(
            connected_socket, time.monotonic() + 1.0
        )
        reader = owned_socket.makefile("rb", buffering=0)

        owned_socket.close()
        self.assertEqual(connected_socket.close_count, 0)
        reader.close()
        self.assertEqual(connected_socket.close_count, 1)
        owned_socket.close()
        self.assertEqual(connected_socket.close_count, 1)

    def test_connection_uses_validated_address_without_dns_reresolution(self):
        answers = [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 80)),
        ]
        with patch(
            "sourcecourt.fetch.socket.getaddrinfo", return_value=answers
        ) as resolver, patch(
            "sourcecourt.fetch._connect_pinned", side_effect=OSError("test stop")
        ) as connector:
            with self.assertRaisesRegex(RetrievalError, "test stop"):
                HttpFetcher(FetchLimits(timeout_seconds=0.1)).fetch(
                    "http://public.example/"
                )
        resolver.assert_called_once()
        connector.assert_called_once()
        endpoint = connector.call_args.args[0]
        self.assertEqual(endpoint[4][0], "93.184.216.34")

    def test_https_connection_preserves_hostname_verification(self):
        endpoint = (
            socket.AF_INET,
            socket.SOCK_STREAM,
            6,
            "",
            ("93.184.216.34", 443),
        )
        with patch("sourcecourt.fetch.socket.socket") as socket_factory, patch(
            "sourcecourt.fetch.ssl.create_default_context"
        ) as context_factory:
            from sourcecourt.fetch import _connect_pinned

            wrapped = _connect_pinned(endpoint, 1.0, "public.example")
        raw_socket = socket_factory.return_value
        context = context_factory.return_value
        raw_socket.connect.assert_called_once_with(("93.184.216.34", 443))
        context.wrap_socket.assert_called_once_with(
            raw_socket, server_hostname="public.example"
        )
        self.assertIs(wrapped, context.wrap_socket.return_value)

    def test_redirect_revalidates_destination(self):
        with self.assertRaisesRegex(RetrievalError, "loopback destinations"):
            HttpFetcher.for_local_fixture_tests().fetch(
                self.base + "/redirect-private"
            )

    def test_redirect_honors_configured_url_length(self):
        page = HttpFetcher.for_local_fixture_tests(
            FetchLimits(max_url_length=4096)
        ).fetch(self.base + "/redirect-long")
        self.assertGreater(len(page.final_url), 2048)
        self.assertEqual(page.text, "long redirect accepted")

        with self.assertRaisesRegex(RetrievalError, "oversized URL"):
            HttpFetcher.for_local_fixture_tests(
                FetchLimits(max_url_length=128)
            ).fetch(self.base + "/redirect-long")

    def test_system_proxy_settings_are_ignored(self):
        hostile_proxy = "http://127.0.0.1:1"
        with patch.dict(
            os.environ,
            {"HTTP_PROXY": hostile_proxy, "HTTPS_PROXY": hostile_proxy, "NO_PROXY": ""},
            clear=False,
        ), patch("urllib.request.proxy_bypass", return_value=False):
            page = HttpFetcher.for_local_fixture_tests().fetch(self.base + "/ok")
        self.assertIn("Launch date", page.text)

    def test_overall_deadline_bounds_slow_streaming_body(self):
        started = time.monotonic()
        with self.assertRaisesRegex(RetrievalError, "timed out"):
            HttpFetcher.for_local_fixture_tests(
                FetchLimits(timeout_seconds=0.1)
            ).fetch(self.base + "/drip")
        self.assertLess(time.monotonic() - started, 0.3)

    def test_overall_deadline_bounds_slow_trickling_headers(self):
        configured_deadline = 0.2
        acceptable_tolerance = 0.12
        started = time.monotonic()
        with self.assertRaisesRegex(RetrievalError, "timed out"):
            HttpFetcher.for_local_fixture_tests(
                FetchLimits(timeout_seconds=configured_deadline)
            ).fetch(self.base + "/slow-headers")
        elapsed = time.monotonic() - started
        self.assertLess(elapsed, configured_deadline + acceptable_tolerance)

    def test_overall_deadline_includes_redirect_chain(self):
        with self.assertRaisesRegex(RetrievalError, "timed out"):
            HttpFetcher.for_local_fixture_tests(
                FetchLimits(timeout_seconds=0.1, max_redirects=2)
            ).fetch(self.base + "/slow-redirect-1")

    def test_rejects_unsupported_or_credentialed_urls(self):
        for url in ("file:///etc/passwd", "ftp://example.test/x", "http://user:pass@example.test/"):
            with self.subTest(url=url), self.assertRaises(RetrievalError):
                HttpFetcher().fetch(url)

    def test_rejects_oversized_body(self):
        with self.assertRaisesRegex(RetrievalError, "maximum size"):
            HttpFetcher.for_local_fixture_tests(
                FetchLimits(max_bytes=128)
            ).fetch(self.base + "/large")

    def test_rejects_unapproved_content_type_and_bad_encoding(self):
        for path in ("/binary", "/malformed"):
            with self.subTest(path=path), self.assertRaises(RetrievalError):
                HttpFetcher.for_local_fixture_tests().fetch(self.base + path)

    def test_timeout_is_normalized(self):
        with self.assertRaisesRegex(RetrievalError, "timed out"):
            HttpFetcher.for_local_fixture_tests(
                FetchLimits(timeout_seconds=0.05)
            ).fetch(self.base + "/slow")

    def test_http_failure_is_normalized(self):
        with self.assertRaisesRegex(RetrievalError, "HTTP 404"):
            HttpFetcher.for_local_fixture_tests().fetch(self.base + "/missing")


if __name__ == "__main__":
    unittest.main()
