# 46. Generate several candidates per beat and choose between them

Date: 2026-09-16

Status: Accepted

## Context

Every beat generated exactly one image, which was then reviewed, and on rejection regenerated. So each attempt was a single roll of a non-deterministic process, seen alone, with its predecessor already discarded.

Two consequences, both observed rather than theorised.

**Improvement is indistinguishable from luck.** The project owner's own read of a beat that came out better after retrying: "it's not super obvious it's not just getting lucky". With one sample there is no way to tell a real improvement from variance, which undermines every judgement made from a single run -- including the ones feeding this project's own experiments.

**The money was already being spent.** A real four-beat run generated seven images, 1.8 per beat, and kept one. Those images existed one at a time and each was archived before the next was generated. The cost of seeing several was already being paid; only the opportunity to compare them was missing.

This is the selection tier of the framework this project has been working through. A prompt rule fixes one known failure. A schema constraint fixes a class. Selection improves output **without requiring anyone to know the failure mode in advance** -- which is exactly the position this pipeline is in, with an automated reviewer measured as wrong in both directions ([0043](./0043-one-review-prompt-the-human-decides.md)) and a human already inspecting every beat.

## Decision

`--candidates N` generates N images per beat attempt and asks which to keep.

1. **Every candidate is kept on disk.** They were paid for. They are written as `candidate_<attempt>_<n>.png` and the chosen one stays under its own name, so the run log and the beat gallery both point at exactly the image that was picked.
2. **"None of them" rejects the attempt, not the beat.** The loop then offers the usual accept/retry/edit/feedback/give-up, so rejecting a bad batch is not the same as abandoning the shot.
3. **Selection happens before review.** [0043](./0043-one-review-prompt-the-human-decides.md) already made the reviewer informational; the human choosing among candidates is the decision, and the reviewer's note afterwards informs a possible retry.
4. **`--candidates 1` is the default** and is exactly the previous behaviour: one image named `previz.png`, no selection prompt. A test asserts this rather than trusting it.
5. **Unattended runs take the first candidate.** There is nobody to ask, and picking arbitrarily is at least honest about being arbitrary.

The fan-out is N sequential calls in `cli.py` rather than a provider-side `n` parameter, because `litellm.image_generation` exposes no such parameter for Gemini. A provider that does -- `flux-dev` has `num_outputs` -- could serve the same interface in one call, which is a further argument for the previz model question [0038](./0038-video-generation-on-replicate-and-moderation-rescope.md) reopened.

## Consequences

**Cost is now explicit rather than incidental.** Four candidates per beat costs four images per beat, where the old loop spent an average of 1.8 without ever saying so. That is a real increase if every beat is accepted first time, and roughly neutral against a run that retries twice. The difference is that the spend is chosen up front instead of accumulating one rejection at a time.

**Experiments get cheaper per unit of confidence.** Every eval in this project so far has used a single generation per cell, which is its weakest property -- the anchor experiment's 9/9 and the style A/B's 5-0 all rest on one sample each. Candidate generation gives a way to raise that without new machinery.

**It does not improve any individual image.** Nothing here makes the model better at cameras, or at horror, or at hands. It improves the *selected* image by giving the selection something to choose from, which is a different and smaller claim than the earlier fixes in this sequence made.
