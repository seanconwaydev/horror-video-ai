# 50. No reference images by default

Date: 2026-09-16

## Status

Accepted. Supersedes [0024](0024-reference-image-conditioning.md) on the
question of whether reference conditioning should be on by default; the
mechanism 0024 built stays, behind `--references`
([0047](0047-references-are-optional.md)).

## Context

ADR 0024 introduced reference-image conditioning: generate a character
reference and a location reference up front, then condition every beat on
them. The premise was that beat text alone could not hold identity across
shots or stop the setting drifting from beat to beat, which was true when
measured.

Two things changed underneath that premise without anyone re-measuring
it. Locations stopped being a single prose blob and became structured
`architecture` / `fixed_props` / `ambient_light` fields. And the run
gained committed style presets ([0033](0033-style-presets.md)), so the
art direction is now stated identically in every beat prompt instead of
being re-invented per beat.

Meanwhile the cost of conditioning turned out to be the camera. Every
beat conditioned on the same reference came back at close to the same
angle, which is the whole reason `--references` was made configurable in
0047.

A four-beat horror run with `--references none` and four candidates per
beat settled it. The project owner's per-beat notes report style holding
on all four beats ("style kept pretty consistent", "style is mostly
consistent", "little bit of style drift but not much", "style is fairly
consistent") and the camera moving on all four ("camera movement is
pretty strong actually", "camera moves quite a bit", "camera changes a
good amount"). Inspecting the images directly, the location's fixed props
also survived with no location reference at all: the stencilled bay
number, the red fire-hose cabinet, the drain grate, the painted lane line
and the subject's own silver hatchback all recur correctly across
non-adjacent beats.

So the structured location text and the style preset were already buying
what the references were being paid for, and the references were charging
composition on top.

## Decision

`--references` defaults to `none`. `both`, `location` and `character`
remain available for a scene where identity or setting genuinely does
drift.

The argument parser moves into `_build_arg_parser()` so a flag default is
assertable in a test without running a pipeline.

## Consequences

A default run generates no reference images, so it is cheaper -- a
four-beat run drops two image generations before any beat is drawn -- and
its beats are free to vary the camera.

The risk 0024 was built for is real and is now unmitigated by default:
nothing structurally prevents a character's face or a room's geometry
drifting between beats. The measured run did not show this, but one
scene's cast and one location is thin evidence, and a scene with several
similar characters is the obvious place it would break down. The flag is
the remedy, and the failure is visible at review before any video is
generated.

This ADR deliberately does not claim reference conditioning was a mistake
in 0024. It claims the premise it rested on was fixed by later work --
structured locations and committed style presets -- and that nobody
re-checked the original finding afterwards. That pattern, a decision
outliving the premise that justified it, is the same one recorded in
[0044](0044-camera-direction-is-not-promptable.md) and
[0037](0037-horror-motion-comic-wan.md); a superseding ADR should name
which other decisions rested on the premise it removes.
