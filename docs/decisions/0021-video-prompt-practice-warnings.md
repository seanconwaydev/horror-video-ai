# 21. --video-prompt gets advisory best-practice warnings, not a gate

Date: 2026-08-28

Status: Accepted

## Context

`--video-prompt` (docs/decisions/0018's follow-on work) takes free-form,
hand-written text with nothing enforcing any structure on it. A real
prompt authored during this project's own testing left out multiple
things `docs/playbook/video-generation-prompting.md` had already learned
the hard way that same session -- no reusable character block, wording
that tripped Sora's real moderation -- discovered only after paying for a
generation. Money and time were spent on a prompt that violated known,
already-documented lessons before it ever ran.

A rigid validator that rewrites or rejects a prompt isn't the right fix --
prompt quality is a creative judgment call this code can't make
reliably, and treating a checklist as a hard gate would block legitimate
prompts that deliberately deviate from it for good reason.

## Decision

`_check_video_prompt_practices` runs a small set of cheap, mechanical,
objectively-checkable tests against a `--video-prompt` string -- a
missing `CHARACTER:` block, no `Audio:` direction, more than
`_MAX_RECOMMENDED_BEATS` (3) timecoded beats in one prompt, or wording
that has actually tripped real moderation in this project
(`_VIDEO_PROMPT_RISK_WORDS`) -- and prints each as a warning before
generation runs. It never blocks or modifies the prompt; `_run_video_
generation_only` always proceeds regardless of what it finds. This is
scoped to `--video-prompt` specifically, not previz's own auto-built
prompt, since that prompt has a different, fixed, already-known shape --
running the same checks against it would just be noisy false positives.

## Consequences

A human (or a future automated caller) authoring a `--video-prompt` now
sees, in the run's own transcript, exactly which known lessons their
prompt skipped, before any money is spent -- without anything being
rewritten or blocked. `_VIDEO_PROMPT_RISK_WORDS` and
`_MAX_RECOMMENDED_BEATS` are expected to grow/change as the playbook
itself does; keep them in sync rather than letting this drift stale.
