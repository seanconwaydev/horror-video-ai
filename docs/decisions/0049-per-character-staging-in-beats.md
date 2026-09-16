# 49. Beats stage each character individually

Date: 2026-09-16

## Status

Accepted. Supersedes the `character_ids` field introduced by
[0041](0041-beats-name-every-character-present.md).

## Context

A four-beat horror run (`--references none`, four candidates per beat)
produced images the project owner rejected outright on every beat. The
craft was not the problem: style held across all four beats, the camera
moved between them, and the location's fixed props (a stencilled bay
number, a fire-hose cabinet, a drain grate, the subject's own car)
recurred correctly with no reference images at all.

What failed was the people. In the owner's words the two characters were
"not being 'aware' of each other, no cause-and-effect between them, just
kind of standing around or staring at the camera", and the stalker "has
been getting closer, but as though he's teleporting while standing
still."

The images matched the prompts exactly. Reading the plan back:

| beat | the antagonist's verb | how it escalated |
|---|---|---|
| 1 | stands | "no bigger than a finger-height in frame" |
| 2 | is | "roughly a sixth of the frame" |
| 3 | stands | "roughly a third of the frame" |
| 4 | stands | "roughly a quarter of the frame" |

No beat gave the antagonist an action directed at anyone. Beat 3 asked
for "arms hanging long at its sides, head slightly tilted" and got
exactly that -- a character-select T-pose. The escalation existed only as
a fraction of the frame, so the model rendered one motionless man at four
zoom levels.

Three causes, all upstream of the image model:

1. **A beat had one `subject` and one `action`.** The action was authored
   from the subject's point of view, and 0041's `character_ids` could say
   a second character was present but not what they were doing. Every
   non-focal character was therefore staging metadata -- a position, an
   occluder, a fraction of the frame -- which is what the planner wrote.
2. **The prompt rule for an embodied threat asked only about
   prominence** ("roughly what fraction of the frame it occupies, where
   in the frame, what specifically occludes it"). Good advice for
   controlling prominence; it became the antagonist's entire
   characterisation because nothing else was asked for.
3. **Compositional vocabulary was spent on one character.** Beat 4 placed
   the figure "offset hard to the left, never centred" and said nothing
   about where the subject stood, so she landed dead centre in every
   image.

A rule for this already existed and lost: "When two characters interact,
give each a specific reaction to the other ... so they read as one
connected moment, not two independently-posed figures that happen to
share a frame." It was buried at the end of a paragraph about furniture
contact points, was conditional on the planner judging that the
characters were "interacting", and was outcompeted by the much more
concrete prominence rule above. Adding a further instruction would have
been the same bet at worse odds.

## Decision

Replace `Beat.character_ids: list[str]` with `Beat.staging:
list[Staging]`, where each `Staging` carries `character_id`, `action`,
and `frame_position`. Every character visible in a beat gets an entry,
including partially hidden ones.

`Beat.action` survives as one sentence naming the shot's event, and
`subject` survives as a pointer to who the shot is *about* and who should
dominate the frame. All per-character physicality moves into `staging`.

Four planning rules follow the schema, each tied to one observed failure:
a staging `action` must be a physical action done to someone or something
(states like "stands" and "watches" are named and rejected); every
multi-character beat must have at least one entry describing what that
character does *because of* another; an escalation must show in the body
and may not be encoded only as a larger `frame_position`; and every
character gets a `frame_position`, the focal one included.

In the image prompt each character's action is emitted inside that
character's own labelled block (`DOING:` / `POSITION IN FRAME:`) rather
than in one shared `ACTION` paragraph, so the verb binds to the person it
belongs to. Multi-character beats additionally get one line stating the
characters must react to each other.

## Consequences

The schema change is the point: the previous shape had nowhere to put a
second character's intent, so no amount of prompt tuning could reliably
produce it. This is a capability added to the artifact, not another
instruction competing for the planner's attention.

`staging` is editable in the beat review loop and is displayed there
per character, since it is now where a beat's most consequential content
lives.

A plan captured before this field existed still loads: `staging` defaults
to empty, and a planning model that omits it falls back to a single entry
for the first character, which is what every beat rendered with before
0041.

This does not address the other finding from the same run -- that
reference-image conditioning was buying consistency the structured
location and style text already provided, at the cost of camera
variety. That belongs in its own ADR.
