import base64

import httpx
import pytest

from historical_video_ai.replicate_client import (
    API_BASE,
    ReplicateError,
    _default_request_fn,
    download_output,
    file_to_data_uri,
    resolve_api_token,
    run_prediction,
)


def _request_fn(responses, record=None):
    """Returns each queued response in turn, recording every call."""
    queue = list(responses)

    def _fn(method, url, *, headers, json_body):
        if record is not None:
            record.append({"method": method, "url": url, "headers": headers, "json": json_body})
        return queue.pop(0)

    return _fn


def _no_sleep(_seconds):
    return None


def test_resolve_api_token_prefers_explicit_value_over_environment(monkeypatch):
    monkeypatch.setenv("REPLICATE_API_TOKEN", "from-env")
    assert resolve_api_token("explicit") == "explicit"
    assert resolve_api_token() == "from-env"


def test_resolve_api_token_raises_a_setup_shaped_error_when_unset(monkeypatch):
    monkeypatch.delenv("REPLICATE_API_TOKEN", raising=False)
    with pytest.raises(ReplicateError, match="REPLICATE_API_TOKEN is not set"):
        resolve_api_token()


def test_file_to_data_uri_encodes_contents_with_a_guessed_media_type(tmp_path):
    path = tmp_path / "frame.png"
    path.write_bytes(b"some bytes")

    uri = file_to_data_uri(path)

    assert uri.startswith("data:image/png;base64,")
    assert base64.b64decode(uri.split(",", 1)[1]) == b"some bytes"


def test_file_to_data_uri_raises_for_a_missing_file(tmp_path):
    with pytest.raises(ReplicateError, match="File not found"):
        file_to_data_uri(tmp_path / "nope.png")


def test_run_prediction_posts_to_the_official_model_endpoint(monkeypatch):
    monkeypatch.setenv("REPLICATE_API_TOKEN", "tok")
    calls = []
    run_prediction(
        "owner/name",
        {"prompt": "hi"},
        request_fn=_request_fn([{"id": "p1", "status": "succeeded"}], record=calls),
        sleep_fn=_no_sleep,
    )

    assert calls[0]["method"] == "POST"
    assert calls[0]["url"] == f"{API_BASE}/models/owner/name/predictions"
    assert calls[0]["json"] == {"input": {"prompt": "hi"}}
    assert calls[0]["headers"]["Authorization"] == "Bearer tok"


def test_run_prediction_polls_until_a_terminal_status(monkeypatch):
    monkeypatch.setenv("REPLICATE_API_TOKEN", "tok")
    calls = []
    result = run_prediction(
        "owner/name",
        {},
        request_fn=_request_fn(
            [
                {"id": "p1", "status": "starting"},
                {"id": "p1", "status": "processing"},
                {"id": "p1", "status": "succeeded", "output": "url"},
            ],
            record=calls,
        ),
        sleep_fn=_no_sleep,
    )

    assert result["output"] == "url"
    assert [c["method"] for c in calls] == ["POST", "GET", "GET"]
    assert calls[1]["url"] == f"{API_BASE}/predictions/p1"


@pytest.mark.parametrize("status", ["failed", "canceled", "cancelled"])
def test_run_prediction_raises_on_a_terminal_failure_status(monkeypatch, status):
    monkeypatch.setenv("REPLICATE_API_TOKEN", "tok")
    with pytest.raises(ReplicateError, match="boom"):
        run_prediction(
            "owner/name",
            {},
            request_fn=_request_fn([{"id": "p1", "status": status, "error": "boom"}]),
            sleep_fn=_no_sleep,
        )


def test_run_prediction_raises_when_the_response_has_no_id(monkeypatch):
    monkeypatch.setenv("REPLICATE_API_TOKEN", "tok")
    with pytest.raises(ReplicateError, match="had no id"):
        run_prediction(
            "owner/name",
            {},
            request_fn=_request_fn([{"status": "starting"}]),
            sleep_fn=_no_sleep,
        )


def test_run_prediction_gives_up_after_max_poll_attempts(monkeypatch):
    monkeypatch.setenv("REPLICATE_API_TOKEN", "tok")
    forever = [{"id": "p1", "status": "processing"} for _ in range(10)]
    with pytest.raises(ReplicateError, match="did not finish after 3 polling attempts"):
        run_prediction(
            "owner/name",
            {},
            request_fn=_request_fn(forever),
            sleep_fn=_no_sleep,
            max_poll_attempts=3,
        )


def test_download_output_returns_content_and_rejects_an_empty_body():
    assert download_output("http://x/y", download_fn=lambda url: b"bytes") == b"bytes"

    with pytest.raises(ReplicateError, match="was empty"):
        download_output("http://x/y", download_fn=lambda url: b"")


# --- throttling and transient transport errors (ADR 0045) ---


class _FakeResponse:
    def __init__(self, status_code, payload=None, headers=None, text=""):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.headers = headers or {}
        self.text = text

    def json(self):
        return self._payload


def test_request_retries_a_throttle_and_waits_what_the_api_says(monkeypatch):
    """Replicate drops to 6 requests/minute with a burst of 1 below $5 of
    credit. A real run lost 6 of 10 images to that, and the API itself says
    when the window reopens -- so wait that long rather than guessing."""
    responses = iter(
        [
            _FakeResponse(429, {"retry_after": 3, "detail": "throttled"}),
            _FakeResponse(429, {"retry_after": 2, "detail": "throttled"}),
            _FakeResponse(200, {"id": "p1", "status": "succeeded"}),
        ]
    )
    monkeypatch.setattr(
        "historical_video_ai.replicate_client.httpx.request", lambda *a, **k: next(responses)
    )
    slept = []

    result = _default_request_fn(
        "POST", "http://x", headers={}, json_body=None, sleep_fn=slept.append
    )

    assert result == {"id": "p1", "status": "succeeded"}
    assert slept == [3.0, 2.0], "should wait exactly what the API asked for"


def test_request_prefers_the_retry_after_header_over_the_body(monkeypatch):
    responses = iter(
        [
            _FakeResponse(429, {"retry_after": 99}, headers={"retry-after": "4"}),
            _FakeResponse(200, {"ok": True}),
        ]
    )
    monkeypatch.setattr(
        "historical_video_ai.replicate_client.httpx.request", lambda *a, **k: next(responses)
    )
    slept = []

    _default_request_fn("GET", "http://x", headers={}, json_body=None, sleep_fn=slept.append)

    assert slept == [4.0]


def test_request_does_not_retry_a_client_error(monkeypatch):
    """A 404 or a bad payload will fail identically forever -- retrying it
    just delays the error."""
    calls = {"n": 0}

    def _once(*a, **k):
        calls["n"] += 1
        return _FakeResponse(404, text="no such model")

    monkeypatch.setattr("historical_video_ai.replicate_client.httpx.request", _once)

    with pytest.raises(ReplicateError, match="404"):
        _default_request_fn("GET", "http://x", headers={}, json_body=None, sleep_fn=lambda _s: None)
    assert calls["n"] == 1


def test_request_gives_up_after_the_retry_budget(monkeypatch):
    monkeypatch.setattr(
        "historical_video_ai.replicate_client.httpx.request",
        lambda *a, **k: _FakeResponse(429, {"retry_after": 1}, text="throttled"),
    )
    with pytest.raises(ReplicateError, match="429"):
        _default_request_fn("GET", "http://x", headers={}, json_body=None, sleep_fn=lambda _s: None)


def test_request_retries_a_transport_failure_not_just_a_status_code(monkeypatch):
    """A transport failure raises rather than returning a status, so
    retrying status codes alone missed it. Observed repeatedly as
    "[SSL: SSLV3_ALERT_BAD_RECORD_MAC] ssl/tls alert bad record mac", which
    killed two images of a paid batch after the status-code retry was
    already in place."""
    calls = {"n": 0}

    def _flaky(*a, **k):
        calls["n"] += 1
        if calls["n"] == 1:
            raise httpx.ConnectError("bad record mac")
        return _FakeResponse(200, {"id": "p1"})

    monkeypatch.setattr("historical_video_ai.replicate_client.httpx.request", _flaky)
    slept = []

    result = _default_request_fn(
        "POST", "http://x", headers={}, json_body=None, sleep_fn=slept.append
    )

    assert result == {"id": "p1"}
    assert calls["n"] == 2
    assert slept, "should have waited before retrying"


def test_request_gives_up_on_a_persistent_transport_failure(monkeypatch):
    def _always_fails(*a, **k):
        raise httpx.ConnectError("bad record mac")

    monkeypatch.setattr("historical_video_ai.replicate_client.httpx.request", _always_fails)

    with pytest.raises(ReplicateError, match="bad record mac"):
        _default_request_fn("GET", "http://x", headers={}, json_body=None, sleep_fn=lambda _s: None)
