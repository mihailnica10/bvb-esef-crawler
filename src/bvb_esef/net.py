from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from urllib.parse import urljoin, urlsplit

import httpx

from .config import ALLOWED_HOSTS, HEADERS

ALLOWED_SCHEMES = ("http", "https")
DEFAULT_TIMEOUT = 30.0
MAX_REDIRECTS = 5
REDIRECT_CODES = (301, 302, 303, 307, 308)
PRESERVE_BODY_CODES = (307, 308)


class BlockedUrl(ValueError):
    pass


def host_allowed(host: str) -> bool:
    h = (host or "").strip().lower().rstrip(".")
    if not h:
        return False
    return any(h == d or h.endswith("." + d) for d in ALLOWED_HOSTS)


def check_url(url: str) -> str:
    parts = urlsplit((url or "").strip())
    if parts.scheme.lower() not in ALLOWED_SCHEMES:
        raise BlockedUrl(
            f"blocked scheme {parts.scheme or '(none)'!r} in {url!r}: only "
            f"{' and '.join(ALLOWED_SCHEMES)} is allowed")
    host = parts.hostname or ""
    if not host_allowed(host):
        raise BlockedUrl(
            f"blocked host {host or '(none)'!r} in {url!r}: allowlist is "
            f"{', '.join(ALLOWED_HOSTS)}")
    return url.strip()


def client(timeout: float = DEFAULT_TIMEOUT) -> httpx.Client:
    return httpx.Client(headers=HEADERS, timeout=timeout, follow_redirects=False)


def _next(url: str, response: httpx.Response, body: bool) -> tuple[str, bool]:
    location = response.headers.get("location")
    if not location:
        raise httpx.TooManyRedirects(
            f"redirect without location from {url}", request=response.request)
    nxt = urljoin(url, location)
    keep = body and response.status_code in PRESERVE_BODY_CODES
    return check_url(nxt), keep


def request(c: httpx.Client, method: str, url: str,
            body: bool = False, **kwargs) -> httpx.Response:
    target = check_url(url)
    for _ in range(MAX_REDIRECTS + 1):
        r = c.request(method, target, **kwargs)
        if r.status_code not in REDIRECT_CODES or not r.is_redirect:
            return r
        target, keep = _next(target, r, body)
        if not keep:
            kwargs.pop("data", None)
            kwargs.pop("content", None)
            method = "GET"
    raise httpx.TooManyRedirects(f"more than {MAX_REDIRECTS} redirects from {url}")


def get(c: httpx.Client, url: str, **kwargs) -> httpx.Response:
    return request(c, "GET", url, **kwargs)


def post(c: httpx.Client, url: str, data: dict | None = None,
         **kwargs) -> httpx.Response:
    return request(c, "POST", url, body=True, data=data, **kwargs)


@contextmanager
def stream_get(url: str, timeout: float = DEFAULT_TIMEOUT) -> Iterator[httpx.Response]:
    target = check_url(url)
    with client(timeout=timeout) as c:
        for _ in range(MAX_REDIRECTS + 1):
            with c.stream("GET", target) as r:
                if r.status_code not in REDIRECT_CODES or not r.is_redirect:
                    yield r
                    return
                target, _ = _next(target, r, False)
        raise httpx.TooManyRedirects(f"more than {MAX_REDIRECTS} redirects from {url}")
