"""Video backends: payload construction and limit checks, no network.

Every backend takes an injectable request/generation seam, so nothing
here needs a key or a connection. The payloads are asserted rather than
the responses, because a wrong payload is what actually costs money --
two of these rules were learned from a rejected paid generation.
"""

from types import SimpleNamespace

import pytest

from horror_video_ai.stages.shot_writing import Shot, ShotList
from horror_video_ai.video_backends import build_backend
from horror_video_ai.video_backends._http import VideoBackendError
from horror_video_ai.video_backends.base import cost_per_second
from horror_video_ai.video_backends.kling import KlingBackend, _sign_jwt
from horror_video_ai.video_backends.veo import VeoBackend, snap_seconds
from horror_video_ai.video_backends.wan import WanBackend

LOOK = "IR night-vision security cam, locked off high in a corner. Camera static."

_KEYS = ("GEMINI_API_KEY", "KLING_ACCESS_KEY", "KLING_SECRET_KEY", "DASHSCOPE_API_KEY")


@pytest.fixture(autouse=True)
def _credentials(monkeypatch):
    """Every backend's validate() now reports a missing key, so the limit
    tests below would otherwise be asserting on the developer's own .env.
    The credential checks themselves clear these explicitly."""
    for key in _KEYS:
        monkeypatch.setenv(key, "test-value")


def _shots(count=4, seconds=4, prompt="A door creeps open. Audio: hiss."):
    return ShotList(
        shots=[Shot(prompt=prompt, duration_seconds=seconds) for _ in range(count)],
        look=LOOK,
        negative_prompt="nude, naked, on-screen text",
    )


# --- Kling -----------------------------------------------------------------


def test_kling_payload_encodes_multi_prompt_as_a_json_string():
    """Verified the hard way: a real prediction was rejected because this
    is a string, not an array."""
    backend = KlingBackend("kling/kling-v3")
    payload = backend.build_payload(_shots(), aspect_ratio="9:16")
    assert isinstance(payload["multi_prompt"], str)
    assert payload["duration"] == 16
    assert payload["aspect_ratio"] == "9:16"
    assert payload["generate_audio"] is True
    assert payload["model_name"] == "kling-v3"  # provider prefix stripped


def test_kling_rejects_a_shot_over_512_characters():
    """Undocumented cap. The published 2500 applies to the top-level
    prompt only, and Kling does not say so until after the generation has
    been created and charged for."""
    backend = KlingBackend("kling/kling-v3")
    problems = backend.validate(_shots(count=1, prompt="x" * 600))
    assert any("512" in p for p in problems)


def test_kling_counts_the_look_toward_the_limit():
    backend = KlingBackend("kling/kling-v3")
    just_under = "y" * (512 - len(LOOK) - 1)
    assert backend.validate(_shots(count=1, prompt=just_under)) == []
    assert backend.validate(_shots(count=1, prompt=just_under + "zz"))


def test_kling_rejects_too_many_shots_and_too_long_a_runtime():
    backend = KlingBackend("kling/kling-v3")
    problems = backend.validate(_shots(count=8, seconds=3))
    assert any("at most 6" in p for p in problems)
    assert any("ceiling is 15s" in p for p in problems)


def test_kling_jwt_is_three_dot_separated_segments():
    token = _sign_jwt("access", "secret", now=1_000_000)
    assert token.count(".") == 2
    assert _sign_jwt("access", "secret", now=1_000_000) == token
    assert _sign_jwt("access", "other", now=1_000_000) != token


def test_kling_missing_credentials_fail_loud(monkeypatch):
    monkeypatch.delenv("KLING_ACCESS_KEY", raising=False)
    monkeypatch.delenv("KLING_SECRET_KEY", raising=False)
    with pytest.raises(VideoBackendError, match="KLING_ACCESS_KEY"):
        KlingBackend("kling/kling-v3").generate(_shots())


# --- Veo -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("asked", "expected"),
    [(1, 4), (3, 4), (4, 4), (5, 4), (6, 6), (7, 6), (8, 8), (12, 8)],
)
def test_veo_snaps_to_a_duration_it_actually_accepts(asked, expected):
    """Veo takes 4, 6 or 8 seconds and nothing else. Ties go to the
    shorter so a snap never silently costs more than was asked for."""
    assert snap_seconds(asked) == expected


def test_veo_uses_a_portrait_size_litellm_maps_to_9_16():
    """litellm maps size to aspectRatio through a fixed table; anything
    outside it silently becomes 16:9, which for a vertical short is a
    ruined generation."""
    sent = {}

    def fake_generation(**kwargs):
        sent.update(kwargs)
        return SimpleNamespace(id="vid_1", status="completed")

    backend = VeoBackend(
        "gemini/veo-3.1-fast-generate-preview",
        generation_fn=fake_generation,
        content_fn=lambda **kwargs: b"mp4",
        sleep_fn=lambda _: None,
    )
    backend.generate(_shots(count=1))
    assert sent["size"] == "720x1280"
    assert sent["seconds"] == "4"
    assert "nude" in sent["negativePrompt"]


def test_veo_notes_when_snapping_changes_the_runtime():
    backend = VeoBackend("gemini/veo-3.1-fast-generate-preview")
    problems = backend.validate(_shots(count=4, seconds=3))
    assert any("rather than" in p and p.startswith("note:") for p in problems)


def test_veo_rejects_a_landscape_request():
    backend = VeoBackend("gemini/veo-3.1-fast-generate-preview")
    with pytest.raises(VideoBackendError, match="9:16"):
        backend.generate(_shots(count=1), aspect_ratio="16:9")


def test_veo_fails_loud_when_a_generation_fails():
    backend = VeoBackend(
        "gemini/veo-3.1-fast-generate-preview",
        generation_fn=lambda **kwargs: SimpleNamespace(id="v", status="failed", error="nope"),
        sleep_fn=lambda _: None,
    )
    with pytest.raises(VideoBackendError, match="failed"):
        backend.generate(_shots(count=1))


def test_veo_cost_comes_from_litellms_price_table():
    backend = VeoBackend("gemini/veo-3.1-fast-generate-preview")
    cost = backend.estimate_cost_usd(15)
    assert cost is not None and cost > 0
    assert cost_per_second("gemini/not-a-real-model") is None


# --- Wan -------------------------------------------------------------------


def test_wan_payload_uses_dashscope_shape_and_strips_the_prefix():
    backend = WanBackend("dashscope/wan2.7-t2v-plus")
    payload = backend.build_payload(_shots(count=2, seconds=4), aspect_ratio="9:16")
    assert payload["model"] == "wan2.7-t2v-plus"
    assert "prompt" in payload["input"]
    assert payload["parameters"]["size"] == "720*1280"
    assert payload["parameters"]["duration"] == 8


def test_wan_notes_that_it_has_no_cuts():
    problems = WanBackend("dashscope/wan2.7-t2v-plus").validate(_shots(count=4, seconds=2))
    assert any("no multi-shot" in p for p in problems)


def test_wan_missing_key_fails_loud(monkeypatch):
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    with pytest.raises(VideoBackendError, match="DASHSCOPE_API_KEY"):
        WanBackend("dashscope/wan2.7-t2v-plus").generate(_shots(count=1))


# --- Selection -------------------------------------------------------------


def test_build_backend_rejects_an_unknown_name():
    with pytest.raises(VideoBackendError, match="Unknown backend"):
        build_backend("sora")


def test_build_backend_reads_the_pinned_models():
    assert build_backend("veo").model.startswith("gemini/")
    assert build_backend("kling").model == "kling-v3"
    assert build_backend("wan").model == "wan2.7-t2v-plus"


# --- Generate and poll loops ------------------------------------------------


@pytest.fixture
def kling_env(monkeypatch):
    """Kling resolves credentials before it builds a request, so a
    generate test needs them present even though nothing is sent."""
    monkeypatch.setenv("KLING_ACCESS_KEY", "access")
    monkeypatch.setenv("KLING_SECRET_KEY", "secret")


def _responder(pages):
    """A request_fn returning each queued response in turn."""
    queue = list(pages)

    def fake(method, url, *, headers, json_body=None):
        return queue.pop(0) if len(queue) > 1 else queue[0]

    return fake


def test_kling_generate_polls_to_success_and_downloads(kling_env):
    backend = KlingBackend(
        "kling/kling-v3",
        request_fn=_responder(
            [
                {"data": {"task_id": "t1"}},
                {"data": {"task_id": "t1", "task_status": "processing"}},
                {
                    "data": {
                        "task_id": "t1",
                        "task_status": "succeed",
                        "task_result": {"videos": [{"url": "https://example/v.mp4"}]},
                    }
                },
            ]
        ),
        download_fn=lambda url: b"kling-bytes",
        sleep_fn=lambda _: None,
    )
    video = backend.generate(_shots(count=2))
    assert video.data == b"kling-bytes"
    assert video.backend == "kling"
    assert video.request_payloads


def test_kling_generate_raises_when_the_task_fails(kling_env):
    backend = KlingBackend(
        "kling/kling-v3",
        request_fn=_responder(
            [
                {"data": {"task_id": "t1"}},
                {"data": {"task_status": "failed", "task_status_msg": "moderation"}},
            ]
        ),
        sleep_fn=lambda _: None,
    )
    with pytest.raises(VideoBackendError, match="moderation"):
        backend.generate(_shots(count=1))


def test_kling_generate_raises_without_a_task_id(kling_env):
    backend = KlingBackend(
        "kling/kling-v3", request_fn=_responder([{"data": {}}]), sleep_fn=lambda _: None
    )
    with pytest.raises(VideoBackendError, match="no task id"):
        backend.generate(_shots(count=1))


def test_kling_generate_raises_when_no_video_url_comes_back(kling_env):
    backend = KlingBackend(
        "kling/kling-v3",
        request_fn=_responder(
            [
                {"data": {"task_id": "t1"}},
                {"data": {"task_status": "succeed", "task_result": {"videos": []}}},
            ]
        ),
        sleep_fn=lambda _: None,
    )
    with pytest.raises(VideoBackendError, match="no video url"):
        backend.generate(_shots(count=1))


def test_wan_generate_polls_to_success_and_downloads(monkeypatch):
    monkeypatch.setenv("DASHSCOPE_API_KEY", "k")
    backend = WanBackend(
        "dashscope/wan2.7-t2v-plus",
        request_fn=_responder(
            [
                {"output": {"task_id": "t1"}},
                {"output": {"task_status": "RUNNING"}},
                {"output": {"task_status": "SUCCEEDED", "video_url": "https://example/v.mp4"}},
            ]
        ),
        download_fn=lambda url: b"wan-bytes",
        sleep_fn=lambda _: None,
    )
    video = backend.generate(_shots(count=1))
    assert video.data == b"wan-bytes"
    assert video.seconds == 4


def test_wan_generate_raises_on_a_failed_task(monkeypatch):
    monkeypatch.setenv("DASHSCOPE_API_KEY", "k")
    backend = WanBackend(
        "dashscope/wan2.7-t2v-plus",
        request_fn=_responder(
            [
                {"output": {"task_id": "t1"}},
                {"output": {"task_status": "FAILED", "message": "bad prompt"}},
            ]
        ),
        sleep_fn=lambda _: None,
    )
    with pytest.raises(VideoBackendError, match="bad prompt"):
        backend.generate(_shots(count=1))


def test_wan_generate_raises_without_a_task_id(monkeypatch):
    monkeypatch.setenv("DASHSCOPE_API_KEY", "k")
    backend = WanBackend(
        "dashscope/wan2.7-t2v-plus",
        request_fn=_responder([{"output": {}}]),
        sleep_fn=lambda _: None,
    )
    with pytest.raises(VideoBackendError, match="no task id"):
        backend.generate(_shots(count=1))


def test_wan_rejects_an_unknown_resolution():
    with pytest.raises(VideoBackendError, match="Resolution"):
        WanBackend("dashscope/wan2.7-t2v-plus", resolution="4k")


def test_veo_rejects_an_unknown_resolution():
    with pytest.raises(VideoBackendError, match="Resolution"):
        VeoBackend("gemini/veo-3.1-fast-generate-preview", resolution="4k")


def test_veo_polls_until_the_operation_completes():
    states = iter(
        [
            SimpleNamespace(id="v1", status="processing"),
            SimpleNamespace(id="v1", status="completed"),
        ]
    )
    backend = VeoBackend(
        "gemini/veo-3.1-fast-generate-preview",
        generation_fn=lambda **kwargs: SimpleNamespace(id="v1", status="queued"),
        status_fn=lambda **kwargs: next(states),
        content_fn=lambda **kwargs: b"veo-bytes",
        sleep_fn=lambda _: None,
    )
    assert backend.generate(_shots(count=1)).data == b"veo-bytes"


def test_veo_raises_when_no_id_comes_back():
    backend = VeoBackend(
        "gemini/veo-3.1-fast-generate-preview",
        generation_fn=lambda **kwargs: SimpleNamespace(id=None, status="queued"),
        sleep_fn=lambda _: None,
    )
    with pytest.raises(VideoBackendError, match="no video id"):
        backend.generate(_shots(count=1))


def test_veo_raises_when_content_comes_back_empty():
    backend = VeoBackend(
        "gemini/veo-3.1-fast-generate-preview",
        generation_fn=lambda **kwargs: SimpleNamespace(id="v1", status="completed"),
        content_fn=lambda **kwargs: b"",
        sleep_fn=lambda _: None,
    )
    with pytest.raises(VideoBackendError, match="no content"):
        backend.generate(_shots(count=1))


# --- Joining Veo's clips ----------------------------------------------------


def test_a_single_clip_needs_no_join():
    from horror_video_ai.video_backends.veo import _concatenate

    assert _concatenate([b"only-one"]) == b"only-one"


def test_joining_without_ffmpeg_fails_loud(monkeypatch):
    """Veo's 8-second cap means a 15-second short is always several
    clips, so a missing ffmpeg has to surface before anything is paid
    for -- which is why validate() checks it too."""
    from horror_video_ai.video_backends import veo as veo_module

    monkeypatch.setattr(veo_module.shutil, "which", lambda _: None)
    with pytest.raises(VideoBackendError, match="ffmpeg"):
        veo_module._concatenate([b"a", b"b"])
    assert any("ffmpeg" in p for p in VeoBackend("gemini/veo-3.1-fast-generate-preview").validate(_shots()))


# --- Credentials, checked before the spend prompt --------------------------


@pytest.mark.parametrize(
    ("build", "unset", "expected"),
    [
        (lambda: VeoBackend("gemini/veo-3.1-fast-generate-preview"), ["GEMINI_API_KEY"], "GEMINI_API_KEY"),
        (lambda: KlingBackend("kling/kling-v3"), ["KLING_ACCESS_KEY"], "KLING_ACCESS_KEY"),
        (lambda: KlingBackend("kling/kling-v3"), ["KLING_SECRET_KEY"], "KLING_SECRET_KEY"),
        (lambda: WanBackend("dashscope/wan2.7-t2v-plus"), ["DASHSCOPE_API_KEY"], "DASHSCOPE_API_KEY"),
    ],
)
def test_a_missing_key_is_a_fatal_validation_problem(monkeypatch, build, unset, expected):
    """A bake-off confirms one total and then generates in order, so a
    missing key found at generate() time means the backends ahead of it
    have already been paid for. validate() has to catch it instead, and
    the problem must be fatal -- run_bakeoff only skips problems that do
    not start with "note:"."""
    for key in unset:
        monkeypatch.delenv(key, raising=False)
    problems = build().validate(_shots(count=1, seconds=4))
    matching = [p for p in problems if expected in p]
    assert matching, problems
    assert not matching[0].startswith("note:")


def test_credentials_present_means_no_credential_problem():
    for backend in (
        VeoBackend("gemini/veo-3.1-fast-generate-preview"),
        KlingBackend("kling/kling-v3"),
        WanBackend("dashscope/wan2.7-t2v-plus"),
    ):
        assert not [p for p in backend.validate(_shots(count=1, seconds=4)) if "_KEY" in p]
