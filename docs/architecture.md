# Historical AI Video Generator — Architecture

Last updated: 2026-08-12

## Vision

A pipeline that turns a historical topic into a finished, YouTube-ready educational video, with different models handling different stages (research, narrative, visual prompting, generation), and a human review gate before every step that costs real money. The goal isn't just "software that produces a video" — it's software that produces something worth watching, with a floor of quality that holds even on video one, and that improves over time the way a creator's channel improves with experience.

Two things are shaping this from the start. First, YouTube's "inauthentic content" policy (part of its channel monetization policies, renamed from "repetitious content" in July 2025) makes mass-produced, templated AI video ineligible for monetization — so originality and craft aren't optional polish, they're a monetization requirement. See the dedicated section below for what this actually says and how the pipeline addresses it; an earlier draft of this doc cited a "three-strike" enforcement mechanism specific to this policy from a secondary source, which does not appear in YouTube's own monetization policy page and has been removed pending further verification — YouTube does have a well-documented three-strikes system, but it's for Community Guidelines violations generally, not confirmed as the specific mechanism for inauthentic-content monetization decisions. Second, full ad monetization needs 1,000 subscribers and either 4,000 watch hours in 12 months or 10 million Shorts views in 90 days, plus a linked AdSense account — meaning the "$1" goal is gated by audience thresholds that no amount of pipeline quality can shortcut. The pipeline can get the content right; it can't skip the runway.

## Design principles

Every stage that produces cheap output (text, a still image) happens before every stage that produces expensive output (a generated video clip). Video generation is the last thing that happens in the pipeline, only after everything upstream of it has been reviewed and approved.

Every stage produces a reviewable artifact — a prompt, a document, an image — not just an opaque intermediate result. You should always be able to see and approve what a model is about to hand to the next stage.

Most stages get two passes: a generation pass (one model produces the artifact) and a review pass (a second model critiques it against explicit criteria) before it reaches you. The second model isn't rubber-stamping the first — it should be prompted adversarially, i.e. "find what's wrong with this," not "confirm this is fine."

The system should get better with use. Findings from your own review notes and, later, from actual YouTube performance data should feed back into the prompts and rubrics used at each gate, not just live in your head.

## Pipeline stages

### 1. Topic selection

Input: a historical topic or era, chosen by you (at least initially — this could become model-assisted later, e.g. suggesting topics based on what's performing well in the space, but that's a v2 concern).

### 2. Research

A model with web search / grounding (not relying purely on parametric knowledge) produces a structured fact sheet: claims, dates, names, and a citation or source for each. Historical accuracy is the thing most likely to publicly embarrass the channel if it's wrong, so nothing here should be unsourced.

**Review gate:** you read the fact sheet. Is it accurate, are the sources real and credible, is anything missing that a good treatment of this topic would need?

### 3. Fact-check pass

A second, independent model pass reviews the research output specifically for accuracy — cross-checking claims, flagging anything uncertain or contested, catching hallucinated specifics (invented quotes, wrong dates, misattributed events). This model should be prompted to be skeptical of the research stage's output, not to summarize it.

**Review gate:** you see any flags raised and resolve them (accept the claim, cut it, or soften the language to reflect genuine historical uncertainty where it exists).

### 4. Narrative / script

Using only the verified fact sheet, a model writes the actual script — the thing a viewer will hear. This stage is optimized for a different skill than research: hook strength, pacing, narrative throughline, an ending that lands. It should stay strictly within the bounds of the verified facts; it doesn't get to introduce new claims.

**Review gate:** you read the script for both faithfulness to the research (did it stay accurate) and craft (is this something you'd actually want to watch).

### 5. Narrative quality review

A second model critiques the script specifically for watchability — where it drags, where the hook is weak, whether the structure holds attention, whether it feels generic vs. distinctive. This is the gate most directly aimed at avoiding "inauthentic content" territory: a script that reads like a templated summary should get flagged here.

**Review gate:** you decide which critiques to act on and revise the script accordingly (or send it back for a regeneration pass).

### 6. Shot list / scene breakdown

The approved script is broken into discrete visual beats — video generation models work in short clips (typically 5–10 seconds each), not continuous narratives, so the script needs to be decomposed into a sequence of scenes before it can be turned into generation prompts.

**Review gate:** you check the shot list against the script — does the visual plan actually serve the story, or is it defaulting to generic "historical imagery"?

### 7. Per-scene video prompts

Each scene becomes a detailed text prompt, written in whatever prompting idiom the target video model expects (this varies meaningfully between Veo, Kling, Runway, Sora, etc., so this stage needs to be model-aware).

**Review gate:** you read through the full set of prompts as a batch before anything gets rendered.

### 8. Previz (still images)

This is the key cost-control stage. Before any video is generated, an image model renders one still frame per scene from its video prompt. Reviewing a storyboard of stills is dramatically cheaper than reviewing generated video clips, and it catches the failure modes that matter most before money is spent: wrong tone, anachronistic imagery, awkward composition, a scene that just doesn't look like what you pictured.

This stage does double duty: the approved still isn't just a review artifact, it becomes the reference image fed into the video model's image-to-video generation for that scene (assuming the chosen video model supports image conditioning — this should be a requirement when selecting a video model, since it gives tighter continuity between what you approved and what actually renders, rather than the video model reinterpreting the text prompt from scratch).

**Review gate:** you approve the full storyboard, scene by scene. Nothing proceeds to video generation until this gate is cleared. This is the hard stop before any expensive spend.

### 9. Video generation

Only now does the actual (expensive) video generation run, one clip per approved scene, using the scene's text prompt plus its approved reference image.

**Review gate:** spot-check generated clips against their approved previz/prompt before assembly — a regeneration here is far cheaper than discovering a problem after the full video is assembled.

### 10. Voice and audio

Not fixed to a single format — different videos may use narrator voiceover, in-scene character speech, or no dialogue/narration at all (sound design and ambient audio only), decided per video at the script stage rather than as a pipeline default. This is deliberate: forcing every video into the same audio format would itself be a form of the "templated" pattern the inauthentic-content policy penalizes, so staying flexible here is as much a policy-risk decision as a creative one. Whatever the choice, it happens in parallel with video generation since it depends on the script, not the visuals.

### 11. Assembly

Clips, narration, music, and captions get stitched into the final cut. Thumbnail and title generation happen here too — arguably these matter as much to view counts as the video content itself, so they deserve their own review, not an afterthought.

**Review gate:** full watch-through of the assembled video before upload — the last and most important check.

### 12. Upload

Push to YouTube via the YouTube Data API with metadata, including toggling the "altered or synthetic content" disclosure where applicable (required by YouTube policy for realistic synthetic content; disclosing it does not by itself limit reach or monetization).

## Inauthentic content policy — risk mitigation

Source: YouTube's official "YouTube channel monetization policies" page (support.google.com/youtube/answer/1311392), fetched 2026-08-12. This is the primary source, not a secondary summary.

There is no way to guarantee with certainty that a given video won't be flagged. The policy is enforced by human reviewer judgment against qualitative language, not an automated check against a fixed threshold, so "100% certain" isn't an achievable target — the honest goal is minimizing risk by deliberately building toward the stated criteria, not eliminating it.

The policy's own language is more specific than secondary sources suggested, and it directly shapes what the review gates should be checking for. Not allowed to monetize: "AI-generated content made with generic or unoriginal templates giving the impression of mass production without adding the creator's original, authentic insights or perspective," "image slideshows, templated storylines, or scrolling text with minimal or no narrative, commentary, or educational value," and content that "stitches together unrelated or inconsistent AI clips" without a cohesive narrative arc. Allowed to monetize: content with "a cohesive storyline that doesn't rely solely on shock value," content that "expresses your unique creative voice, like using AI to visualize a unique character and narrative you invented," and content that "utilizes creative tools to assist in delivering a unique, well-researched, or creative narrative" as long as "the final product still demonstrates your creative vision." A consistent intro/outro across videos is explicitly fine — what has to vary is the substance. Reviewers also assess a channel as a whole (its main theme, most-viewed and newest videos, metadata, About section), not just one video in isolation, so consistency of quality and premise across the channel matters, not only individual-video polish.

Mapped to the pipeline: the research and fact-check stages (2–3) should aim for genuine, specific findings rather than a generic summary, since "original, authentic insights" is explicit policy language. The narrative and narrative-quality-review stages (4–5) should be scored directly against "cohesive narrative arc" and "materially varied" substance, not just against a general "is this good" rubric — this is the gate most directly responsible for catching templated-feeling scripts before they go further. The shot list and previz stages (6–8) should be checked for visual coherence across the sequence, specifically to avoid the "stitched together unrelated or inconsistent AI clips" failure mode called out by name in the policy. None of this is a substitute for your own judgment at each review gate, but it gives the review gates (both yours and the model reviewers') concrete, sourced language to check against instead of a vague sense of "does this feel like slop."

### What actually happens if a video gets flagged

Source: YouTube's "Monetization is disabled for my channel" page (support.google.com/youtube/answer/1727191), fetched 2026-08-12. This directly answers the "is it one strike and done" question — it isn't.

There's a warning stage before any channel-level penalty: if a portion of a channel is found out of line with monetization policy, YouTube sends a "scheduled for suspension" notice with a 7-day window to appeal before the suspension takes effect. Appealing in time pauses the scheduled suspension while it's reviewed (response within 14 days). If the window is missed or the appeal is rejected, the channel is suspended from the Partner Program — at which point you can appeal within 21 days, or simply re-apply after 90 days.

For monetization-policy violations specifically (the category inauthentic content falls under), the documented recovery path is exactly "fix it and try again": review the flagged videos against policy, edit or delete the ones that violate it, then re-apply. YouTube's review team re-examines the channel; the decision takes about a month.

One important distinction: this "edit or delete to fix it" path applies to monetization-policy issues, not to Community Guidelines strikes or copyright strikes — for those, deleting the video explicitly does not resolve the strike, a formal appeal of the strike itself is required instead. That's a separate, harsher system and not the one this project's content would be evaluated under if the concern is "this feels mass-produced" rather than a safety/content violation.

Net effect for planning purposes: a channel finding its footing can expect a working correction loop (warning → fix → resume, or suspend → correct → re-apply) rather than a single irreversible failure condition, which fits the expectation that the first several videos are where the pipeline's quality bar gets calibrated against the real platform.

## Narrative concept ideas

**Character-driven format (undecided).** One direction under consideration: rather than a straight documentary-style summary of a topic, each video follows a character moving through real historical events or settings, working toward or accomplishing something, or meeting a dramatic (possibly tragic) fate. This is worth taking seriously for reasons beyond storytelling: it maps closely onto exactly the language YouTube's policy calls out as monetizable — "using AI to visualize a unique character and narrative you invented" is a near-verbatim match for this idea, and a distinct character/premise per video is a strong, legible way to satisfy "materially varied" content across the channel.

It does raise a question that isn't resolved yet: how a character-driven device interacts with the fact-checking pipeline. If the character is a real historical figure, the accuracy bar from stages 2–3 applies to them directly, same as any other claim. If the character is fictional or a composite used to dramatize real events (a common device in historical storytelling), that needs to be handled honestly — likely via clear framing in the video itself (e.g., "a composite character based on real accounts") so the "educational" positioning doesn't blur into presenting invented specifics as documented fact. This is a discussion for when the narrative stage design gets more concrete, not a blocker on anything happening now.

**Unexplained human detail (creative principle, from the D-Day dry run).** AI-generated video has a natural tendency toward a slightly surreal, gap-filled quality — this can read as off-putting, but it can also be an asset: leaving some detail slightly unresolved invites the viewer's imagination to fill it in, rather than everything being explicitly set up and paid off. Concretely, this means giving a character one subtle, human, *unexplained* habit or tic — something a viewer notices and wonders about rather than something narrated or resolved (examples explored so far: a private counting habit, an unconscious habit with a piece of gear, a limp or physical habit with no stated backstory). Explicitly not meant as a required beat in every video — it's a pool of techniques to draw from for flavor, not a checklist item, since forcing it into every single video would itself become a template. First applied instance: the D-Day dry-run script used a private, unexplained counting habit under the soldier's breath, which breaks and restarts at moments of shock — logged here as the first concrete example in the pool.

A further variant on this, specific to continuous/countable tics rather than tics in general: occasionally letting the detail bridge a scene cut to imply elapsed time — e.g., a count left at "...2...3..." at the end of one scene picked back up mid-count ("...30...31...") at the start of the next, implying time has passed without narrating it. This should be rare, not a recurring device, and it doesn't generalize cleanly to every kind of tic (it works because counting is inherently sequential and legible across a cut — a physical habit like a limp doesn't carry the same "time has passed" information). Logged as a specific flavor option, not a general rule.

**"Walk through history" as a future video type (deferred, not now).** Correction to an earlier note in this doc: the archived vision-initial-thoughts.md described this as an interactive, navigable environment, but that framing was a mistake in that old doc, not the actual intent. The real idea is simpler and entirely compatible with a linear YouTube video: a character walking through a piece of history, with the environment/setting changing around them to show progression over time — its own video type, leaning more educational than the character-driven format above, but not fundamentally different in mechanism from what the D-Day dry run already did. Deliberately not started now, per the decision to go deep on one direction (D-Day-style) before reconsidering.

**POV is configurable, not assumed (general principle, applies beyond this one format).** First-person vs. third-person shouldn't be hardcoded anywhere in the pipeline — different scenarios call for different POV, and that choice should be made per video at the narrative stage, the same way audio format (stage 10) already is. Applies to "walk through history" above as much as to any other narrative format.

## Feedback loop (phase 2, once there's data)

Once videos are live and generating real performance data, YouTube Analytics (retention curves, drop-off points, thumbnail CTR, average view duration) gets pulled in periodically. A model summarizes what the data suggests — where viewers drop off, what thumbnail styles outperform others — and those summaries feed back into the rubrics used at the review-gate stages (particularly the narrative quality review and thumbnail generation). You stay the one deciding whether to act on a given insight; the model's role is surfacing patterns, not autonomously rewriting the pipeline or its own code.

Alongside this, a running notes log of your own review judgments (what you rejected and why, at each gate) is worth keeping from day one — this is useful even before there's any YouTube data, and it's the most direct way the "reviewer" models' prompts get sharper over time.

## Open decisions

**Video generation model.** Needs to support image-to-video conditioning (see stage 8). Candidates to evaluate on cost, output quality, and API access: Veo, Kling, Runway, Sora. Not yet decided.

**Image model for previz.** Needs to be cheap and fast since it's the primary quality gate. Not yet decided.

**Research/grounding model.** Needs real web search capability, not just training-data recall, given how much the whole pipeline depends on the fact sheet being accurate. Not yet decided.

**Length format.** Decided, three phases, in this same project (not a second one) since the pipeline itself doesn't structurally change with length — length only affects how many scenes stage 6 produces and how long stage 11's assembly runs.

Phase 1: Shorts only, while the pipeline and its review gates are still being calibrated against real output and real platform behavior. YouTube's Shorts max length is 3 minutes (raised from 60 seconds in October 2024), but the best-performing range is roughly 30–60 seconds, with 50–60 second Shorts substantially outperforming anything under 10 seconds — so scripts should be paced toward that window, not the 3-minute ceiling.

Phase 2: once Shorts are more concrete and the pipeline is proven out, experiment with long-form (10+ min, clears the 8-minute mid-roll ad eligibility threshold) as its own distinct effort — not yet, and not a small extension of the Shorts scripts, since long-form carries meaningfully higher viewer expectations that aren't fully understood yet (see note below).

Phase 3: long-form becomes the primary artifact, with Shorts derived from it as a repurposing stage, per the original "long-form informs Shorts" idea — this is the eventual steady state, reached after phase 2 has been proven out, not the starting point.

A specific open concern flagged in phase 2: an 8+ minute video is scrutinized more heavily by viewers and carries expectations beyond just "more scenes" — pacing variation, escalation, structure across acts, not just a linear extension of a short's beat list. "Length-expansion" (stage 5's note about needing more scenes/texture for long-form) is necessary but not sufficient to meet that bar; what specifically closes that gap is still unresolved and worth dedicated discussion once phase 2 actually starts, not solved by this doc.

**Orchestration.** Partially decided. Each pipeline stage's model choice (provider + specific model version) lives in configuration, not hardcoded into that stage's code — swapping models, including trying models like DeepSeek alongside Claude, or moving to a newer version of a model already in use, is a config edit, not a code change. The integration layer is LiteLLM (open-source Python library, `pip install`/`uv add litellm`), which exposes one `completion(model="<provider>/<model-name>", messages=[...])` call that works uniformly across 100+ providers including Anthropic and DeepSeek, normalizing the response format so stage code doesn't need provider-specific branches.

Explicit rule: model versions are pinned in config and changed only by a human decision — never automatically. LiteLLM has an optional Router feature that can auto-fallback to a different model on failure/rate-limit; this pipeline will not use that feature, at least for now, specifically to avoid any model substitution happening without the person running the pipeline being aware of it. Plain `completion()` calls with an explicit pinned model string are the only mechanism used.

Still undecided: the actual control flow that calls each stage in sequence and pauses for review (a script vs. something more structured) — worth revisiting once stages 2–7 have real code to review, per the "build and review the cheap text stages before touching image/video vendors" plan already agreed on.
