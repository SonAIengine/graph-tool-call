"""Safe network helpers for remote spec loading."""

from __future__ import annotations

import ipaddress
import socket
import urllib.error
import urllib.request
from email.message import Message
from typing import Any
from urllib.parse import urlparse

_DEFAULT_MAX_RESPONSE_BYTES = 5_000_000
_DEFAULT_MAX_REDIRECTS = 3
_DEFAULT_ALLOWED_CONTENT_TYPES = (
    "application/json",
    "application/yaml",
    "application/x-yaml",
    "text/yaml",
    "text/x-yaml",
    "text/plain",
)


class _LimitedRedirectHandler(urllib.request.HTTPRedirectHandler):
    """HTTP redirect handler with a hard cap."""

    def __init__(self, max_redirects: int) -> None:
        super().__init__()
        self._remaining = max_redirects

    def redirect_request(
        self,
        req: Any,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> Any:
        if self._remaining <= 0:
            raise urllib.error.HTTPError(newurl, code, "redirect limit exceeded", headers, fp)
        self._remaining -= 1
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _open_url(
    request: urllib.request.Request | str,
    *,
    timeout: int,
    max_redirects: int,
    verify_ssl: bool = True,
) -> Any:
    """urllib opener — verify_ssl=False 시 self-signed/사내 CA 인증서 허용."""
    handlers: list[Any] = [_LimitedRedirectHandler(max_redirects)]
    if not verify_ssl:
        import ssl
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        handlers.append(urllib.request.HTTPSHandler(context=ctx))
    opener = urllib.request.build_opener(*handlers)
    return opener.open(request, timeout=timeout)


def _is_private_ip(value: str) -> bool:
    ip = ipaddress.ip_address(value)
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def _is_private_hostname(hostname: str) -> bool:
    lowered = hostname.lower()
    if lowered in {"localhost", "localhost.localdomain"}:
        return True
    if lowered.endswith(".local"):
        return True

    try:
        return _is_private_ip(hostname)
    except ValueError:
        pass

    try:
        infos = socket.getaddrinfo(hostname, None, type=socket.SOCK_STREAM)
    except socket.gaierror:
        return False

    for info in infos:
        sockaddr = info[4]
        address = sockaddr[0]
        try:
            if _is_private_ip(address):
                return True
        except ValueError:
            continue
    return False


def validate_remote_url(url: str, *, allow_private_hosts: bool = False) -> None:
    """Validate that the remote URL is public by default."""
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        msg = f"Only http/https URLs are supported: {url}"
        raise ValueError(msg)

    if not parsed.hostname:
        msg = f"URL must include a hostname: {url}"
        raise ValueError(msg)

    if not allow_private_hosts and _is_private_hostname(parsed.hostname):
        msg = f"Refusing to access private or local host: {parsed.hostname}"
        raise ConnectionError(msg)


def _get_content_type(headers: Message | dict[str, Any] | None) -> str:
    if headers is None:
        return ""
    if isinstance(headers, Message):
        return str(headers.get_content_type())

    raw = ""
    if hasattr(headers, "get"):
        raw = str(headers.get("Content-Type", ""))
    if ";" in raw:
        raw = raw.split(";", 1)[0]
    return raw.strip().lower()


def fetch_url_text(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    timeout: int = 30,
    max_response_bytes: int = _DEFAULT_MAX_RESPONSE_BYTES,
    allowed_content_types: tuple[str, ...] = _DEFAULT_ALLOWED_CONTENT_TYPES,
    allow_private_hosts: bool = False,
    max_redirects: int = _DEFAULT_MAX_REDIRECTS,
    verify_ssl: bool | None = None,
) -> str:
    """Fetch UTF-8 text from a remote URL with basic SSRF protections.

    ``verify_ssl`` — None 이면 ``allow_private_hosts`` 값에 따라 자동 결정
    (사내망 hosts 는 self-signed CA 가 일반적이므로 verify off 가 기본).
    """
    validate_remote_url(url, allow_private_hosts=allow_private_hosts)

    if verify_ssl is None:
        # allow_private_hosts=True 사용자는 보통 사내망 hitting. 사내 CA 포용.
        verify_ssl = not allow_private_hosts

    req = urllib.request.Request(url, headers=headers or {})
    try:
        with _open_url(req, timeout=timeout, max_redirects=max_redirects, verify_ssl=verify_ssl) as resp:
            final_url = url
            if hasattr(resp, "geturl"):
                candidate = resp.geturl()
                if isinstance(candidate, str) and candidate:
                    final_url = candidate
            validate_remote_url(final_url, allow_private_hosts=allow_private_hosts)

            content_length = None
            if hasattr(resp, "headers") and resp.headers is not None:
                raw_length = resp.headers.get("Content-Length")
                if raw_length:
                    try:
                        content_length = int(raw_length)
                    except (TypeError, ValueError):
                        content_length = None

            if content_length is not None and content_length > max_response_bytes:
                msg = (
                    f"Remote response too large from {final_url}: "
                    f"{content_length} bytes > {max_response_bytes} byte limit"
                )
                raise ValueError(msg)

            content_type = _get_content_type(getattr(resp, "headers", None))
            if allowed_content_types and content_type and content_type not in allowed_content_types:
                msg = f"Unexpected content type from {final_url}: {content_type}"
                raise ValueError(msg)

            data = resp.read(max_response_bytes + 1)
    except urllib.error.HTTPError as e:
        msg = f"HTTP {e.code} from {url}: {e.reason}"
        raise ConnectionError(msg) from None
    except urllib.error.URLError as e:
        msg = f"Cannot reach {url}: {e.reason}"
        raise ConnectionError(msg) from None

    if len(data) > max_response_bytes:
        msg = f"Remote response too large from {url}: exceeded {max_response_bytes} byte limit"
        raise ValueError(msg)

    return data.decode("utf-8")


def post_json(
    url: str,
    payload: object,
    *,
    headers: dict[str, str] | None = None,
    timeout: int = 30,
    max_response_bytes: int = _DEFAULT_MAX_RESPONSE_BYTES,
    allowed_content_types: tuple[str, ...] = _DEFAULT_ALLOWED_CONTENT_TYPES,
    allow_private_hosts: bool = False,
    max_redirects: int = _DEFAULT_MAX_REDIRECTS,
) -> str:
    """POST JSON to a remote URL with the same SSRF protections as fetch_url_text()."""
    import json

    validate_remote_url(url, allow_private_hosts=allow_private_hosts)

    merged_headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if headers:
        merged_headers.update(headers)

    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=merged_headers,
        method="POST",
    )

    try:
        with _open_url(req, timeout=timeout, max_redirects=max_redirects) as resp:
            final_url = url
            if hasattr(resp, "geturl"):
                candidate = resp.geturl()
                if isinstance(candidate, str) and candidate:
                    final_url = candidate
            validate_remote_url(final_url, allow_private_hosts=allow_private_hosts)

            content_length = None
            if hasattr(resp, "headers") and resp.headers is not None:
                raw_length = resp.headers.get("Content-Length")
                if raw_length:
                    try:
                        content_length = int(raw_length)
                    except (TypeError, ValueError):
                        content_length = None

            if content_length is not None and content_length > max_response_bytes:
                msg = (
                    f"Remote response too large from {final_url}: "
                    f"{content_length} bytes > {max_response_bytes} byte limit"
                )
                raise ValueError(msg)

            content_type = _get_content_type(getattr(resp, "headers", None))
            if allowed_content_types and content_type and content_type not in allowed_content_types:
                msg = f"Unexpected content type from {final_url}: {content_type}"
                raise ValueError(msg)

            data = resp.read(max_response_bytes + 1)
    except urllib.error.HTTPError as e:
        msg = f"HTTP {e.code} from {url}: {e.reason}"
        raise ConnectionError(msg) from None
    except urllib.error.URLError as e:
        msg = f"Cannot reach {url}: {e.reason}"
        raise ConnectionError(msg) from None

    if len(data) > max_response_bytes:
        msg = f"Remote response too large from {url}: exceeded {max_response_bytes} byte limit"
        raise ValueError(msg)

    return data.decode("utf-8")
