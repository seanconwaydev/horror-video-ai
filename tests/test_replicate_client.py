import base64

import pytest

from historical_video_ai.replicate_client import (
    API_BASE,
    ReplicateError,
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
