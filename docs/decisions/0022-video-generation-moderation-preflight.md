# 22. Two-layer moderation pre-flight check before video generation

Date: 2026-08-28

Status: Accepted

## Context

A real `--video-gen-from` run against an approved previz image (Agent Voss
reaching a rooftop doorway) failed twice with Sora's `moderation_blocked`,
both times paid, real attempts. The first failure used the image's saved
previz prompt; the second used a fully rewritten, deliberately neutral
prompt (no aggressive verbs, explicit `Audio:` direction, no wording from
`docs/playbook/video-generation-prompting.md`'s already-documented
"tactical jacket"/"shoulder-checks" lesson) against the *same* image, and
still failed identically. Since only the text changed between the two
failures, the reference image itself -- not the prompt -- is the trigger:
a dynamic lunging pose, one gloved hand pressed flat against a door,
plausibly reading as forced entry to Sora's classifier even though a human
reviewer sees ordinary non-violent action content. Two other images from
the same scene (sprinting toward camera, mid-air leap) generated cleanly,
so this isn't a blanket "action content" problem -- it's specific to this
one visual pattern.

Sora's own moderation is a separate, undisclosed "prevention-first"
system, not the same thing as OpenAI's public moderation endpoint --
it text-scans prompts before generation starts and analyzes generated
frames, using thresholds that aren't published. A generic classifier
tuned to literal policy categories (depicted violence/injury, self-harm,
sexual content, hate) won't necessarily flag "a pose that reads as
breaking into a building," since nothing about that is literally violent.
Note also: some public documentation claims about this API (e.g. that any
reference image containing a human face is rejected) were checked against
this project's own real runs and don't hold up -- two of the three real
reference images used here show clear human faces and generated
successfully. Public docs about this specific API are not fully reliable;
this project's own observed failures are the trustworthy source.

Discovering a `moderation_blocked` failure only at the video-generation
call -- after research, fact-check, and previz have already run -- means
money and time are wasted on a scene that was doomed from the image stage.
`previz_review` (0009) is the existing adversarial-image-check
infrastructure, but it's conditionally run at best: it's skipped entirely
for scenes generated outside the normal pipeline flow (confirmed directly
-- this project's own fictional Agent Voss test runs have no
`previz_review_model` key in their logs, meaning that check never ran for
them), and `--video-gen-from` is explicitly designed to accept a previz
image from any provenance, reviewed or not. A money-safety check needs to
run unconditionally, every time, regardless of how the reference image was
produced -- folding it into `previz_review` would silently make it
optional in exactly the cases (ad hoc/fictional scenes, `--video-gen-from`
against an old run) where it's needed just as much.

## Decision

A new, standalone two-layer check (`stages/moderation.py`), run in
`_run_video_generation_only` immediately before every paid
`run_video_generation_stage` call -- the one choke point every path
(full pipeline, `--fixture`, or a hand-built run directory) passes through
regardless of how the previz image and prompt were produced.

**Layer 1 -- free, catches literal policy violations.**
`run_moderation_policy_check` calls `litellm.moderation()` (wraps OpenAI's
own `omni-moderation-latest` endpoint, confirmed free, confirmed to accept
combined text + image input via the standard OpenAI multi-modal moderation
input shape) against the final prompt text and the reference image
together. Pinned as a new `moderation_check` entry in `config/models.yaml`
(`openai/omni-moderation-latest`) -- the only model this endpoint supports
today, per litellm's own source, but pinned anyway for consistency with
0003's per-stage convention and so a future provider addition is a
one-line config change, not a code change.

**Layer 2 -- costs one more vision-LLM call, targets what Layer 1 can't.**
`run_moderation_risk_review` sends the reference image to an independent
vision-capable model (same "not the same model checking its own work"
reasoning as `fact_check` vs. `research` and `previz_review` vs. `previz`),
asking whether the image's pose or action plausibly reads as violent,
threatening, or forced entry to an automated safety classifier -- even if
it depicts ordinary, non-violent action. The prompt is built from a small,
explicitly evidence-only list of known trigger patterns
(`_KNOWN_MODERATION_RISK_PATTERNS`), starting with exactly one entry: a
lunging or hand-pressed approach into a door read as forced entry (this
incident). This deliberately mirrors this project's existing practice of
building safeguards only from observed failures (0009's rejection-and-
retry loop, 0021's `_VIDEO_PROMPT_RISK_WORDS`) rather than speculating
about patterns that haven't actually failed yet -- plain running and
jumping already passed cleanly twice in this same scene, so guessing at
"avoid all dynamic action" would be over-broad and wrong. Pinned as a new
`moderation_review` entry in `config/models.yaml`, reusing
`anthropic/claude-sonnet-5` (same model already picked for `previz_review`,
for the same reasons).

`docs/playbook/video-generation-prompting.md`'s existing "Content
moderation" section is the narrative record of *why* each pattern is on
the list -- `_KNOWN_MODERATION_RISK_PATTERNS` and that section are kept in
sync by hand (same relationship 0021 already established between
`_VIDEO_PROMPT_RISK_WORDS` and that same section), so a newly diagnosed
incident updates both.

**On a flag from either layer:** print the concern(s) and require
confirmation before proceeding (`_confirm`, same pattern as every other
review gate in this pipeline). Under `--yes`, refuse rather than
auto-proceeding -- the same precedent 0019 set for a `[contradicted]`
fact-check flag: real money is on the line, and both layers are heuristic
enough that a human should be the one deciding to override, not `--yes`.
This skips only the flagged scene, not the whole `--video-gen-from`
invocation -- each `run_dir` is an independent scene (0010), so one
flagged scene shouldn't block generating the others in the same call.

## Consequences

`config/models.yaml` gains `moderation_check` and `moderation_review`;
`tests/test_config.py`'s `expected_stages` updated to match.
`_run_video_generation_only` gains two more calls per scene before the
paid video-generation call -- Layer 1 is free, Layer 2 is a small added
per-scene cost (roughly the same order of magnitude as the existing
`previz_review` call). `--mock` gets corresponding mock functions so the
new calls' mechanics are exercised without cost or credentials.

This is a heuristic pre-flight, not a guarantee: Layer 1 only catches
literal policy-category violations, and Layer 2's known-pattern list
starts with exactly one real data point and is expected to grow only as
real incidents get diagnosed, not by guessing ahead of evidence. A
`moderation_blocked` failure at the real Sora call is still possible after
both layers pass clean -- this reduces wasted spend on the failure modes
already seen, it doesn't eliminate the category.
