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


_fix_message_forward_ref()
