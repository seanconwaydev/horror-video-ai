import json

import pytest

from horror_video_ai.json_utils import parse_json_response, strip_markdown_json_fence


class _Err(Exception):
    pass


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


@pytest.mark.parametrize("raw", [None, "", "   ", "\n"])
def test_empty_content_raises_the_callers_error_not_an_attributeerror(raw):
    """`message.content` is None on a refusal, a filtered response, or a
    turn that returned only tool calls, and every stage passes it straight
    through. Without a guard they all crashed with a bare "'NoneType'
    object has no attribute 'strip'", which says nothing about what
    happened."""
    with pytest.raises(_Err, match="was empty"):
        parse_json_response(raw, _Err, "Scene-planning response")
