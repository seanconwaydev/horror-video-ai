# Pipeline stages — detail

Last updated: 2026-09-21

> Stages 2 and 3 (Research, Fact-check) were built and then deleted by
> [decisions/0069](./decisions/0069-delete-historical-grounding.md).
> Nothing in this pipeline is verified against the real world any more,
> and the numbering below keeps its gaps rather than renumbering, so
> stage 8 still means previz everywhere it is cited. What actually runs
> today is **scene planning -> previz -> video generation**; see
> CLAUDE.md for the current build.

See [architecture.md](./architecture.md) for the high-level diagram this expands on. Each stage below produces a reviewable artifact and, for most stages, has a review gate before the pipeline continues.

### 1. Topic selection

Input: a scene — a time, a place, and what happens — chosen by you (at least initially; this could become model-assisted later, e.g. suggesting ideas based on what's performing well in the space, but that's a v2 concern). "Time" and "place" are a setting, not a claim about the world: "present day" and "an underground car park at night" are the normal case.

### 2. Research — deleted

### 3. Fact-check pass — deleted

Both stages are gone ([decisions/0069](./decisions/0069-delete-historical-grounding.md)). Research produced a sourced fact sheet and fact-check verified it; together they grounded every scene in real-world claims, refused impossible premises, and made the human resolve each flag before planning. [decisions/0031](./decisions/0031-goal-is-quality-video-not-historical-accuracy.md) had already settled that accuracy is not this project's goal, and a horror short set in a car park was paying for sourced claims it could not use.

Consequence for the stages below: wherever one of them says "the verified fact sheet" or "stay strictly within the bounds of the verified facts", read it as the scene the human wrote. Nothing verifies anything now.

### 4. Narrative / script

From the scene, a model writes the actual script — the thing a viewer will hear (or, if the video has no narration, the thing that drives the visual/audio design — see stage 10). This stage is optimized for a different skill than research: hook strength, pacing, narrative throughline, an ending that lands. Point of view (first- vs. third-person) and narrative format (see the playbook) are decided here, per video.

**Review gate:** you read the script for craft — is this something you'd actually want to watch.

### 5. Narrative quality review

A second model critiques the script specifically for watchability — where it drags, where the hook is weak, whether the structure holds attention, whether it feels generic vs. distinctive. This is the gate most directly aimed at avoiding "inauthentic content" territory (see the research doc): a script that reads like a templated summary should get flagged here.

**Review gate:** you decide which critiques to act on and revise the script accordingly (or send it back for a regeneration pass).

### 6. Shot list / scene breakdown

The approved script is broken into discrete visual beats — video generation models work in short clips (typically 5–10 seconds each), not continuous narratives, so the script needs to be decomposed into a sequence of scenes before it can be turned into generation prompts.

**Review gate:** you check the shot list against the script — does the visual plan actually serve the story, or is it defaulting to generic "historical imagery"?

### 7. Per-scene video prompts

Each scene becomes a detailed text prompt, written in whatever prompting idiom the target video model expects (this varies meaningfully between Veo, Kling, Runway, Sora, etc., so this stage needs to be model-aware).

**Review gate:** you read through the full set of prompts as a batch before anything gets rendered.

### 8. Previz (still images)

This is the key cost-control stage — the spend gate shown in the architecture diagram. Before any video is generated, an image model renders one still frame per scene from its video prompt. Reviewing a storyboard of stills is dramatically cheaper than reviewing generated video clips, and it catches the failure modes that matter most before money is spent: wrong tone, awkward composition, a character staged as scenery, a scene that just doesn't look like what you pictured.

This stage does double duty: the approved still isn't just a review artifact, it becomes the reference image fed into the video model's image-to-video generation for that scene (assuming the chosen video model supports image conditioning — this should be a requirement when selecting a video model, since it gives tighter continuity between what you approved and what actually renders, rather than the video model reinterpreting the text prompt from scratch).

There is no automated pass in front of you: the image goes straight to the human gate. [decisions/0009](./decisions/0009-previz-image-review.md) put an independent vision model in that position, and [decisions/0055](./decisions/0055-delete-the-automated-previz-reviewer.md) deleted it after measuring it against 78 images already ruled on — 56% agreement against 79% for accepting everything, and it rejected 31 of the 62 images that were kept. A gate worse than no gate is a gate that costs regenerations and hides good frames. The retry loop it used to drive is gone with it; the human decides what gets regenerated.

**Review gate:** you approve the full storyboard, scene by scene. Nothing proceeds to video generation until this gate is cleared. This is the hard stop before any expensive spend.

### 9. Video generation

Only now does the actual (expensive) video generation run, one clip per approved scene, using the scene's text prompt plus its approved reference image.

**Review gate:** spot-check generated clips against their approved previz/prompt before assembly — a regeneration here is far cheaper than discovering a problem after the full video is assembled.

### 10. Voice and audio

Not fixed to a single format — different videos may use narrator voiceover, in-scene character speech, or no dialogue/narration at all (sound design and ambient audio only), decided per video at the script stage rather than as a pipeline default. Whatever the choice, it happens in parallel with video generation since it depends on the script, not the visuals.

### 11. Assembly

Clips, narration, music, and captions get stitched into the final cut. Thumbnail and title generation happen here too — arguably these matter as much to view counts as the video content itself, so they deserve their own review, not an afterthought.

**Review gate:** full watch-through of the assembled video before upload — the last and most important check.

### 12. Upload

Push to YouTube via the YouTube Data API with metadata, including toggling the "altered or synthetic content" disclosure where applicable (required by YouTube policy for realistic synthetic content; disclosing it does not by itself limit reach or monetization — see the research doc).

## Feedback loop (phase 2, once there's data)

Once videos are live and generating real performance data, YouTube Analytics (retention curves, drop-off points, thumbnail CTR, average view duration) gets pulled in periodically. A model summarizes what the data suggests — where viewers drop off, what thumbnail styles outperform others — and those summaries feed back into the rubrics used at the review-gate stages (particularly stage 5 and the thumbnail step of stage 11). You stay the one deciding whether to act on a given insight; the model's role is surfacing patterns, not autonomously rewriting the pipeline or its own code.

Alongside this, a running notes log of your own review judgments (what you rejected and why, at each gate) is worth keeping from day one — this is useful even before there's any YouTube data, and it's the most direct way the "reviewer" models' prompts get sharper over time.

Not built yet — this is planned future behavior, not current pipeline behavior.
