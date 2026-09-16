# 47. Reference conditioning becomes optional

Date: 2026-09-16

Status: Accepted

Makes [0024](./0024-previz-image-conditioning.md) a choice rather than a fixture.

## Context

Reference-image conditioning has been mandatory since 0024, which introduced it when this project was about historical accuracy and location fidelity mattered. Its recorded justification still stands on its own terms: "text description alone, even good text description, already failed" at holding a location steady across beats.

Since then the evidence against it has accumulated, and the case for testing its removal is now stronger than the case for keeping it unexamined:

- The reference-anchor experiment's no-reference arms won camera picks where the shipped arm won none.
- The conditioning bake-off showed a clean dose-response on `prompt_strength`: a stronger reference gave 0/3 on camera, weaker gave 2/3, none gave 2.5/3.
- Four candidates generated for one beat came back visibly similar to each other, which is what heavy conditioning looks like from the outside.
- This project's own style A/B, which produced the most compositionally varied images it has made, used plain text-to-image with no references at all.
- `failure-taxonomy.md` has carried an unresolved entry since 2026-09-02: two beats sharing a location rendered near-identical images. Fourteen runs since have had multiple accepted beats in one location. The project owner's summary: "a different shot might happen in the same room at a different angle and i've never seen that actually happen with the current reference system."

Worth recording honestly: the immediate cause of this ADR was the project owner pushing back on a pattern in the assistant's reasoning. Having found one good image that was produced *with* references, the assistant had begun treating it as evidence for keeping them -- "we're trying to find any excuse to keep it when all we want to do is pry the damned control of the camera back into our own hands." A single favourable example is not evidence, and that is exactly the standard this project has been applying to everything else.

## Decision

`--references {both,location,character,none}`, defaulting to `both`, which is the previous behaviour exactly.

Granular rather than a boolean, because the two references are separate hypotheses: a location reference was added to stop cross-beat setting drift, a character reference to hold identity. Both also pin composition, so they need to be testable apart -- and a hybrid, if one turns out to earn its keep and the other does not, is only reachable if they can be varied independently.

A reference that will not be used is not generated, so turning one off saves its cost rather than merely ignoring it.

The cost estimate shown before any spending is corrected at the same time: it counted every reference regardless of this flag, and ignored `--candidates` entirely, so the figure a human confirmed against could understate the real spend several-fold.

## Consequences

**Setting and style drift are the expected cost, and there is no solution for them yet.** 0024's finding was real. Running with `--references none` should be expected to produce rooms that differ between beats, and possibly style that drifts too. That is the thing to watch for, not a surprise to be disappointed by -- and the owner has already named the shape of the eventual answer: "maybe some sort of hybrid is needed".

**This decides nothing on its own.** It makes an untested assumption testable. The question it exists to answer is whether beats generated without conditioning are more alive -- genuinely different angles of the same room, characters positioned in ways worth looking at -- and whether that is worth the consistency it costs.

**A seed would be the obvious hybrid**, and is not available here: `litellm.image_generation` exposes no seed parameter for Gemini, while `flux-dev` on Replicate has both a seed and a `prompt_strength` dial. The conditioning bake-off's seed-only condition held room and style and camera simultaneously. If drift turns out to be the only real cost of dropping references, that is a direct argument for the previz model question [0038](./0038-video-generation-on-replicate-and-moderation-rescope.md) reopened.
