"""Kling v3 via Kuaishou's own developer API, not an aggregator.

This is the model that produced the one short worth watching so far, and
the reason for going direct is measured: the same 15 seconds cost $5 on
Replicate against a ~$2.52 list price.

**The wire format here is UNVERIFIED against a live account.** Everything
below is written to Kling's documented scheme, but nothing in this module
has been exercised against the real API, because access needs a prepaid
package. Treat the first live call as a probe, not as a working path, and
expect to correct `_build_payload` and `_extract_video_url`. Two things
carried over from the Replicate wrapper ARE verified, because a real
prediction was rejected for violating them:

- `multi_prompt` is a JSON-encoded STRING, not an array, and the shot
  durations must sum to exactly `duration`.
- **Each shot's prompt is capped at 512 characters.** This is
  undocumented -- the published limit of 2500 applies to the single
  top-level `prompt` -- and it is not reported until after the generation
  has been created.

Commercial note worth keeping next to the code: the developer API is
prepaid. A $9.80 trial covers 100 units for 30 days; the next tier is
$700 for 5,000 units, expiring after 180 days with no rollover. Failed
tasks do not consume credits.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from collections.abc import Callable
from typing import Any

from horror_video_ai.stages.shot_writing import ShotList
from horror_video_ai.video_backends._http import VideoBackendError, download, request_json
from horror_video_ai.video_backends.base import PORTRAIT_9_16, GeneratedVideo

API_BASE = "https://api-singapore.klingai.com"

MAX_SHOTS = 6
MAX_TOTAL_SECONDS = 15
MAX_SHOT_PROMPT_CHARS = 512

_POLL_INTERVAL_SECONDS = 10.0
_MAX_POLL_ATTEMPTS = 180
_TOKEN_LIFETIME_SECONDS = 1800

# Kling bills in "resource units" rather than seconds; $0.14 list per unit.
# Kept here rather than in litellm's table because litellm has no entry
# for Kling at all, and a bake-off still needs a number to compare.
_LIST_PRICE_PER_SECOND_USD = 0.168


def _sign_jwt(access_key: str, secret_key: str, *, now: int | None = None) -> str:
    """Kling authenticates with an HS256 JWT signed by the secret key.

    Hand-rolled rather than adding a JWT dependency for twelve lines: the
    header and claims are fixed, and this project does not otherwise need
    one.
    """
    issued = int(time.time()) if now is None else now
    header = {"alg": "HS256", "typ": "JWT"}
    claims = {"iss": access_key, "exp": issued + _TOKEN_LIFETIME_SECONDS, "nbf": issued - 5}

    def segment(payload: dict[str, Any]) -> bytes:
        raw = json.dumps(payload, separators=(",", ":")).encode()
        return base64.urlsafe_b64encode(raw).rstrip(b"=")

    signing_input = segment(header) + b"." + segment(claims)
    signature = hmac.new(secret_key.encode(), signing_input, hashlib.sha256).digest()
    return (signing_input + b"." + base64.urlsafe_b64encode(signature).rstrip(b"=")).decode()


_MISSING_CREDENTIALS = (
    "KLING_ACCESS_KEY and KLING_SECRET_KEY are not both set -- add them to "
    ".env (see .env.example). Kling's developer API is prepaid and separate "
    "from any consumer subscription."
)


def credentials_problem() -> str | None:
    """Why this backend cannot be called, or None when it can.

    Read by `validate()` so a missing key takes the backend out of a
    bake-off before the spend prompt. Without it the run confirms a total
    that includes this backend, pays the ones ahead of it in the order,
    and only then raises.
    """
    if os.environ.get("KLING_ACCESS_KEY") and os.environ.get("KLING_SECRET_KEY"):
        return None
    return _MISSING_CREDENTIALS


def resolve_credentials(
    access_key: str | None = None, secret_key: str | None = None
) -> tuple[str, str]:
    """Fail loud on missing credentials rather than sending an
    unauthenticated request and surfacing a 401 -- a missing key is a
    setup problem and should say so in those terms."""
    access = access_key or os.environ.get("KLING_ACCESS_KEY")
    secret = secret_key or os.environ.get("KLING_SECRET_KEY")
    if not access or not secret:
        raise VideoBackendError(_MISSING_CREDENTIALS)
    return access, secret


class KlingBackend:
    """Kling v3: a whole multi-shot short in a single call, with audio."""

    supports_multishot = True
    max_seconds_per_call = MAX_TOTAL_SECONDS

    def __init__(
        self,
        model: str,
        *,
        mode: str = "pro",
        request_fn: Callable[..., dict] = request_json,
        download_fn: Callable[[str], bytes] = download,
        sleep_fn: Callable[[float], None] = time.sleep,
    ) -> None:
        self.name = "kling"
        # Strip the config's "<provider>/" prefix -- docs/decisions/0003
        # requires that shape in models.yaml, but Kling's own API expects a
        # bare model name, the same split replicate_client.py already makes.
        self.model = model.removeprefix("kling/")
        self.mode = mode
        self._request_fn = request_fn
        self._download_fn = download_fn
        self._sleep_fn = sleep_fn

    def validate(self, shot_list: ShotList) -> list[str]:
        problems = []
        missing = credentials_problem()
        if missing is not None:
            problems.append(missing)
        if len(shot_list.shots) > MAX_SHOTS:
            problems.append(f"{len(shot_list.shots)} shots -- Kling accepts at most {MAX_SHOTS}")
        if shot_list.total_seconds > MAX_TOTAL_SECONDS:
            problems.append(
                f"{shot_list.total_seconds}s total -- Kling's ceiling is {MAX_TOTAL_SECONDS}s"
            )
        for index, shot in enumerate(shot_list.shots, start=1):
            length = len(f"{shot_list.look} {shot.prompt}")
            if length > MAX_SHOT_PROMPT_CHARS:
                problems.append(
                    f"shot {index} is {length} characters with the look prepended -- each "
                    f"shot is capped at {MAX_SHOT_PROMPT_CHARS}, and Kling only says so "
                    "after the generation has been created"
                )
            if shot.duration_seconds < 1:
                problems.append(f"shot {index} is under Kling's 1 second minimum")
        return problems

    def estimate_cost_usd(self, seconds: int) -> float | None:
        return _LIST_PRICE_PER_SECOND_USD * seconds

    def build_payload(self, shot_list: ShotList, *, aspect_ratio: str) -> dict[str, Any]:
        """The exact request body. Separated so a test can assert it
        without a network call, and so the one place needing correction
        after the first live probe is obvious."""
        shots = [
            {
                "prompt": f"{shot_list.look} {shot.prompt}",
                "duration": shot.duration_seconds,
            }
            for shot in shot_list.shots
        ]
        return {
            "model_name": self.model,
            "mode": self.mode,
            "prompt": shots[0]["prompt"],
            "multi_prompt": json.dumps(shots),
            "duration": shot_list.total_seconds,
            "aspect_ratio": aspect_ratio,
            "generate_audio": True,
            "negative_prompt": shot_list.negative_prompt,
        }

    def generate(
        self, shot_list: ShotList, *, aspect_ratio: str = PORTRAIT_9_16
    ) -> GeneratedVideo:
        access, secret = resolve_credentials()
        headers = {
            "Authorization": f"Bearer {_sign_jwt(access, secret)}",
            "Content-Type": "application/json",
        }
        payload = self.build_payload(shot_list, aspect_ratio=aspect_ratio)
        created = self._request_fn(
            "POST", f"{API_BASE}/v1/videos/text2video", headers=headers, json_body=payload
        )
        task_id = (created.get("data") or {}).get("task_id")
        if not task_id:
            raise VideoBackendError(f"Kling returned no task id: {created!r}")

        status = ""
        attempts = 0
        result: dict[str, Any] = created
        while status not in {"succeed", "failed"}:
            attempts += 1
            if attempts > _MAX_POLL_ATTEMPTS:
                raise VideoBackendError(
                    f"Kling task {task_id} did not finish after {_MAX_POLL_ATTEMPTS} polls"
                )
            self._sleep_fn(_POLL_INTERVAL_SECONDS)
            result = self._request_fn(
                "GET",
                f"{API_BASE}/v1/videos/text2video/{task_id}",
                headers=headers,
                json_body=None,
            )
            status = str((result.get("data") or {}).get("task_status", ""))
        if status == "failed":
            raise VideoBackendError(
                f"Kling task {task_id} failed: {(result.get('data') or {}).get('task_status_msg')}"
            )
        return GeneratedVideo(
            data=self._download_fn(_extract_video_url(result)),
            backend=self.name,
            seconds=shot_list.total_seconds,
            request_payloads=[payload],
        )


def _extract_video_url(result: dict[str, Any]) -> str:
    videos = ((result.get("data") or {}).get("task_result") or {}).get("videos") or []
    if not videos or not videos[0].get("url"):
        raise VideoBackendError(f"Kling returned no video url: {result!r}")
    return str(videos[0]["url"])
