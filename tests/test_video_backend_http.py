"""The retry policy the paid backends share.

The distinction being tested is the one that costs money if it is wrong:
a 429 is safe to repeat on any method because the request was rejected
before it was processed, but an ambiguous failure on a POST must NOT be
repeated -- the generation may already have been accepted, and a retry
pays for a second one (docs/decisions/0067).
"""

import httpx
import pytest

from horror_video_ai.video_backends import _http
from horror_video_ai.video_backends._http import VideoBackendError, download, request_json


class _Response:
    def __init__(self, status_code, *, body=None, content=b"", headers=None):
        self.status_code = status_code
        self._body = body if body is not None else {}
        self.content = content
        self.headers = headers or {}
        self.text = str(self._body)

    def json(self):
        return self._body


def _record(responses, calls):
    def fake(method, url, **kwargs):
        calls.append(method)
        return responses.pop(0)

    return fake


def test_a_successful_call_returns_the_body(monkeypatch):
    monkeypatch.setattr(httpx, "request", _record([_Response(200, body={"ok": 1})], []))
    assert request_json("POST", "https://x", headers={}) == {"ok": 1}


def test_a_throttle_is_retried_even_on_a_post(monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(
        httpx,
        "request",
        _record([_Response(429, headers={"retry-after": "0"}), _Response(200, body={"ok": 1})],
                calls),
    )
    assert request_json("POST", "https://x", headers={}, sleep_fn=lambda _: None) == {"ok": 1}
    assert calls == ["POST", "POST"]


def test_a_server_error_is_NOT_retried_on_a_post(monkeypatch):
    """The request may already have started a paid generation."""
    calls: list[str] = []
    monkeypatch.setattr(
        httpx, "request", _record([_Response(500), _Response(200, body={"ok": 1})], calls)
    )
    with pytest.raises(VideoBackendError, match="HTTP 500"):
        request_json("POST", "https://x", headers={}, sleep_fn=lambda _: None)
    assert calls == ["POST"]


def test_a_server_error_IS_retried_on_a_get(monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(
        httpx, "request", _record([_Response(503), _Response(200, body={"ok": 1})], calls)
    )
    assert request_json("GET", "https://x", headers={}, sleep_fn=lambda _: None) == {"ok": 1}
    assert calls == ["GET", "GET"]


def test_a_dropped_connection_is_not_retried_on_a_post(monkeypatch):
    def boom(method, url, **kwargs):
        raise httpx.ConnectError("dropped")

    monkeypatch.setattr(httpx, "request", boom)
    with pytest.raises(VideoBackendError, match="dropped"):
        request_json("POST", "https://x", headers={}, sleep_fn=lambda _: None)


def test_a_dropped_connection_is_retried_on_a_get(monkeypatch):
    attempts = {"n": 0}

    def flaky(method, url, **kwargs):
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise httpx.ConnectError("dropped")
        return _Response(200, body={"ok": 1})

    monkeypatch.setattr(httpx, "request", flaky)
    assert request_json("GET", "https://x", headers={}, sleep_fn=lambda _: None) == {"ok": 1}


def test_a_non_object_body_fails_loud(monkeypatch):
    monkeypatch.setattr(httpx, "request", _record([_Response(200, body=[1, 2])], []))
    with pytest.raises(VideoBackendError, match="returned list"):
        request_json("GET", "https://x", headers={})


def test_retry_after_header_is_preferred_over_the_fallback(monkeypatch):
    waits: list[float] = []
    monkeypatch.setattr(
        httpx,
        "request",
        _record([_Response(429, headers={"retry-after": "1.5"}), _Response(200, body={})], []),
    )
    request_json("GET", "https://x", headers={}, sleep_fn=waits.append)
    assert waits == [1.5]


def test_an_unparseable_retry_after_falls_back(monkeypatch):
    waits: list[float] = []
    monkeypatch.setattr(
        httpx,
        "request",
        _record([_Response(429, headers={"retry-after": "soon"}), _Response(200, body={})], []),
    )
    request_json("GET", "https://x", headers={}, sleep_fn=waits.append)
    assert waits == [_http._FALLBACK_RETRY_DELAY_SECONDS]


def test_download_returns_the_bytes(monkeypatch):
    monkeypatch.setattr(httpx, "get", lambda url, **kwargs: _Response(200, content=b"mp4"))
    assert download("https://x/v.mp4") == b"mp4"


def test_download_refuses_an_empty_body(monkeypatch):
    """Better to fail than to write a zero-byte file over a clip that has
    already been paid for."""
    monkeypatch.setattr(httpx, "get", lambda url, **kwargs: _Response(200, content=b""))
    with pytest.raises(VideoBackendError, match="was empty"):
        download("https://x/v.mp4")


def test_download_retries_a_transient_failure(monkeypatch):
    attempts = {"n": 0}

    def flaky(url, **kwargs):
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise httpx.ConnectError("dropped")
        return _Response(200, content=b"mp4")

    monkeypatch.setattr(httpx, "get", flaky)
    assert download("https://x/v.mp4", sleep_fn=lambda _: None) == b"mp4"


def test_download_gives_up_on_a_permanent_failure(monkeypatch):
    monkeypatch.setattr(httpx, "get", lambda url, **kwargs: _Response(404))
    with pytest.raises(VideoBackendError, match="HTTP 404"):
        download("https://x/v.mp4", sleep_fn=lambda _: None)
