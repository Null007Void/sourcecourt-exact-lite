"""Bounded HTTP/HTTPS retrieval using only the Python standard library."""

from __future__ import annotations

import http.client
import io
import ipaddress
import queue
import socket
import ssl
import threading
import time
from dataclasses import dataclass
from urllib.parse import urldefrag, urljoin, urlsplit, urlunsplit


class RetrievalError(RuntimeError):
    """A normalized, safe retrieval failure."""


_DNS_SLOTS = threading.BoundedSemaphore(4)


@dataclass(frozen=True)
class FetchLimits:
    timeout_seconds: float = 5.0
    max_bytes: int = 1_000_000
    max_redirects: int = 3
    max_url_length: int = 2048

    def __post_init__(self) -> None:
        if (
            self.timeout_seconds <= 0
            or self.max_bytes <= 0
            or self.max_redirects < 0
            or self.max_url_length <= 0
        ):
            raise ValueError("fetch limits must be positive (redirects may be zero)")


@dataclass(frozen=True)
class RetrievedPage:
    requested_url: str
    final_url: str
    status_code: int
    content_type: str
    text: str


def _validate_url(url: str, max_length: int) -> str:
    if not isinstance(url, str) or not url or len(url) > max_length:
        raise RetrievalError("invalid or oversized URL")
    if any(ord(character) < 32 or ord(character) == 127 for character in url):
        raise RetrievalError("invalid or oversized URL")
    clean, _fragment = urldefrag(url)
    try:
        parsed = urlsplit(clean)
        port = parsed.port
    except ValueError as exc:
        raise RetrievalError("invalid or oversized URL") from exc
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        raise RetrievalError("only absolute HTTP/HTTPS URLs are supported")
    if parsed.username is not None or parsed.password is not None:
        raise RetrievalError("credentialed URLs are forbidden")
    if port is not None and not 1 <= port <= 65535:
        raise RetrievalError("invalid or oversized URL")
    return clean


def _is_public_address(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if isinstance(address, ipaddress.IPv6Address):
        if address.ipv4_mapped is not None:
            return _is_public_address(address.ipv4_mapped)
        if address.sixtofour is not None or address.teredo is not None:
            return False
    return bool(
        address.is_global
        and not address.is_loopback
        and not address.is_link_local
        and not address.is_multicast
        and not address.is_reserved
        and not address.is_unspecified
        and not getattr(address, "is_site_local", False)
    )


def _literal_endpoint(
    address: ipaddress.IPv4Address | ipaddress.IPv6Address, port: int
) -> tuple[int, int, int, str, tuple]:
    if isinstance(address, ipaddress.IPv6Address):
        sockaddr = (str(address), port, 0, 0)
        family = socket.AF_INET6
    else:
        sockaddr = (str(address), port)
        family = socket.AF_INET
    return family, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", sockaddr


def _validate_destination(
    url: str, allow_loopback_fixture: bool, deadline: float
) -> tuple[int, int, int, str, tuple]:
    parsed = urlsplit(url)
    hostname = parsed.hostname
    assert hostname is not None
    port = parsed.port or (443 if parsed.scheme.lower() == "https" else 80)
    try:
        literal = ipaddress.ip_address(hostname)
    except ValueError:
        literal = None

    if allow_loopback_fixture:
        if literal is None or not literal.is_loopback:
            raise RetrievalError("local fixture mode permits only literal loopback destinations")
        return _literal_endpoint(literal, port)

    if literal is not None:
        records = (_literal_endpoint(literal, port),)
    else:
        try:
            records = _bounded_getaddrinfo(hostname, port, deadline)
        except socket.gaierror as exc:
            raise RetrievalError("destination DNS resolution failed") from exc
        if not records:
            raise RetrievalError("destination DNS resolution returned no addresses")

    try:
        addresses = tuple(ipaddress.ip_address(record[4][0]) for record in records)
    except ValueError as exc:
        raise RetrievalError("destination DNS resolution returned an invalid address") from exc
    if any(not _is_public_address(address) for address in addresses):
        raise RetrievalError("non-public destination is forbidden")
    return records[0]


def _bounded_getaddrinfo(hostname: str, port: int, deadline: float) -> tuple:
    """Resolve DNS within the retrieval deadline using bounded daemon capacity."""

    if not _DNS_SLOTS.acquire(timeout=_remaining(deadline)):
        raise RetrievalError("retrieval timed out")
    result_queue: queue.Queue[tuple[bool, object]] = queue.Queue(maxsize=1)

    def resolve() -> None:
        try:
            result = tuple(
                socket.getaddrinfo(
                    hostname,
                    port,
                    family=socket.AF_UNSPEC,
                    type=socket.SOCK_STREAM,
                    proto=socket.IPPROTO_TCP,
                )
            )
            result_queue.put((True, result))
        except BaseException as exc:
            result_queue.put((False, exc))
        finally:
            _DNS_SLOTS.release()

    threading.Thread(target=resolve, daemon=True, name="sourcecourt-dns").start()
    try:
        succeeded, value = result_queue.get(timeout=_remaining(deadline))
    except queue.Empty as exc:
        raise RetrievalError("retrieval timed out") from exc
    if not succeeded:
        assert isinstance(value, BaseException)
        raise value
    assert isinstance(value, tuple)
    return value


def _connect_pinned(
    endpoint: tuple[int, int, int, str, tuple],
    timeout: float,
    tls_hostname: str | None,
):
    """Connect directly to one validated address without a DNS re-resolution."""

    family, socktype, proto, _canonical_name, sockaddr = endpoint
    raw_socket = socket.socket(family, socktype, proto)
    try:
        raw_socket.settimeout(timeout)
        raw_socket.connect(sockaddr)
        if tls_hostname is None:
            return raw_socket
        context = ssl.create_default_context()
        return context.wrap_socket(raw_socket, server_hostname=tls_hostname)
    except BaseException:
        raw_socket.close()
        raise


def _remaining(deadline: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise RetrievalError("retrieval timed out")
    return remaining


class _DeadlineSocketReader(io.RawIOBase):
    """Raw reader that reapplies the shrinking absolute deadline per receive."""

    def __init__(self, connected_socket: socket.socket, deadline: float, release):
        super().__init__()
        self._sock = connected_socket
        self._deadline = deadline
        self._release = release

    def readable(self) -> bool:
        return True

    def readinto(self, buffer) -> int:
        self._sock.settimeout(_remaining(self._deadline))
        return self._sock.recv_into(buffer)

    def close(self) -> None:
        if not self.closed:
            self._release()
        super().close()


class _DeadlineSocket:
    """Socket facade whose HTTP reads and writes share one monotonic deadline."""

    def __init__(self, connected_socket: socket.socket, deadline: float):
        self._sock = connected_socket
        self._deadline = deadline
        self._file_references = 0
        self._close_requested = False
        self._closed = False

    def __getattr__(self, name: str):
        return getattr(self._sock, name)

    def _close_underlying_if_unreferenced(self) -> None:
        if self._close_requested and self._file_references == 0 and not self._closed:
            self._closed = True
            self._sock.close()

    def _release_file(self) -> None:
        if self._file_references > 0:
            self._file_references -= 1
        self._close_underlying_if_unreferenced()

    def close(self) -> None:
        self._close_requested = True
        self._close_underlying_if_unreferenced()

    def sendall(self, data, flags: int = 0) -> None:
        self._sock.settimeout(_remaining(self._deadline))
        self._sock.sendall(data, flags)

    def makefile(
        self,
        mode: str = "r",
        buffering: int | None = None,
        *,
        encoding=None,
        errors=None,
        newline=None,
    ):
        if mode != "rb" or encoding is not None or errors is not None or newline is not None:
            raise ValueError("deadline socket supports only binary response reads")
        self._file_references += 1
        raw = _DeadlineSocketReader(self._sock, self._deadline, self._release_file)
        if buffering == 0:
            return raw
        buffer_size = io.DEFAULT_BUFFER_SIZE if buffering is None or buffering < 0 else buffering
        return io.BufferedReader(raw, buffer_size=buffer_size)


def _set_response_timeout(response: http.client.HTTPResponse, timeout: float) -> None:
    """Set the live response socket timeout even after HTTPConnection detaches it."""

    buffered = response.fp
    raw = getattr(buffered, "raw", None)
    response_socket = getattr(raw, "_sock", None)
    if response_socket is None:
        raise RetrievalError("retrieval connection closed unexpectedly")
    response_socket.settimeout(timeout)


def _user_agent() -> str:
    """Product user agent, versioned from the package (single source of truth)."""
    from . import __version__

    return f"SourceCourt-Exact-Lite/{__version__}"


def _request_target(url: str) -> str:
    parsed = urlsplit(url)
    return urlunsplit(("", "", parsed.path or "/", parsed.query, ""))


class HttpFetcher:
    def __init__(self, limits: FetchLimits | None = None):
        self.limits = limits or FetchLimits()
        self._allow_loopback_fixture = False

    @classmethod
    def for_local_fixture_tests(cls, limits: FetchLimits | None = None) -> "HttpFetcher":
        """Create a test-only fetcher limited to literal loopback destinations."""

        fetcher = cls(limits)
        fetcher._allow_loopback_fixture = True
        return fetcher

    def fetch(self, url: str) -> RetrievedPage:
        requested_url = _validate_url(url, self.limits.max_url_length)
        current_url = requested_url
        redirect_count = 0
        deadline = time.monotonic() + self.limits.timeout_seconds

        try:
            while True:
                current_url = _validate_url(current_url, self.limits.max_url_length)
                endpoint = _validate_destination(
                    current_url, self._allow_loopback_fixture, deadline
                )
                parsed = urlsplit(current_url)
                hostname = parsed.hostname
                assert hostname is not None
                port = parsed.port or (
                    443 if parsed.scheme.lower() == "https" else 80
                )
                tls_hostname = hostname if parsed.scheme.lower() == "https" else None

                connection: http.client.HTTPConnection | None = None
                response: http.client.HTTPResponse | None = None
                owned_socket: _DeadlineSocket | None = None
                try:
                    connected_socket = _connect_pinned(
                        endpoint, _remaining(deadline), tls_hostname
                    )
                    owned_socket = _DeadlineSocket(connected_socket, deadline)
                    connection = http.client.HTTPConnection(
                        hostname, port=port, timeout=_remaining(deadline)
                    )
                    connection.sock = owned_socket
                    connection.request(
                        "GET",
                        _request_target(current_url),
                        headers={
                            "User-Agent": _user_agent(),
                            "Accept": "text/html,text/plain",
                            "Accept-Encoding": "identity",
                            "Connection": "close",
                        },
                    )
                    connected_socket.settimeout(_remaining(deadline))
                    response = connection.getresponse()
                    status = int(response.status)

                    if status in {301, 302, 303, 307, 308}:
                        location = response.getheader("Location")
                        if not location:
                            raise RetrievalError(f"HTTP {status} retrieval failure")
                        if redirect_count >= self.limits.max_redirects:
                            raise RetrievalError("redirect limit exceeded")
                        redirect_count += 1
                        current_url = _validate_url(
                            urljoin(current_url, location),
                            self.limits.max_url_length,
                        )
                        continue

                    if status >= 400:
                        raise RetrievalError(f"HTTP {status} retrieval failure")

                    content_type = response.headers.get_content_type().lower()
                    if content_type not in {"text/html", "text/plain"}:
                        raise RetrievalError(
                            f"unsupported content type: {content_type}"
                        )
                    declared = response.getheader("Content-Length")
                    declared_size: int | None = None
                    if declared is not None:
                        try:
                            declared_size = int(declared)
                        except ValueError as exc:
                            raise RetrievalError("invalid Content-Length") from exc
                        if declared_size < 0:
                            raise RetrievalError("invalid Content-Length")
                        if declared_size > self.limits.max_bytes:
                            raise RetrievalError("response exceeds maximum size")

                    body = bytearray()
                    while len(body) <= self.limits.max_bytes:
                        _set_response_timeout(response, _remaining(deadline))
                        read_size = min(
                            65_536, self.limits.max_bytes + 1 - len(body)
                        )
                        chunk = response.read1(read_size)
                        if not chunk:
                            break
                        body.extend(chunk)
                        if declared_size is not None and len(body) >= declared_size:
                            break
                    if len(body) > self.limits.max_bytes:
                        raise RetrievalError("response exceeds maximum size")

                    charset = response.headers.get_content_charset() or "utf-8"
                    try:
                        text = bytes(body).decode(charset, errors="strict")
                    except (LookupError, UnicodeDecodeError) as exc:
                        raise RetrievalError(
                            "response text encoding is invalid"
                        ) from exc
                    return RetrievedPage(
                        requested_url, current_url, status, content_type, text
                    )
                finally:
                    if response is not None:
                        response.close()
                    if connection is not None:
                        connection.close()
                    if owned_socket is not None:
                        owned_socket.close()
        except RetrievalError:
            raise
        except (socket.timeout, TimeoutError) as exc:
            raise RetrievalError("retrieval timed out") from exc
        except (http.client.HTTPException, ssl.SSLError, OSError) as exc:
            raise RetrievalError(f"retrieval failed: {exc}") from exc
