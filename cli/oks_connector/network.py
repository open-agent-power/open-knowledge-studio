"""Safe public HTTP probe and fetch with network boundary enforcement."""

from __future__ import annotations

import hashlib
import re
import ipaddress
import os
import socket
import ssl
import tempfile
from datetime import datetime, timezone
from email.message import Message
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urldefrag, urljoin, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

from oks_connector.constants import FETCH_RECEIPT_VERSION, PLUGIN_VERSION
from oks_connector.route import is_url, platform_for, route_plan



class ProbeError(RuntimeError):
    """One stable, user-facing URL probe failure."""

    def __init__(self, code: str, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable


def normalize_public_http_url(value: str) -> str:
    """Normalize a public HTTP(S) URL without treating it as authorization."""
    candidate, _fragment = urldefrag(value.strip())
    parsed = urlparse(candidate)
    if parsed.scheme.lower() not in {"http", "https"}:
        raise ProbeError("INVALID_URL", "only http and https URLs are supported")
    if not parsed.hostname:
        raise ProbeError("INVALID_URL", "URL has no hostname")
    if parsed.username is not None or parsed.password is not None:
        raise ProbeError("INVALID_URL", "credentials embedded in URLs are not accepted")
    try:
        _ = parsed.port
    except ValueError as exc:
        raise ProbeError("INVALID_URL", str(exc)) from exc
    return parsed._replace(scheme=parsed.scheme.lower()).geturl()


def assert_public_network_target(url: str) -> list[str]:
    """Resolve a URL and reject loopback, private, link-local and reserved targets."""
    parsed = urlparse(url)
    assert parsed.hostname
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        addresses = socket.getaddrinfo(
            parsed.hostname, port, type=socket.SOCK_STREAM
        )
    except socket.gaierror as exc:
        raise ProbeError("DNS_FAILED", str(exc), retryable=True) from exc
    resolved: list[str] = []
    for address in addresses:
        raw_ip = address[4][0].split("%", 1)[0]
        ip = ipaddress.ip_address(raw_ip)
        if not ip.is_global:
            raise ProbeError(
                "INVALID_URL",
                f"target resolves to a non-public address: {ip.compressed}",
            )
        if ip.compressed not in resolved:
            resolved.append(ip.compressed)
    if not resolved:
        raise ProbeError("DNS_FAILED", "hostname resolved to no usable address", retryable=True)
    return resolved


class SafeProbeRedirectHandler(HTTPRedirectHandler):
    def __init__(self, max_redirects: int) -> None:
        super().__init__()
        self.max_redirects = max_redirects
        self.redirects: list[dict[str, Any]] = []

    def redirect_request(
        self,
        req: Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Message,
        newurl: str,
    ) -> Request | None:
        if len(self.redirects) >= self.max_redirects:
            raise ProbeError("REDIRECT_LOOP", "redirect limit exceeded")
        target = normalize_public_http_url(urljoin(req.full_url, newurl))
        assert_public_network_target(target)
        self.redirects.append({"status": code, "from": req.full_url, "to": target})
        return super().redirect_request(req, fp, code, msg, headers, target)


def _header_value(headers: Any, name: str) -> str | None:
    value = headers.get(name) if headers is not None else None
    return str(value) if value is not None else None


def _looks_like_challenge(sample: bytes, final_url: str | None = None) -> bool:
    text = sample.decode("utf-8", errors="ignore").lower()
    strong_markers = (
        "cf-chl-",
        "cloudflare challenge",
        "challenges.cloudflare.com",
        "cf-turnstile",
        "g-recaptcha",
        "h-captcha",
        "id=\"captcha\"",
        "id='captcha'",
    )
    if any(marker in text for marker in strong_markers):
        return True
    if final_url:
        parsed = urlparse(final_url)
        location = f"{parsed.path}?{parsed.query}".lower()
        return "captcha" in location or "challenge" in location
    return False


def _looks_script_only(sample: bytes) -> bool:
    text = sample.decode("utf-8", errors="ignore")
    without_scripts = re.sub(r"<script\b[^>]*>.*?</script>", " ", text, flags=re.I | re.S)
    without_tags = re.sub(r"<[^>]+>", " ", without_scripts)
    visible = re.sub(r"\s+", " ", without_tags).strip()
    return len(visible) < 80 and bool(re.search(r"<script\b", text, flags=re.I))


def _error_receipt(
    source: str,
    normalized: str | None,
    code: str,
    message: str,
    *,
    retryable: bool,
    started_at: str,
    redirects: list[dict[str, Any]] | None = None,
    http_status: int | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": FETCH_RECEIPT_VERSION,
        "status": "failed_retryable" if retryable else "failed_final",
        "source_url": source,
        "normalized_url": normalized,
        "final_url": redirects[-1]["to"] if redirects else normalized,
        "started_at": started_at,
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "fetch_mode": "http_probe",
        "http_status": http_status,
        "redirects": redirects or [],
        "error": {"code": code, "message": message, "retryable": retryable},
        "next_action": "retry" if retryable else "user_review",
    }


def safe_redirect_chain(
    source: str,
    get: Any,
    *,
    max_redirects: int = 5,
) -> tuple[Any, str, list[dict[str, str]]]:
    """Follow redirects manually, validating every hop against SSRF.

    ``requests.get(url, allow_redirects=True)`` only ever sees the first URL, so
    a public host that 302s to ``127.0.0.1`` walks straight past
    :func:`assert_public_network_target`. This validates each hop instead.

    *get* is injected (typically ``requests.get`` bound with headers and timeout,
    with redirects disabled) so this module keeps its urllib-only dependencies.

    Returns ``(final_response, final_url, hops)``. Intermediate 3xx responses are
    closed before moving on, and a 3xx without ``Location`` is an error rather
    than a silently returned redirect body.
    """
    url = normalize_public_http_url(source)
    assert_public_network_target(url)
    hops: list[dict[str, str]] = []

    for _ in range(max_redirects + 1):
        response = get(url)
        if response.status_code not in {301, 302, 303, 307, 308}:
            return response, url, hops

        status = response.status_code
        location = response.headers.get("Location")
        try:
            if not location:
                raise ProbeError(
                    "INVALID_REDIRECT",
                    f"HTTP {status} without a Location header",
                )
            target = normalize_public_http_url(urljoin(url, location))
            assert_public_network_target(target)
        finally:
            response.close()

        hops.append({"status": str(status), "from": url, "to": target})
        url = target

    raise ProbeError("REDIRECT_LOOP", "redirect limit exceeded")


def probe_url(
    source: str,
    *,
    timeout: float = 15.0,
    max_bytes: int = 64 * 1024,
    max_redirects: int = 5,
    opener: Any | None = None,
    resolved_addresses: list[str] | None = None,
) -> dict[str, Any]:
    """Inspect one URL without bypassing authentication or anti-bot controls."""
    started_at = datetime.now(timezone.utc).isoformat()
    normalized: str | None = None
    redirect_handler = SafeProbeRedirectHandler(max_redirects)
    try:
        if timeout <= 0 or max_bytes <= 0 or max_redirects < 0:
            raise ProbeError("INVALID_ARGUMENT", "probe limits must be positive")
        normalized = normalize_public_http_url(source)
        route = route_plan(normalized)
        if route["platform"] in {"bilibili", "douyin", "youtube"}:
            finished_at = datetime.now(timezone.utc).isoformat()
            return {
                "schema_version": FETCH_RECEIPT_VERSION,
                "status": "ok",
                "source_url": source,
                "normalized_url": normalized,
                "final_url": normalized,
                "started_at": started_at,
                "finished_at": finished_at,
                "fetch_mode": "platform_route",
                "http_status": None,
                "content_type": None,
                "content_length": None,
                "sample_bytes": 0,
                "sample_truncated": False,
                "sample_sha256": hashlib.sha256(b"").hexdigest(),
                "resolved_addresses": [],
                "redirects": [],
                "route_plan": route,
                "robots": {
                    "checked": False,
                    "reason": "known platform URLs are delegated without a generic HTTP crawl",
                },
                "error": None,
                "next_action": "platform_extractor",
            }
        addresses = resolved_addresses or assert_public_network_target(normalized)
        client = opener or build_opener(redirect_handler)
        request = Request(
            normalized,
            headers={
                "User-Agent": f"oks-connector/{PLUGIN_VERSION} (+single-url-probe)",
                "Accept": "text/html,application/xhtml+xml,application/pdf,image/*,audio/*,video/*,*/*;q=0.1",
            },
            method="GET",
        )
        with client.open(request, timeout=timeout) as response:
            status = int(getattr(response, "status", response.getcode()))
            final_url = normalize_public_http_url(response.geturl())
            if not redirect_handler.redirects and final_url != normalized:
                assert_public_network_target(final_url)
            content_type = (_header_value(response.headers, "Content-Type") or "").split(";", 1)[0].strip().lower()
            content_length_text = _header_value(response.headers, "Content-Length")
            content_length = int(content_length_text) if content_length_text and content_length_text.isdigit() else None
            sample = response.read(max_bytes + 1)
        sample_truncated = len(sample) > max_bytes
        sample = sample[:max_bytes]
        route = route_plan(final_url)
        next_action = "direct_http_snapshot"
        status_name = "ok"
        error: dict[str, Any] | None = None
        if _looks_like_challenge(sample, final_url):
            status_name = "needs_user_action"
            next_action = "visible_browser_or_manual_snapshot"
            error = {
                "code": "CHALLENGE_REQUIRED",
                "message": "challenge or CAPTCHA detected; automatic bypass is not attempted",
                "retryable": False,
            }
        elif content_length is not None and content_length > max_bytes and route["source_type"] == "unknown":
            next_action = "review_size_before_download"
        elif content_type in {"text/html", "application/xhtml+xml"} and _looks_script_only(sample):
            next_action = "browser_public"
            error = {
                "code": "JS_RENDER_REQUIRED",
                "message": "HTTP response contains little visible text and requires browser rendering",
                "retryable": False,
            }
        elif route["platform"] in {"bilibili", "douyin", "youtube"}:
            next_action = "platform_extractor"
        elif route["source_type"] != "unknown":
            next_action = "download_then_route"
        return {
            "schema_version": FETCH_RECEIPT_VERSION,
            "status": status_name,
            "source_url": source,
            "normalized_url": normalized,
            "final_url": final_url,
            "started_at": started_at,
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "fetch_mode": "http_probe",
            "http_status": status,
            "content_type": content_type or None,
            "content_length": content_length,
            "sample_bytes": len(sample),
            "sample_truncated": sample_truncated,
            "sample_sha256": hashlib.sha256(sample).hexdigest(),
            "resolved_addresses": addresses,
            "redirects": redirect_handler.redirects,
            "route_plan": route,
            "robots": {"checked": False, "reason": "site crawl is not performed by probe v0.1"},
            "error": error,
            "next_action": next_action,
        }
    except ProbeError as exc:
        return _error_receipt(
            source,
            normalized,
            exc.code,
            str(exc),
            retryable=exc.retryable,
            started_at=started_at,
            redirects=redirect_handler.redirects,
        )
    except HTTPError as exc:
        try:
            sample = exc.read(max_bytes)
        except Exception:
            sample = b""
        if _looks_like_challenge(sample, getattr(exc, "url", None)):
            code, retryable = "CHALLENGE_REQUIRED", False
        elif exc.code in {401, 407}:
            code, retryable = "AUTH_REQUIRED", False
        elif exc.code in {403, 451}:
            code, retryable = "FORBIDDEN", False
        elif exc.code == 404:
            code, retryable = "NOT_FOUND", False
        elif exc.code == 429:
            code, retryable = "RATE_LIMITED", True
        elif 500 <= exc.code <= 599:
            code, retryable = "UPSTREAM_UNAVAILABLE", True
        else:
            code, retryable = "HTTP_ERROR", False
        receipt = _error_receipt(
            source,
            normalized,
            code,
            f"HTTP {exc.code}: {exc.reason}",
            retryable=retryable,
            started_at=started_at,
            redirects=redirect_handler.redirects,
            http_status=exc.code,
        )
        if code in {"AUTH_REQUIRED", "CHALLENGE_REQUIRED"}:
            receipt["status"] = "needs_user_action"
            receipt["next_action"] = "visible_browser_or_manual_snapshot"
        if exc.code == 429:
            receipt["retry_after"] = _header_value(exc.headers, "Retry-After")
        return receipt
    except (socket.timeout, TimeoutError) as exc:
        return _error_receipt(source, normalized, "FETCH_TIMEOUT", str(exc), retryable=True, started_at=started_at)
    except ssl.SSLError as exc:
        return _error_receipt(source, normalized, "TLS_FAILED", str(exc), retryable=False, started_at=started_at)
    except URLError as exc:
        reason = exc.reason
        if isinstance(reason, socket.gaierror):
            code, retryable = "DNS_FAILED", True
        elif isinstance(reason, (socket.timeout, TimeoutError)):
            code, retryable = "FETCH_TIMEOUT", True
        elif isinstance(reason, ssl.SSLError):
            code, retryable = "TLS_FAILED", False
        else:
            code, retryable = "NETWORK_FAILED", True
        return _error_receipt(source, normalized, code, str(reason), retryable=retryable, started_at=started_at)


def fetch_url(
    source: str,
    output: Path,
    *,
    timeout: float = 30.0,
    max_bytes: int = 64 * 1024 * 1024,
    max_redirects: int = 5,
    overwrite: bool = False,
    opener: Any | None = None,
    resolved_addresses: list[str] | None = None,
) -> dict[str, Any]:
    """Download one immutable public source snapshot with bounded resource use."""
    started_at = datetime.now(timezone.utc).isoformat()
    normalized: str | None = None
    redirect_handler = SafeProbeRedirectHandler(max_redirects)
    target = output.expanduser().resolve()
    temporary: Path | None = None
    try:
        if timeout <= 0 or max_bytes <= 0 or max_redirects < 0:
            raise ProbeError("INVALID_ARGUMENT", "fetch limits must be positive")
        normalized = normalize_public_http_url(source)
        addresses = resolved_addresses or assert_public_network_target(normalized)
        if target.exists() and not overwrite:
            raise ProbeError("OUTPUT_EXISTS", f"output already exists: {target}")
        target.parent.mkdir(parents=True, exist_ok=True)
        client = opener or build_opener(redirect_handler)
        request = Request(
            normalized,
            headers={
                "User-Agent": f"oks-connector/{PLUGIN_VERSION} (+single-url-snapshot)",
                "Accept": "application/pdf,image/*,audio/*,video/*,application/octet-stream,*/*;q=0.1",
            },
            method="GET",
        )
        with client.open(request, timeout=timeout) as response:
            status = int(getattr(response, "status", response.getcode()))
            final_url = normalize_public_http_url(response.geturl())
            if not redirect_handler.redirects and final_url != normalized:
                assert_public_network_target(final_url)
            content_type = (_header_value(response.headers, "Content-Type") or "").split(";", 1)[0].strip().lower()
            content_length_text = _header_value(response.headers, "Content-Length")
            content_length = int(content_length_text) if content_length_text and content_length_text.isdigit() else None
            if content_length is not None and content_length > max_bytes:
                raise ProbeError(
                    "RESPONSE_TOO_LARGE",
                    f"declared response size {content_length} exceeds limit {max_bytes}",
                )
            handle, temporary_name = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
            temporary = Path(temporary_name)
            digest = hashlib.sha256()
            sample = bytearray()
            received = 0
            with os.fdopen(handle, "wb") as stream:
                while True:
                    chunk = response.read(min(1024 * 1024, max_bytes - received + 1))
                    if not chunk:
                        break
                    received += len(chunk)
                    if received > max_bytes:
                        raise ProbeError(
                            "RESPONSE_TOO_LARGE",
                            f"response exceeded download limit {max_bytes}",
                        )
                    if len(sample) < 64 * 1024:
                        sample.extend(chunk[: 64 * 1024 - len(sample)])
                    digest.update(chunk)
                    stream.write(chunk)
                stream.flush()
                os.fsync(stream.fileno())
        if content_type in {"text/html", "application/xhtml+xml"}:
            if _looks_like_challenge(bytes(sample), final_url):
                raise ProbeError("CHALLENGE_REQUIRED", "challenge or CAPTCHA detected; automatic bypass is not attempted")
            raise ProbeError("UNSUPPORTED_MIME", "HTML snapshots must use the web or browser acquisition route")
        os.replace(temporary, target)
        # Directory fsync persists the rename itself; without it a crash can
        # leave the receipt claiming success for a file that no longer exists.
        try:
            dir_fd = os.open(str(target.parent), os.O_RDONLY)
        except OSError:
            pass
        else:
            try:
                os.fsync(dir_fd)
            except OSError:
                pass
            finally:
                os.close(dir_fd)
        temporary = None
        return {
            "schema_version": FETCH_RECEIPT_VERSION,
            "status": "ok",
            "source_url": source,
            "normalized_url": normalized,
            "final_url": final_url,
            "started_at": started_at,
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "fetch_mode": "http_snapshot",
            "http_status": status,
            "content_type": content_type or None,
            "content_length": content_length,
            "downloaded_bytes": received,
            "content_sha256": digest.hexdigest(),
            "output": str(target),
            "resolved_addresses": addresses,
            "redirects": redirect_handler.redirects,
            "route_plan": route_plan(final_url),
            "error": None,
            "next_action": "route_local_snapshot",
        }
    except ProbeError as exc:
        receipt = _error_receipt(
            source,
            normalized,
            exc.code,
            str(exc),
            retryable=exc.retryable,
            started_at=started_at,
            redirects=redirect_handler.redirects,
        )
        receipt["fetch_mode"] = "http_snapshot"
        if exc.code == "CHALLENGE_REQUIRED":
            receipt["status"] = "needs_user_action"
            receipt["next_action"] = "visible_browser_or_manual_snapshot"
        return receipt
    except (HTTPError, URLError, socket.timeout, TimeoutError, ssl.SSLError) as exc:
        retryable = isinstance(exc, (URLError, socket.timeout, TimeoutError))
        receipt = _error_receipt(
            source,
            normalized,
            "NETWORK_FAILED" if retryable else "HTTP_ERROR",
            str(exc),
            retryable=retryable,
            started_at=started_at,
            redirects=redirect_handler.redirects,
            http_status=getattr(exc, "code", None),
        )
        receipt["fetch_mode"] = "http_snapshot"
        return receipt
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
