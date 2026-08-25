"""Workarounds for currently-unfixed upstream bugs in litellm.

See CLAUDE.md's "Known upstream workarounds" section for the convention
this file follows -- greppable `WORKAROUND(...)` markers so a later session
can find every one of these and check whether it's safe to delete because
the underlying bug got fixed upstream.

Any stage module that makes a real (non-mocked) litellm.completion() or
litellm.image_generation() call should `import historical_video_ai
._litellm_workarounds  # noqa: F401` for its side effect, before that call
happens. Each workaround below is self-deactivating: it checks whether the
bug it patches is still present and does nothing if litellm has already
fixed it, so this file doesn't need to be remembered and manually removed
the moment a fix ships -- though it's still worth deleting once every
workaround in it has gone permanently inert, so this file doesn't linger
as dead weight.
"""

from __future__ import annotations


def _fix_message_forward_ref() -> None:
    """WORKAROUND(https://github.com/BerriAI/litellm/issues/36384): on
    Python 3.10/3.11, litellm.types.utils.Message -- and anything built on
    it, e.g. ModelResponse -- fails to construct at all. Pydantic can't
    resolve a forward reference to ChatCompletionReasoningSummaryTextBlock,
    a type that's defined in litellm/types/llms/openai.py but never
    imported into litellm/types/utils.py, where Message actually lives.
    This breaks litellm.completion() for every provider, not just one --
    it isn't specific to any model this project uses.

    Verified 2026-08-22: no released litellm version fixes this (checked
    1.96.2, 1.97.0 -- the latest stable at the time -- and every available
    pre-release build up to 1.99.0.dev2). Two upstream PRs (litellm#36387,
    #36396) looked relevant but don't actually fix this failure path when
    tested against their real commits -- they fix a different forward-ref
    issue self-contained within openai.py, and never touch utils.py's
    missing import, which is the actual gap. Escalated no further than
    that per project convention: this project checks released versions for
    a fix, not in-flight/unmerged PRs, before resorting to a workaround.
    """
    import litellm.types.utils as litellm_types_utils

    if getattr(litellm_types_utils, "ChatCompletionReasoningSummaryTextBlock", None) is not None:
        return  # litellm already resolves this -- fixed upstream, nothing to do

    from litellm.types.llms.openai import ChatCompletionReasoningSummaryTextBlock

    litellm_types_utils.ChatCompletionReasoningSummaryTextBlock = (
        ChatCompletionReasoningSummaryTextBlock
    )
    litellm_types_utils.Message.model_rebuild(force=True)


def _fix_video_generation_internal_params_leak() -> None:
    """WORKAROUND(no upstream issue found as of 2026-08-25 -- see note
    below): litellm.video_generation() builds a `local_vars = locals()`
    snapshot of its own function scope (prompt, model, input_reference,
    timeout, kwargs, etc.), later merges the decorator-injected `kwargs`
    into it (`local_vars.update(kwargs)`), and passes that whole blob to
    VideoGenerationRequestUtils.get_requested_video_generation_optional_param()
    to compute the request's "optional params". That function only strips
    litellm's own named internal params (via filter_out_litellm_params) --
    it has no way to know `local_vars` (which, after the update, nests a
    copy of itself) and `_is_async` are video_generation()'s own
    implementation details, not real request fields. Both leak straight
    through into the actual HTTP request body sent to the provider. For
    OpenAI's videos endpoint (multipart/form-data, since an image is
    attached) this fails outright: httpx's multipart encoder rejects
    `local_vars`'s dict value with "Invalid type for value. Expected
    primitive type, got <class 'dict'>" before any network call is even
    made -- confirmed via direct reproduction, not just seen once in a live
    run. Root-caused and reproduced in this project on 2026-08-25 while
    building the video_generation stage; a directed search (GitHub issues,
    PRs, and the relevant file's commit history) turned up nothing already
    describing this specific leak, so this may be worth filing upstream --
    that's your call, not something to do without asking, since it's a
    public action under your account.

    Verified 2026-08-25: no released litellm version fixes this on this
    project's Python 3.10 (`.python-version`) -- 1.98.0 and the newest
    published pre-release (1.99.0rc1) do fix the underlying leak (checked
    by direct reproduction, bypassing the network, in isolated venvs), but
    both are unrelated-ly broken on Python 3.10: they unconditionally
    `from typing import NotRequired`, which doesn't exist before Python
    3.11, so litellm fails to import at all. Effectively no usable released
    fix exists for this project's environment, meeting this project's own
    bar (CLAUDE.md's "Known upstream workarounds") for a workaround here
    rather than an upgrade.
    """
    import litellm.videos.utils as litellm_video_utils

    _LEAKED_INTERNAL_KEYS = ("local_vars", "_is_async")

    original = litellm_video_utils.VideoGenerationRequestUtils.get_requested_video_generation_optional_param

    # Self-deactivating: if upstream's own filtering already drops these
    # keys (i.e. the bug is fixed), this probe call -- pure, no I/O, no
    # network -- comes back clean and there's nothing to patch.
    probe = original({"local_vars": {"marker": True}, "prompt": "p"})
    if not any(key in probe for key in _LEAKED_INTERNAL_KEYS):
        return

    def _patched(params):
        result = original(params)
        for key in _LEAKED_INTERNAL_KEYS:
            result.pop(key, None)
        return result

    litellm_video_utils.VideoGenerationRequestUtils.get_requested_video_generation_optional_param = (
        staticmethod(_patched)
    )


_fix_message_forward_ref()
_fix_video_generation_internal_params_leak()
