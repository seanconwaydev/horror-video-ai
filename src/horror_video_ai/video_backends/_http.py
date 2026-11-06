"""Shared HTTP for the direct-vendor video backends.

Carries the same retry reasoning `replicate_client.py` arrived at the hard
way (docs/decisions/0067), because it is a property of paid generation
APIs rather than of Replicate:

- A 429 is safe to repeat on ANY method. It means the request was rejected
  before it was processed, so a retry cannot duplicate work.
- Every other retryable failure -- a 5xx, a 408, a dropped connection --
  is ambiguous: the request may have been accepted and only the response
  lost. Repeating those on a POST that creates a generation starts a
  second paid job while the first runs on, orphaned and billed. So they
  are retried only on methods that change nothing.
- The download retry matters most and is the easiest to forget. By then
  the video is generated, paid for and polled through; a dropped
  connection there discards work that cannot be recovered.

`replicate_client.py` predates this module and keeps its own copy; it is
on the existing Wan-on-Replicate path and is left alone deliberately.
"""

from __future__ import annotations

import ssl
import time
from collections.abc import Callable

import httpx

_TIMEOUT_SECONDS = 60.0
_THROTTLE_STATUS = 429
_RETRYABLE_STATUSES = frozenset({408, 429, 500, 502, 503, 504})
_SAFE_TO_REPEAT_METHODS = frozenset({"GET", "HEAD"})
_MAX_RETRIES = 5
_FALLBACK_RETRY_DELAY_SECONDS = 5.0


class VideoBackendError(Exception):
    """Raised when a backend call fails, times out, or returns something
    malformed -- the same fail-loud convention as ConfigError and every
    stage's own error type."""


def _is_retryable(method: str, *, status: int | None) -> bool:
    """`status=None` means the call raised rather than returned -- a
    dropped connection or a TLS error."""
    repeatable = method.upper() in _SAFE_TO_REPEAT_METHODS
    if status is None:
        return repeatable
    if status == _THROTTLE_STATUS:
        return True
    return repeatable and status in _RETRYABLE_STATUSES


def _retry_delay(response: httpx.Response) -> float:
    """Prefer the delay the API itself names -- telling you when the
    window reopens is the entire point of a throttle response."""
    header = response.headers.get("retry-after")
    if header:
        try:
            return float(header)
        except ValueError:
            pass
    return _FALLBACK_RETRY_DELAY_SECONDS


def request_json(
    method: str,
    url: str,
    *,
    headers: dict[str, str],
    json_body: dict | None = None,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> dict:
    """One JSON API call, retried per the policy above. The injection
    point for tests is the backend's own `request_fn` parameter, which
    defaults to this -- so no test needs the network."""
    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            response = httpx.request(
                method, url, headers=headers, json=json_body, timeout=_TIMEOUT_SECONDS
            )
        except (httpx.TransportError, ssl.SSLError) as exc:
            if not _is_retryable(method, status=None) or attempt == _MAX_RETRIES:
                raise VideoBackendError(f"{method} {url} failed: {exc}") from exc
            sleep_fn(_FALLBACK_RETRY_DELAY_SECONDS)
            continue
        if response.status_code < 400:
            result = response.json()
            if not isinstance(result, dict):
                raise VideoBackendError(f"{method} {url} returned {type(result).__name__}")
            return result
        if not _is_retryable(method, status=response.status_code) or attempt == _MAX_RETRIES:
            raise VideoBackendError(
                f"{method} {url} failed with HTTP {response.status_code}: {response.text}"
            )
        sleep_fn(_retry_delay(response))
    raise AssertionError("unreachable")  # the loop always returns or raises


def download(url: str, *, sleep_fn: Callable[[float], None] = time.sleep) -> bytes:
    """Fetch a finished video, failing loud on an empty body rather than
    writing a zero-byte file. Retried on every attempt -- a GET of a
    static object has no consequence to repeat, and by this point the
    generation has already been paid for."""
    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            response = httpx.get(url, timeout=_TIMEOUT_SECONDS, follow_redirects=True)
        except (httpx.TransportError, ssl.SSLError) as exc:
            if attempt == _MAX_RETRIES:
                raise VideoBackendError(f"Downloading {url} failed: {exc}") from exc
            sleep_fn(_FALLBACK_RETRY_DELAY_SECONDS)
            continue
        if response.status_code < 400:
            if not response.content:
                raise VideoBackendError(f"Video at {url} was empty.")
            return response.content
        if not _is_retryable("GET", status=response.status_code) or attempt == _MAX_RETRIES:
            raise VideoBackendError(f"Downloading {url} failed: HTTP {response.status_code}")
        sleep_fn(_retry_delay(response))
    raise AssertionError("unreachable")  # the loop always returns or raises
