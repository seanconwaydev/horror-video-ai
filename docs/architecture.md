# Historical AI Video Generator — Architecture

Last updated: 2026-08-20

Fast overview of the system. For detail, see the linked docs below rather than this file — this one is meant to stay short enough to read in a couple of minutes.

- Stage-by-stage behavior: [pipeline.md](./pipeline.md)
- Why specific choices were made: [decisions/](./decisions)
- YouTube monetization policy research: [research/youtube-monetization-policy.md](./research/youtube-monetization-policy.md)
- Research-stage model comparison: [research/model-comparison.md](./research/model-comparison.md)
- Short-form format selection research: [research/short-form-format-selection.md](./research/short-form-format-selection.md)
- Horror content best practices research: [research/horror-content-best-practices.md](./research/horror-content-best-practices.md)
- Creative/narrative techniques: [playbook/narrative-techniques.md](./playbook/narrative-techniques.md)
- Human input design + the real AI-video tool landscape: [playbook/human-input-and-tools.md](./playbook/human-input-and-tools.md)
- Observed image/video failure modes and what's been tried: [playbook/failure-taxonomy.md](./playbook/failure-taxonomy.md)
- Manual pipeline dry runs: [dry-runs/](./dry-runs)

## Vision

A pipeline that turns a scene idea into a finished, YouTube-ready video, with different models handling different stages (research, narrative, visual prompting, generation), and a human review gate before every step that costs real money. The goal isn't just "software that produces a video" — it's software that produces something worth watching, with a floor of quality that holds even on video one, and that improves over time the way a creator's channel improves with experience.

**The goal is videos worth watching, not historical accuracy for its own sake** — see [decisions/0031](./decisions/0031-goal-is-quality-video-not-historical-accuracy.md). Historical settings are what the pipeline has been built and tested against so far, and research/fact-check stay genuinely useful for the parts of a scene meant to be real, but which genres are actually worth specializing in is meant to be discovered empirically across many kinds of scenes, not assumed from the pipeline's own name or its historical-genre-heavy implementation history.

Two constraints shape everything else: YouTube's monetization policy makes mass-produced, templated AI video ineligible for monetization (see the research doc linked above for what this actually says), and full ad monetization has audience thresholds (subscribers, watch hours or Shorts views) that no amount of pipeline quality can shortcut. The pipeline can get the content right; it can't skip the runway.

## Design principles

Every stage that produces cheap output (text, a still image) happens before every stage that produces expensive output (a generated video clip). Video generation is the last thing that happens in the pipeline, only after everything upstream of it has been reviewed and approved.

Every stage produces a reviewable artifact — a prompt, a document, an image — not just an opaque intermediate result. You should always be able to see and approve what a model is about to hand to the next stage.

Most stages get two passes: a generation pass (one model produces the artifact) and a review pass (a second model critiques it against explicit criteria) before it reaches you. The second model isn't rubber-stamping the first — it should be prompted adversarially, i.e. "find what's wrong with this," not "confirm this is fine."

The system should get better with use. Findings from your own review notes and, later, from actual YouTube performance data should feed back into the prompts and rubrics used at each gate, not just live in your head.

Format, audio style, and point of view are all decided per video at the narrative stage, not hardcoded as pipeline defaults — forcing every video into the same shape would itself be the "templated" pattern the monetization policy penalizes.

## Current v1 scope

The full pipeline below is the vision, and it hasn't changed. What's actually being built right now is deliberately narrower: stages 1–3 (input, research, fact-check) feeding a scoped-down Previz that produces a single image from a single described scene — no multi-scene script, no video yet. See [decisions/0006](./decisions/0006-narrow-v1-scope-single-image.md) for why, and exactly what's deferred vs. skipped for good.

## Structure

```mermaid
flowchart TD
    A[Topic] --> B[Research + fact-check]
    B --> C[Script + review]
    C --> D[Shot list + prompts]
    D --> E[Previz]
    E --> F[Video generation]
    F --> G[Audio]
    G --> H[Assembly]
    H --> I[Upload]

    classDef gate fill:#f0ad4e,stroke:#8a6d3b,color:#3a2e1a;
    class E gate;
```

The highlighted box (Previz) is the spend gate: everything before it is text or a still image and cheap to redo; everything from Video generation onward costs real money, so nothing crosses that line without explicit approval. Full behavior of each box is in [pipeline.md](./pipeline.md).

## Open questions (not yet decided)

**Video generation model.** Resolved for now: Wan via Replicate
([decisions/0037](./decisions/0037-horror-motion-comic-shorts-wan-via-replicate.md)), which replaced the
`openai/sora-2` placeholder before the Videos API was removed on 2026-09-24. It is still
a placeholder in the sense that no rigorous quality comparison has been run; Veo, Kling
and Runway remain untried.

Runway is the one worth evaluating specifically rather than leaving as one option among
several: `docs/playbook/failure-taxonomy.md`'s same-location-beat-repetitiveness entry
found that Runway Gen-4/4.5 has *native* prompt-driven camera-movement control
(dolly/pan, explicit camera parameters, ~$0.05-0.15/sec base + camera-control surcharge)
— a first-party feature for exactly the "camera coverage within one continuous shot"
problem this project has fought at the previz-image level. Worth weighing whether that
problem is better solved at the video stage (one good previz keyframe per location,
camera movement native to the video model) rather than by generating multiple
independent previz images per location and hoping they read as coherent coverage. Raw
multi-ControlNet conditioning (depth + camera pose) was researched as an alternative at
the previz-image level — requires a new provider (Flux via Replicate, ~$0.03-0.05/image,
comparable to current previz cost) — but the video-stage angle looks like the more direct
fit and adds no new image provider.

**Camera, character and environment are authored in two different spaces, and nothing
reconciles them.** The largest open design question this project has. Where a character
appears in the frame is a *projection* -- a function of where they stand in the world,
where the camera is, and the lens -- but the planner is asked to author all three legs
independently. Character world position is demanded in `action` prose ("near the top step"
vs "three steps from the bottom"); character frame position is authored separately in
`frame_position` ("upper-left of frame"); and `camera` was deliberately stripped of any
world position by [0044](./decisions/0044-camera-specified-at-a-granularity-models-follow.md),
which forbids it for good measured reasons. So two legs are world-space, one is
frame-space, the thing that would connect them is frame-relative only, and no validator
compares any of them. They can only agree if the planning model performs the projection
correctly in its head.

Observed directly (`run_20260918-221017`, `playbook/failure-taxonomy.md`): a beat placed a
character "far background, **upper-left of frame**" under a `wide, low, from behind`
camera. Far background down a receding aisle projects near the vanishing point, roughly
frame centre. The image model obeyed the frame instruction, found nothing at ceiling
height to hide the figure behind, and invented a concrete slab. The project owner's
summary: "as long as that's true, these will never turn out good on purpose, only luck."

Two coherent architectures exist and the current one is neither. **Frame-space authoring**
makes `frame_position` authoritative and derives or drops the world-space prose --
storyboarding. **World-space blocking** authors where each character stands relative to
the location's features and to each other, plus where each looks, plus a camera in 0044's
three renderable terms, and does not author frame position at all -- the image model does
the projection. The latter is what a production's blocking diagram is, and this project
already uses "coverage" and screen direction, which are that model's vocabulary.

**Partly answered, 2026-09-18.** `evals/blocking_space.py` ran the two architectures
head to head -- twelve images, three scenarios from that same run, scored blind. World-space
blocking **lost**: every image the owner picked out favourably was a frame-coordinate one,
including the only image he said he would keep. But the finding that matters is that
*distance failed in both arms* -- "far down at the unlit end, several pillars beyond her"
and "a sliver in the far background" both rendered a figure about five feet away. The model
is not converting either description into depth, so re-authoring placement in world-space
does not fix the projection problem; it relocates it.

The experiment also exposed an asymmetry it did not control, and that is now the live
hypothesis: the frame arm carries an explicit apparent size ("roughly a twentieth of the
image") because that is how `frame_position` is written, the world arm carried none, and
apparent size is the strongest depth cue a rendered image has. The only two depth successes
in the run sat in the arm holding the size. A third arm (`world_size` -- world placement plus
the same size figures) is added and unrun. If it matches the frame arm, the lever is apparent
size rather than frame coordinates, and world placement can replace `frame_position` provided
size travels with it -- a far smaller change than giving `Location` a floor plan. Full result
in [playbook/failure-taxonomy.md](./playbook/failure-taxonomy.md).

Two things had to be established before choosing, and one was already answered.
*Answered:* this is not caused by reference-image conditioning. 0044's live hypothesis was
that conditioning overrides camera direction, but `run_20260918-221017` ran with
`--references none` ([0050](./decisions/0050-no-reference-images-by-default.md)) and took
the plain text-to-image branch, and the conflict appeared anyway. `evals/camera_obedience.py`
is still worth running to find out whether conditioning makes it *worse*, but it is no
longer the prior question. *Unanswered:* `Location` has no geometry either -- it is
`architecture`, `fixed_props` and `ambient_light`, all prose -- so world-space blocking has
no floor plan to position anyone against. Something has to carry the space itself before a
character can be placed in it.

**Documentation and instruction rot.** Several decisions have outlived the premise that
justified them, and the pattern is now frequent enough to be worth a deliberate sweep
rather than case-by-case discovery: a dead model constant survived a month past
[0037](./decisions/0037-horror-motion-comic-shorts-wan-via-replicate.md); reference conditioning outlived its
premise until [0050](./decisions/0050-no-reference-images-by-default.md); the entire
single-image previz flow stayed reachable-looking, tests and all, until
[0051](./decisions/0051-remove-the-single-image-previz-flow.md); and `CLAUDE.md` claimed
video generation went through litellm long after it stopped doing so. The findings so far, and the method, are written up in
[playbook/repo-audit-brief.md](./playbook/repo-audit-brief.md), and what is still queued is in [playbook/open-tasks.md](./playbook/open-tasks.md). Two things to check
across the whole repo, not just where a bug points: every doc claim against the code that
implements it, and every prompt rule in `scene_planning.py`/`previz.py` against whether it
is still earning its place. For the prompt rules specifically, the question is not only
whether a rule is outdated but whether it sits at the right tier and in the right order —
the five-tier framework (instruction / routed instruction / schema constraint / selection
/ capability) plus [0048](./decisions/0048-heuristic-gates-warn-rather-than-fail.md)'s
rule that only a decidable predicate may fail a run. Two rules have already been found
actively fighting each other: a buried, conditional "make characters react to each other"
clause was losing to a much more concrete instruction to describe the threat as a fraction
of the frame ([0049](./decisions/0049-per-character-staging-in-beats.md)).

**Image model for previz.** Needs to be cheap and fast since it's the primary quality gate. `gemini/gemini-2.5-flash-image` is the current v1 placeholder ([decisions/0011](./decisions/0011-previz-image-model-for-video-aspect-ratio-fit.md), superseding 0007's original OpenAI placeholder) — picked because its 9:16 output is a close aspect-ratio match to the video-generation stage's required size, not from a rigorous quality comparison; Kling, Runway, and a real quality bake-off against gpt-image-1-mini are all still untried.

**Control flow.** How stages actually get called in sequence and pause for review (a script vs. something more structured) — worth revisiting once stages 2–7 have real code to review. Likely AWS Step Functions, per [decisions/0004](./decisions/0004-aws-incremental-adoption.md), but not yet implemented. Answered for v1's narrowed scope as a plain CLI confirm-loop — see [decisions/0006](./decisions/0006-narrow-v1-scope-single-image.md).

**Compute for the video-generation stage.** Lambda's 15-minute execution limit doesn't fit long-running video-generation API calls. Fargate is the leading candidate but needs more research before committing — see [decisions/0004](./decisions/0004-aws-incremental-adoption.md).

**Which other AWS services get adopted, and when.** S3 (artifact storage), Secrets Manager/Parameter Store (API keys), and DynamoDB/RDS (pipeline state) were all identified as natural fits in [decisions/0004](./decisions/0004-aws-incremental-adoption.md), but deliberately not committed yet — each gets its own ADR if and when the pipeline actually needs it.

**Whether previz's "main character" stays generic or becomes fixed (a recurring "brand" character) or input-determined.** Raised in [decisions/0006](./decisions/0006-narrow-v1-scope-single-image.md); not resolved there.

**How a non-interactive caller should resolve a premise conflict.** [decisions/0008](./decisions/0008-refuse-impossible-premises.md) builds an interactive human review flow for when fact-check finds the requested scene historically impossible (offer a close alternative, let the human correct it, or stop) — but this pipeline may eventually be driven by something other than a human at a terminal, per the "Control flow" question above. There's no answer yet for how such a caller would resolve a conflict without a human to ask; `run_previz_stage`'s hard refusal is the safety net in the meantime, not a resolution mechanism.

**Whether an overall video "style/genre" preset is worth adding — the rule-application half is now answered.** Raised while researching camera/composition conventions for previz: classical continuity editing (the 180-degree rule, consistent screen direction, eyeline matches) is the right convention for a cinematic/film-like video, but genuinely wrong for other genres this project might want to produce — an influencer/vlog-style video routinely breaks those rules on purpose (jump cuts, direct-to-camera address) while relying on its own strong, well-established convention instead. Kids' content, "cute"/wholesome content, and other genres likely each have their own established trope set the same way. [decisions/0034](./decisions/0034-creative-flag-skips-historical-grounding.md) took the first step (a binary `--creative` flag), superseded by [decisions/0035](./decisions/0035-genre-and-tone-replace-binary-creative-flag.md) (`--genre`/`--tone` free text feeding scene-planning directly). [decisions/0036](./decisions/0036-genre-resolves-to-early-routing-signals.md) now answers the *mechanism* for exactly this 180-degree-rule-vs-jump-cuts-vs-other-trope-sets idea: genre-conditional rules are built reactively as named, selected rule groups keyed by a small early-resolved signal (generalizing the `requires_grounding` pattern), not inline prose exceptions, and not a full pipeline split per genre. Still genuinely open: the fuller structured-brief fields (audience, constraints-as-one-concept, deliverables) and whether per-stage *model* selection should also route on grounding/genre — both tracked as their own items, not resolved by 0036.

**Whether horror needs its own sub-genre routing, not just one shared rule set.** Raised after real horror-genre runs (`docs/playbook/failure-taxonomy.md`'s "Rule refinements are scenario-specific" entry): rules and moderation-risk patterns tuned against a domestic-interior haunting scene aren't assumed to transfer to a structurally different horror scenario (an outdoor chase, body horror, a slasher scene). Whether horror sub-types eventually warrant their own routed rule variants the way `composition_mode` already routes staged-vs-chaotic (ADR 0036) is genuinely undecided — needs real variety across multiple horror scenario types tried first, not just the domestic-interior scenes tested so far.

Once any of these is actually decided, it moves out of this list and becomes its own entry under [decisions/](./decisions).
