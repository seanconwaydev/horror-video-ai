"""Minimal Replicate REST client -- the one place this project talks to a
model provider without going through litellm.

Deliberate, scoped exception to docs/decisions/0003's "everything through
litellm" convention: litellm has no video-generation support for Replicate
(confirmed against 1.100.1 by reading its source -- only OpenAI, Azure,
Gemini, Vertex AI and RunwayML are wired up). See docs/decisions/0037 for
the decision and docs/decisions/0038 for this implementation.

Replicate's prediction API is async: create a prediction, poll it to a
terminal status, then fetch the output file from the URL it returns.
Official models (`is_official: true`, which wan-video/wan-2.2-i2v-fast is)
are created at /v1/models/{owner}/{name}/predictions and always run the
model's current version -- community models instead require posting a
pinned version id to /v1/predictions.
"""

from __future__ import annotations

import base64
import mimetypes
import os
import time
from collections.abc import Callable
from pathlib import Path

import httpx

API_BASE = "https://api.replicate.com/v1"

_TERMINAL_SUCCESS_STATUS = "succeeded"
_TERMINAL_FAILURE_STATUSES = {"failed", "canceled", "cancelled"}

# Replicate cold-starts a model's hardware on demand, so the first call
# after an idle period is much slower than a warm one. Polling is cheap
# (a plain GET), so this favours a short interval over a long one.
_DEFAULT_POLL_INTERVAL_SECONDS = 5.0
_DEFAULT_MAX_POLL_ATTEMPTS = 120

_DEFAULT_TIMEOUT_SECONDS = 60.0


class ReplicateError(Exception):
    """Raised when a Replicate call fails, times out, or returns a
    malformed response -- same fail-loud convention as ConfigError and
    every stage's own error type."""


def resolve_api_token(api_token: str | None = None) -> str:
    """Return the Replicate API token, failing loud if it isn't set.

    Explicit rather than letting httpx send an unauthenticated request
    and surface a 401 -- a missing key is a setup problem and should say
    so in those terms.
    """
    token = api_token or os.environ.get("REPLICATE_API_TOKEN")
    if not token:
        raise ReplicateError(
            "REPLICATE_API_TOKEN is not set -- add it to .env (see .env.example). "
            "Video generation calls Replicate directly, not through litellm "
            "(docs/decisions/0037)."
        )
    return token


def _default_request_fn(
    method: str, url: str, *, headers: dict[str, str], json_body: dict | None
) -> dict:
    """Perform one JSON API call. Injection point for tests -- every
    function below takes this as a parameter rather than importing httpx
    directly, so no test ever needs the network."""
    response = httpx.request(
        method, url, headers=headers, json=json_body, timeout=_DEFAULT_TIMEOUT_SECONDS
    )
    if response.status_code >= 400:
        raise ReplicateError(
            f"Replicate {method} {url} failed with HTTP {response.status_code}: {response.text}"
        )
    return response.json()


def _default_download_fn(url: str) -> bytes:
    """Fetch a finished prediction's output file. Separate seam from
    `_default_request_fn` because this returns raw bytes from Replicate's
    CDN, not JSON from the API."""
    response = httpx.get(url, timeout=_DEFAULT_TIMEOUT_SECONDS, follow_redirects=True)
    if response.status_code >= 400:
        raise ReplicateError(
            f"Downloading prediction output from {url} failed with HTTP {response.status_code}"
        )
    return response.content


def file_to_data_uri(path: Path) -> str:
    """Encode a local file as a data: URI for Replicate's file inputs.

    Replicate accepts either a public URL or a data URI for `uri`-format
    inputs. A data URI avoids needing to upload the image anywhere first,
    which matters because previz images only ever exist on local disk.
    """
    if not path.exists():
        raise ReplicateError(f"File not found: {path}")
    media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{media_type};base64,{encoded}"


def run_prediction(
    model: str,
    input_payload: dict,
    *,
    api_token: str | None = None,
    request_fn: Callable = _default_request_fn,
    sleep_fn: Callable[[float], None] = time.sleep,
    poll_interval_seconds: float = _DEFAULT_POLL_INTERVAL_SECONDS,
    max_poll_attempts: int = _DEFAULT_MAX_POLL_ATTEMPTS,
) -> dict:
    """Create a prediction for `model` ("owner/name") and poll it to a
    terminal status, returning the finished prediction object.

    Raises ReplicateError if the prediction has no id, ends in a failure
    status, or never reaches a terminal status within `max_poll_attempts`
    -- rather than returning a half-finished object for the caller to
    misinterpret.
    """
    headers = {
        "Authorization": f"Bearer {resolve_api_token(api_token)}",
        "Content-Type": "application/json",
    }

    prediction = request_fn(
        "POST",
        f"{API_BASE}/models/{model}/predictions",
        headers=headers,
        json_body={"input": input_payload},
    )

    prediction_id = prediction.get("id")
    if not prediction_id:
        raise ReplicateError(f"Replicate prediction response had no id: {prediction!r}")

    status = prediction.get("status")
    attempts = 0
    while status != _TERMINAL_SUCCESS_STATUS and status not in _TERMINAL_FAILURE_STATUSES:
        attempts += 1
        if attempts > max_poll_attempts:
            raise ReplicateError(
                f"Replicate prediction {prediction_id} did not finish after "
                f"{max_poll_attempts} polling attempts (last status: {status!r})."
            )
        sleep_fn(poll_interval_seconds)
        prediction = request_fn(
            "GET", f"{API_BASE}/predictions/{prediction_id}", headers=headers, json_body=None
        )
        status = prediction.get("status")

    if status in _TERMINAL_FAILURE_STATUSES:
        raise ReplicateError(
            f"Replicate prediction {prediction_id} ended with status {status!r}: "
            f"{prediction.get('error')}"
        )

    return prediction


def download_output(url: str, *, download_fn: Callable[[str], bytes] = _default_download_fn) -> bytes:
    """Fetch a finished prediction's output file, failing loud on an
    empty body rather than writing a zero-byte file to disk."""
    content = download_fn(url)
    if not content:
        raise ReplicateError(f"Prediction output at {url} was empty.")
    return content
