# 52. Compositional vocabulary is unconditional, not genre-routed

Date: 2026-09-16

## Status

Accepted. Narrows [0036](0036-genre-resolves-to-early-routing-signals.md), which
stays in force for everything else it routes.

Rule text superseded by [0054](./0054-one-fact-per-field.md): the decision
to make composition unconditional stands, but asking for it as prose in
`camera` contradicted [0044](./0044-camera-specified-at-a-granularity-models-follow.md)
and produced every camera failure in the 2026-09-17 run.

## Context

Found by the repo audit (`docs/playbook/repo-audit-brief.md`), not by a
bug: the finding is that a rule exists and one genre cannot reach it.

[0036](0036-genre-resolves-to-early-routing-signals.md) resolves a closed
`composition_mode` signal from genre/tone. `_CHAOTIC_COMPOSITION_KEYWORDS`
lists surreal, absurd, nonsensical, chaotic, dreamlike, vaporwave,
bizarre, weird. `horror` matches none of them, so every horror run
resolves to `staged` and gets `_STAGED_COMPOSITION_RULE` -- "clarity
beats complexity", which is about whether a beat reads at a glance and
says nothing about where anything sits in the frame.

Meanwhile `_CHAOTIC_COMPOSITION_RULE` is where the craft vocabulary
lives: asymmetry, off-centre composition, impossible scale, deliberate
refusal of a centred shot. That text was unreachable for this project's
actual genre.

The project owner's standing complaint about generated images is
"composition, the girl just simply being center-stage, lame framing."

Two things partly covered this already and are worth stating so the gap
is described accurately rather than dramatically. [0049](0049-per-character-staging-in-beats.md)
requires a `frame_position` for every character and says to let the
subject sit off-centre; the embodied-threat rule says a threat sits in a
background corner or at a frame edge, "never centered". Both are about
*where a character is placed*. Neither says anything about the geometry
of the shot itself -- what occupies the foreground, what the location's
own lines do, what the empty part of the frame is for.

So the real defect is a categorisation error. Framing technique was
written into a rule about surrealism because that is the run where it
first got written, and it inherited that rule's genre gate. Clarity and
framing are orthogonal axes: a horror shot needs to read at a glance
*and* needs to be composed. Routing the second on a genre keyword makes
as little sense as routing "state the lens" would.

## Decision

Add `_BASE_COMPOSITION_RULE`, which every run gets regardless of genre or
tone. It asks a beat's `camera` to make at least one deliberate
compositional choice about the whole frame and names four concrete ones
to choose among: the subject well off-centre with the empty side left
genuinely empty; a solid near-foreground object the shot looks past; the
location's own lines leading toward or boxing in the subject; or the
subject small and low in a frame mostly filled by the space around them.
It names the default it exists to displace -- "medium shot, eye level,
centred on her" -- as the absence of a choice.

`_STAGED_COMPOSITION_RULE` and `_CHAOTIC_COMPOSITION_RULE` are unchanged
and now layer on top of the base rule rather than being the only place
composition is discussed. `_resolve_composition_mode` is unchanged.

## Consequences

Horror reaches framing vocabulary, which is the immediate point. So does
every other genre, which is the more durable one.

The alternative considered was a third mode keyed on horror/thriller/
dread keywords. Rejected: it would have fixed the observed instance and
left the same trap set for the next genre that matches no keyword list,
and it trends toward one composition mode per genre. Preferring the
general fix over the instance patch is the standing preference here.

The base rule asks for one choice to be *stated*, not for a particular
look, so it does not push runs toward a single house style -- the four
options are deliberately different from each other, and a run may commit
to any of them.

This adds a bullet to a planning prompt the audit has already flagged as
crowded at 32 rules. It is routed into the existing `{composition_rule}`
slot rather than appended as a free-floating rule, and the audit's
open item on rule tier and order should judge it alongside the rest.

Not addressed: whether the previz prompt honours a composed `camera`
field as faithfully as it honours a character's `frame_position`. If
composed camera text turns out to be ignored downstream, that is a previz
problem and belongs in its own ADR -- [0049](0049-per-character-staging-in-beats.md)'s
lesson is that an instruction which already exists and is losing should
move tier rather than be sharpened.
