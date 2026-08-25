import json

import pytest

from historical_video_ai.json_utils import strip_markdown_json_fence


def test_strip_markdown_json_fence_removes_json_labeled_fence():
    raw = '```json\n{"a": 1}\n```'
    assert strip_markdown_json_fence(raw) == '{"a": 1}'


def test_strip_markdown_json_fence_removes_plain_fence():
    raw = '```\n{"a": 1}\n```'
    assert strip_markdown_json_fence(raw) == '{"a": 1}'


def test_strip_markdown_json_fence_leaves_unfenced_content_unchanged():
    raw = '{"a": 1}'
    assert strip_markdown_json_fence(raw) == raw


def test_strip_markdown_json_fence_leaves_malformed_content_unchanged():
    # Still-malformed content isn't this function's job to fix -- it only
    # removes a wrapper, never touches what's inside it.
    raw = "not json at all"
    assert strip_markdown_json_fence(raw) == raw


@pytest.mark.parametrize(
    "raw",
    [
        '```json\n{"accepted": true, "concern": null}\n```',
        '{"accepted": true, "concern": null}',
    ],
)
def test_strip_markdown_json_fence_output_is_always_valid_json_when_input_is(raw):
    assert json.loads(strip_markdown_json_fence(raw)) == {"accepted": True, "concern": None}
