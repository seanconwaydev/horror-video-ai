"""Scene-planning stage -- the pipeline's first, feeding previz. See
docs/decisions/0023-scene-planning-stage.md.

Turns a verified fact sheet into a full plan (characters, locations, and
beats) before any image generation happens -- formalizes what was, until
now, done by hand in a chat session for every real multi-beat scene this
project has produced (Agent Voss, the Pompeii influencer scene). Locations
are a distinct concept from beats, not just a flat shot list: see
docs/playbook/video-generation-prompting.md's location-consistency
findings for why. previz doesn't consume this plan's `Location`/`Character`
references yet -- that's docs/decisions/0024.
"""

from __future__ import annotations

import random
from collections.abc import Callable
from dataclasses import dataclass, field

import litellm

from horror_video_ai.config import get_stage_model
from horror_video_ai.json_utils import parse_json_response


class ScenePlanningError(Exception):
    """Raised when the scene-planning stage's response is missing or malformed."""


@dataclass(frozen=True)
class Character:
    """The playbook's CHARACTER block fields -- a reusable identity
    anchor, later turned into an actual reference image by
    docs/decisions/0024's `run_reference_image_stage`."""

    id: str
    face_build: str
    hair: str
    wardrobe_signature: str
    wardrobe_flexible: str
    distinguishing_detail: str


@dataclass(frozen=True)
class Location:
    """The playbook's LOCATION block fields -- a reusable setting anchor,
    distinct from any one beat's shot-specific camera/lighting choices.
    Later turned into an actual reference image by 0024, reused across
    every beat with a matching `location_id`."""

    id: str
    architecture: str
    fixed_props: str
    ambient_light: str


@dataclass(frozen=True)
class Scene:
    """What the human asked for: when, where, and what happens.

    The planner's input. It used to be a `FactCheckResult`, because a
    verified fact sheet was what fed this stage -- see
    docs/decisions/0069 for why research and fact-check were deleted and
    what the planner needs from a scene now, which is exactly these three
    strings.

    `time` and `place` are a *setting*, not a historical claim: "present
    day" and "an underground car park at night" are the normal case.
    """

    time: str
    place: str
    description: str


@dataclass(frozen=True)
class Staging:
    """What ONE character does in one beat, where they stand, how big they
    read, and what hides them -- one fact per field (docs/decisions/0054).

    Beats used to carry a single `action` string plus a flat list of
    character ids (docs/decisions/0041). That gave the focal character a
    verb and left every other character as staging metadata -- a position
    and a fraction of the frame -- so the planner reliably wrote the
    antagonist as scenery. Across a four-beat run its verb was "stands"
    three times and "is" once, no beat gave it an action directed at
    anyone, and the whole escalation was encoded as frame fraction
    (finger-height -> a sixth -> a third -> a quarter), which rendered as
    one motionless man at four zoom levels. See docs/decisions/0049.
    """

    character_id: str
    #: What this character physically does, acting on someone or something.
    #: A state ("stands", "is present") is what this field exists to prevent.
    action: str
    #: Where this character stands -- in the space, relative to the camera,
    #: and relative to the other characters ("directly between her and the
    #: camera, near enough to touch her"). NOT a frame coordinate: the
    #: eval that split this field found world placement paired with
    #: `size_in_frame` beat a frame coordinate paired with the same size,
    #: 6/6 against 3/6 on whether the depth ordering rendered correctly.
    #: See docs/decisions/0059.
    blocking: str
    #: How much of the image this character occupies ("roughly a third of
    #: the image"). This is the field that carries depth: across four
    #: blind runs, world placement WITHOUT it never once rendered the
    #: right depth ordering (0/10) and world placement WITH it never
    #: failed (14/14). Empty for a plan captured before this field.
    size_in_frame: str = ""
    #: What stands between the camera and this character, and roughly how
    #: much of them survives it. Split out of the old `frame_position`
    #: after a run
    #: where the two halves of that one field scored completely
    #: differently: position was right in 3 of 4 beats while the occlusion
    #: clause in the same sentence was wrong in 4 of 4 ("position is good,
    #: but his hiddenness is 100% wrong"). Position had its own field and
    #: its own prompt line; hiding was prose inside it. See
    #: docs/decisions/0054. Empty for a plan captured before this field.
    occlusion: str = ""


@dataclass(frozen=True)
class Beat:
    """One shot: the 7-part fields (minus setting, which comes from the
    Location this beat points at) plus duration. `location_id` must match
    one of the plan's `Location.id` values."""

    location_id: str
    subject: str
    #: ONE sentence naming the event this shot is about. Per-character
    #: physicality belongs in `staging`, not here (docs/decisions/0049).
    action: str
    camera: str
    lighting: str
    audio: str
    duration_seconds: str
    #: The single composed shape two characters make where they physically
    #: touch, written once from the camera's point of view ("its grey hand
    #: closes round her right forearm at the centre of the frame, her arm
    #: pulled straight between them"). Empty when nobody is touching.
    #:
    #: `staging` describes each character independently, so a grab had no
    #: home in the schema: it existed only as two separate sentences in two
    #: separate entries, and the image model drew two people standing near
    #: each other. A real run's beat wrote "its bare hand is clamped around
    #: Rook's right wrist" and "hauls her right arm back" and rendered no
    #: contact at all. See docs/decisions/0071.
    contact: str = ""
    #: How two characters who are NOT touching are aimed at each other,
    #: written once from the camera's point of view ("he is turned three
    #: quarters toward her across the open hatch, her shoulders square to
    #: him, two paces of bare floor between them"). Empty when the beat
    #: has one character, or when `contact` already describes the shape
    #: they make.
    #:
    #: `contact` gave bodies that meet a field of their own; two that do
    #: not meet still had none, so "they face each other" existed only as
    #: a separate sentence inside each `staging` entry and the image came
    #: back with both of them aimed at the lens. A real beat wrote "its
    #: eyes fixed up onto her face" and "her eyes locked down on the
    #: hatch" and rendered the threat staring into camera. See
    #: docs/decisions/0072.
    facing: str = ""
    #: How much physical force is in this moment and what a frozen frame
    #: shows of it -- "still, nothing moving but her eyes" through to
    #: "violent: the slicker flared out mid-lunge, the lantern swung wide
    #: on its arc, one boot off the grating".
    #:
    #: Every other field is positional (where they stand, how big, what
    #: hides them), so the planner had no vocabulary for force and wrote
    #: stillness in every beat. Empty for a plan captured before this
    #: field. See docs/decisions/0071.
    intensity: str = ""
    #: One entry per character visible in this beat -- not just the focal
    #: one named in `subject`. Replaces the flat `character_ids` list from
    #: docs/decisions/0041, which could say who was present but not what
    #: they were doing (docs/decisions/0049). Defaults to empty so a plan
    #: captured before this field existed still loads.
    staging: list[Staging] = field(default_factory=list)


@dataclass(frozen=True)
class ScenePlan:
    """The reviewable artifact this stage produces -- see cli/review.py's
    per-item review loop (characters, then locations, then beats, in that
    order, docs/decisions/0023)."""

    characters: list[Character] = field(default_factory=list)
    locations: list[Location] = field(default_factory=list)
    beats: list[Beat] = field(default_factory=list)


# One preamble. There used to be two, routed by `requires_grounding`
# (docs/decisions/0034/0035): a historical framing that wove in verified
# claims, and a creative one that explicitly disclaimed accuracy.
# docs/decisions/0069 deleted the research and fact-check stages, so
# there are no claims to weave and nothing to disclaim -- and the
# disclaimer itself was only ever needed to undo the other preamble's
# framing. What remains states the scene and gets out of the way.
_PREAMBLE = """\
You are a shot-list planner for a short video scene. Break the scene \
below into a full plan BEFORE any image gets generated: the character(s) \
involved, the distinct locations the action moves through, and the \
individual beats (shots) that tell the story.

Scene -- Setting: {time}, {place} | What happens: {description}
{genre_tone_line}
{max_beats_line}
"""

# docs/decisions/0036: composition_mode is an early-resolved, closed-set
# routing signal -- generalizing the `requires_grounding` pattern
# (0034/0035, itself deleted by 0069) to a second axis -- computed once from genre/tone before the rule text
# is assembled, rather than left to the planning LLM's own inline
# judgment of hedged prose the way PR #44's "unless genre signals X" rule
# text did before this. Keyword-based on purpose: research
# (docs/playbook/genre-conditioned-pipeline-design.md) recommends
# starting with cheap, debuggable rule-based routing, reaching for a real
# classification call only once real runs show this heuristic
# misclassifying.
_CHAOTIC_COMPOSITION_KEYWORDS = (
    "surreal",
    "absurd",
    "nonsensical",
    "chaotic",
    "dreamlike",
    "vaporwave",
    "bizarre",
    "weird",
)


def _resolve_composition_mode(genre: str | None, tone: str | None) -> str:
    """Closed two-value signal selecting which composition rule group
    applies below: "chaotic" (asymmetric/off-center composition is
    appropriate) or "staged" (the default clarity/single-focal-point
    convention applies)."""
    combined = f"{genre or ''} {tone or ''}".lower()
    if any(keyword in combined for keyword in _CHAOTIC_COMPOSITION_KEYWORDS):
        return "chaotic"
    return "staged"


# docs/decisions/0052: framing vocabulary is craft, not a genre trait, so
# it is unconditional -- the two mode rules below layer a genre-specific
# instinct on top of it rather than being the only place composition is
# ever discussed.
_BASE_COMPOSITION_RULE = """\
- Every beat must make one deliberate compositional choice instead of \
accepting the default, and each part of that choice goes in the field \
that controls it -- never as extra prose in `camera`. Shot size, camera \
height and subject orientation go in `camera`; where each character \
stands goes in their `blocking`; how big they read goes in their \
`size_in_frame`; what stands between the camera and them goes in their \
`occlusion`. Pick at least one and make it concrete: a \
subject well off-centre with the opposite side of the frame left empty; a \
subject small and low with the space around them dominating; or a solid \
near-foreground object the shot looks past. "Medium shot, eye level, \
centred on her" is what the image model produces unasked -- it is the \
absence of a choice, not a choice. Describing the frame's contents in \
`camera` states a character's position a second time, in a field that \
cannot control it, and the two statements then contradict each other.
"""

_STAGED_COMPOSITION_RULE = """\
- Every beat should communicate ONE clear, legible focal action or \
emotion a viewer can read at a glance (the animation principle of \
"staging" -- clarity beats complexity) -- avoid a generic, ambiguous pose \
that could mean anything. If a beat's `action` doesn't make clear what \
the character wants or feels in that moment, it needs more specific \
detail, not more general description.
"""

_CHAOTIC_COMPOSITION_RULE = """\
- Commit fully to a strange, asymmetric, or chaotic composition rather \
than resolving it into something safe, conventional, or centered -- real \
surrealist technique (impossible scale, unlikely juxtapositions of \
unrelated objects, asymmetric or off-center composition, elements that \
don't logically belong together) is what makes it read as genuinely \
strange, not one quirky detail placed in an otherwise ordinary, \
symmetrical, centered shot. Err toward more unexpected, not less. Every \
beat should still communicate one legible focal point -- what the one \
strange thing is -- but the composition around it does not need to be \
centered, symmetrical, or conventional.
"""

_COMPOSITION_RULES = {
    "staged": _STAGED_COMPOSITION_RULE,
    "chaotic": _CHAOTIC_COMPOSITION_RULE,
}

# Another early-resolved, closed-set routing signal, alongside
# composition_mode (0036): whether this
# scene has a threat/antagonist that needs to stay visibly present across
# beats. Added after a real horror test run (2026-09-14) showed the threat
# mentioned in only 2 of 9 beats' text -- previz only ever paints what a
# beat's prompt actually asks for, so an unmentioned threat in most beats
# is a scene-planning gap, not an image-generation one. See
# docs/research/short-form-format-selection.md.
_THREAT_KEYWORDS = (
    "horror",
    "thriller",
    "scary",
    "suspense",
    "creepy",
    "dread",
    "slasher",
    "supernatural",
)


def _resolve_threat_mode(genre: str | None, tone: str | None) -> str:
    """Closed two-value signal selecting whether `_THREAT_PRESENCE_RULE`
    applies below."""
    combined = f"{genre or ''} {tone or ''}".lower()
    if any(keyword in combined for keyword in _THREAT_KEYWORDS):
        return "present"
    return "none"


_THREAT_PRESENCE_RULE = """\
- This is a horror/suspense scene: the protagonist's own motivation and \
emotional register must read as fear/apprehension/dread-driven in every \
beat, not neutral curiosity or a calm errand -- unless the scene's own \
tone explicitly calls for something else (comedic, deadpan, morbid \
curiosity). Investigating a threat should look reluctant, hesitant, or \
tense (a held breath, a flinch, a wary glance back) even when the action \
itself is mundane (walking, reaching for a door); a character exploring a \
genuinely frightening situation with the same calm affect they'd use to \
check the mail undercuts the genre even when the visual threat itself is \
rendered correctly. This is a stronger, genre-specific version of the \
general facial-expression rule stated earlier -- for this genre \
specifically, "some expression" isn't enough; it has to be \
fear-appropriate.
- This is a horror/suspense scene: the central threat must read as present \
across a clear majority of beats, not declared once and then dropped -- \
give most beats some concrete visual trace of it (a shadow, a disturbed \
object, a shape partly behind a near object), even when the beat's main \
action is just the character moving through a space.
- If that threat is an embodied character rather than an environmental \
effect -- a person, a creature, a figure -- define it as a Character and \
GIVE IT ITS OWN `staging` ENTRY on every beat where any part of it is \
visible, however little. Describing it only in a beat's prose is not \
enough: a real run defined a stalking figure, generated its reference \
image, mentioned it once in a lighting field, and produced four beats with \
no antagonist in any of them. Its prominence is controlled by its \
`size_in_frame` and `occlusion`, never by a vague adjective like \
"barely visible" or "half-hidden" -- an image model renders those as a \
bold, centered silhouette. In `size_in_frame` state roughly what \
fraction of the image it occupies; in `blocking` say where it stands \
relative to the camera and the other characters; in `occlusion` name the \
specific object doing the hiding. Its `action` is a separate question and must still give it \
something to DO.
- Give the threat a FACE as well, named in its own `staging` entry's \
`action`, and make it predatory -- teeth bared, eyes narrowed and locked \
on her, head lowered and tracking. Every other expression rule here is \
written for the protagonist, so an embodied threat routinely gets pure \
mechanics and no face at all, and an image model draws a blank one: a \
real run wrote "its burned right hand clamps flat on the hatch's lip and \
hauls its shoulders up out of the floor" and the figure came back looking \
puzzled rather than hunting, and in the next beat, its face "lowered to \
hers" with still no expression named, its body language read as lifting \
her out of danger rather than attacking her. A threat that is not \
visibly enjoying this is furniture.
- An embodied threat is made ominous by OCCLUSION, not by distance. Do \
NOT place it far away from the protagonist or deep in the background: a \
figure written as distant rendered as merely a few feet off in 21 of 22 \
measured images, whatever `size_in_frame` said, so the shot reads as a \
mistake rather than as distance. Put it CLOSE and HIDDEN instead -- \
behind the near edge of a pillar, a door frame, a parked car, or inside \
the fog, smoke or unlit dark the location already has, with `occlusion` \
naming exactly how much of it survives. That is the version \
this pipeline renders reliably, and it is scarier: a thing thirty metres \
away is a thing you have time to escape.
- Across the scene the threat's CONCEALMENT must change, and the moment \
it is noticed is the hinge. While unseen it stays hidden; once the \
protagonist registers it, it stops hiding and commits -- give that beat a \
visibly smaller `occlusion` than the one before, and an `action` that \
comes out from behind whatever was covering it: weight onto the front \
foot, shoulders squared at her, no longer holding still. A threat equally \
hidden in every beat has no story in it, only three poses.
- The beat where the protagonist first sees the threat in the open is the \
TOP of her fear arc, and it has to be written as panic rather than \
concern. A person who has just found a monster a couple of paces away is \
not worried or unsettled: name the face coming apart -- mouth wrenched \
open, eyes stretched white all the way round, chin pulled back into her \
own neck, one arm thrown up between them -- and put the same level in the \
beat's `intensity`. `intensity` on its own will not carry this; it is \
about how much force is in the moment, and a woman standing still with a \
mildly alarmed expression satisfies every other rule here while killing \
the scene. Anything short of the maximum at this beat leaves nowhere for \
the beats after it to go.
- If the scene describes a threat that escalates or transforms gradually \
over its course (a shadow growing more distorted, an environment \
decaying, a sound growing louder), give EVERY beat its own explicit, \
distinct point along that progression -- name specifically what's \
different about it compared to the beat before, not just the scene's \
starting and ending states. No two non-adjacent beats should describe the \
same stage of the progression, and no beat should skip stating the \
progression's current stage, even a beat whose main action is something \
else entirely (walking, reaching for a door). A progression only \
described once, at the start and the end, will not survive into the \
individual beats on its own.
- Whenever a beat's threat is a shadow, that beat's `lighting` field must \
name one single, hard-edged, dominant light source explicitly (e.g. "the \
only light in the frame is X, throwing one sharp-edged shadow onto Y") -- \
a shadow described only through diffuse or multiple weak ambient sources \
frequently fails to render as a discernible silhouette at all, regardless \
of whether its distortion is otherwise described correctly.
"""

_THREAT_RULES = {
    "present": _THREAT_PRESENCE_RULE,
    "none": "",
}

# Real, sourced finding (2026-09-15): LLMs collapse toward a narrow set of
# "default" outputs when a prompt doesn't force variety, and this doesn't
# meaningfully improve with temperature -- research on LLM idea diversity
# found only marginal improvement at 1.5x default temperature, with
# quality degrading badly above that. The reliable fix used in production
# LLM pipelines for this exact problem is injecting randomness in code
# rather than relying on the model's own sampling to produce it -- these
# lists back that: a few structural physical traits are randomly picked
# per call and handed to the model as a required starting point, so
# separate runs of an identical prompt get a genuinely different-looking
# character by construction, not by hoping for it. Deliberately excludes
# race/ethnicity -- randomly assigning that from a canned list is its own
# can of worms distinct from "make each run look different," and isn't
# needed to solve the actual reported problem (the same character
# recurring run after run).
_CHARACTER_AGE_RANGES = (
    "late teens",
    "early 20s",
    "mid-20s",
    "late 20s",
    "early 30s",
    "mid-30s",
    "40s",
)
_CHARACTER_BUILDS = (
    "slight and slender",
    "athletic",
    "average build",
    "stocky",
    "tall and lean",
    "short and sturdy",
)
_CHARACTER_HAIR_STYLES = (
    "a short pixie cut",
    "a shoulder-length bob",
    "long and straight",
    "long and curly",
    "a tight bun",
    "buzzed very short",
    "shoulder-length waves",
    "a messy shag cut",
)
_CHARACTER_HAIR_COLORS = (
    "black",
    "dark brown",
    "light brown",
    "auburn",
    "blonde",
    "gray-streaked",
    "dyed a deep red",
)
_CHARACTER_DISTINGUISHING_FEATURES = (
    "a small scar through one eyebrow",
    "a scattering of freckles across the nose",
    "a septum piercing",
    "wire-frame glasses",
    "a birthmark on the jaw",
    "a chipped front tooth",
    "an ear cuff on one ear",
)


def _random_character_trait_hint(rng: random.Random) -> str:
    """One randomly-assembled starting point for a Character's physical
    traits -- see the lists above for why this exists. `rng` is an
    injection point for tests (pass a seeded `random.Random` for a
    deterministic result)."""
    return (
        f"in their {rng.choice(_CHARACTER_AGE_RANGES)}, {rng.choice(_CHARACTER_BUILDS)} build, "
        f"with {rng.choice(_CHARACTER_HAIR_STYLES)} in {rng.choice(_CHARACTER_HAIR_COLORS)} hair, "
        f"and {rng.choice(_CHARACTER_DISTINGUISHING_FEATURES)}"
    )


_CHARACTER_VARIETY_RULE = """\
- Vary each Character's physical appearance meaningfully across separate \
runs of this same pipeline -- left with no explicit physical description \
in the scene itself, an LLM defaults to a narrow, generic "protagonist" \
look that recurs nearly identically run after run, even though nothing \
about the scene requires it. Unless the scene's own description states a \
character's physical traits explicitly, build that Character's \
`face_build`/`hair`/`distinguishing_detail` fields around this specific \
starting point rather than inventing your own generic default: a person \
{character_trait_hint}. Adjust or override any part of it the scene's own \
description actually contradicts.
"""


# docs/decisions/0071. Unconditional, like the base composition rule
# (0052): the ceiling is a property of the image model, not of a genre.
_COMPLEXITY_BUDGET_RULE = """\
- Budget each beat's complexity instead of maximising it. An image model \
has a hard ceiling on how many things it can hold at once, and past it \
the whole frame degrades rather than just the last detail. Across a \
beat's `action`, `lighting`, `contact`, `facing` and every `staging` \
entry together, name no more than about five things the image must get \
right, and \
drop the least important one rather than keeping it. A beat a human \
cannot picture from its own text will not be rendered correctly either.
- One beat is ONE SPACE: everything the frame shows must be inside the \
`location_id` this beat points at. Do not ask a single shot to hold an \
interior and the structure outside its windows, a room and the floor \
below it, or a corridor and what is at the far end of another corridor. \
A beat that stayed inside one space rendered cleanly while the beat \
before it, splitting attention between a cabin interior and the tower \
underneath, did not. If the action needs the other space, that is a \
different beat, and the camera goes there.
- Never put a CHARACTER'S REFLECTION in a beat -- not in glass, a mirror, \
a window, water or polished metal, in any field. Image models do not \
render a reflected person as a reflection; they render a second copy of \
that person standing in the frame, which reads as a continuity error \
rather than as the effect intended. Reflected LIGHT is fine and often \
good: a beam thrown across wet ground, a glow on a pane, a sweep of a \
beacon over metal. It is reflected people that are banned.
- Leave out physical minutiae a still frame at phone resolution cannot \
carry: a character's visible breath, individual beads of condensation, \
a chipped tooth seen from across a room, the exact grain of a surface. \
Each one spends part of the budget above and none of them survives into \
the picture.
- One dominant light source per beat, named in `lighting`, with anything \
else clearly secondary. Two competing sources of similar strength \
produce a flat, sourceless image with no readable shadow.
"""


_PLANNING_RULES_AND_SHAPE = """\
Planning rules:
{complexity_budget_rule}\
- A LOCATION is one physical space the action happens in -- if the scene \
visits multiple distinct spaces (e.g. a street, then a building's \
interior), each is its own Location. Describe architecture in physical, \
concrete terms (materials, fixed structures), not aesthetic ones.
- A BEAT is exactly one moment/shot, never more -- do not describe \
multiple sequential actions in one beat's `action` field. Every beat must \
reference a `location_id` matching one of the Locations you define.
- A Character's `face_build`, `hair` and `distinguishing_detail` describe \
what that character permanently LOOKS LIKE -- never what they are doing. \
Those fields are repeated in every single beat's prompt and baked into the \
character's reference image, so a pose or behaviour written there ("stands \
perfectly still with both arms straight at its sides", "always holds a \
lantern") becomes an instruction the character can never escape in any \
shot. Physical markers only: scars, piercings, glasses, build, hair, \
distinctive features. Anything about posture, movement or habitual \
behaviour belongs in a beat's `action` instead, where it can change from \
shot to shot.
- Every beat must give a `staging` entry to EVERY character visible in \
that shot, including partially visible ones -- a figure in the \
background, a silhouette in a doorway, a hand at the frame edge. Only \
characters staged there can be drawn; a character you define but never \
stage in any beat will be given a reference image and then never appear \
in a single frame. `subject` names which of them the shot is *about* and \
should dominate the frame; `staging` says who is actually in it and what \
each of them is doing.
- A beat's `action`/`lighting`/`camera` text must be physically possible in \
the Location it's assigned to -- if the scene's description mentions a \
distinct space (a bedroom, a bathroom, a car), that space needs its own \
Location with its own id, and any beat set there must use that \
`location_id`, not a different, physically incompatible one (e.g. never \
describe a character lying in bed, near a headboard/nightstand, if the \
beat's `location_id` points at a hallway, landing, or stairwell Location \
that has no bed in its own `fixed_props`). Check this explicitly before \
finishing the plan: for each beat, does its own location's `architecture`/\
`fixed_props` actually contain what the beat's `action`/`lighting` \
describes interacting with?
{character_variety_rule}\
- Every beat's `action` field must state the character's facial \
expression/emotion explicitly, not just their physical action -- image \
models default to a flat, neutral expression unless a specific emotion is \
named outright (e.g. "her jaw tightens, eyes wide with fear" rather than \
just "she listens"). Never write a beat's `action` describing only body \
movement or position with no stated facial expression or emotional state.
- State WHERE THE EYES ARE POINTED as well as what the face is doing, and \
point them at something named in the beat. A person who senses something \
behind them strains their eyes toward it before their head arrives -- \
"her eyes cut hard to the right, whites showing on the far side, her head \
only starting to follow". Fear with the eyes aimed at nothing reads as \
distraction, not fear: a real run produced a woman who "looks scared but \
is just looking randomly" while the threat stood behind her. Do this in \
EVERY `staging` entry too, not only in the beat's own `action` -- an \
entry is the only text bound to that one character, so eyes named once \
at beat level leave everybody else aimed at nothing. A beat whose \
`action` read "she stares past her own pinned arm at the thing crouched \
over her" but whose `staging` entry for her named no eyes at all came \
back with her looking off into the distance in three of four candidates.
- If the scene describes or implies a character's emotional state \
building or shifting over its course (fear or dread escalating, \
excitement rising, calm curdling into panic), give every beat its own \
distinct, specifically-named point along that arc -- not just the \
scene's starting and ending emotional states repeated. This is the same \
escalation-arc requirement that applies to a visually escalating threat, \
generalized to the character's own face and body.
- Vary camera framing deliberately per beat rather than defaulting every \
shot to facing the camera -- a character can face away from camera, be \
seen in profile, or be shot from behind, whenever that's the more natural \
choice for what's happening in that beat.
- The `camera` field must be written in the three terms an image model \
actually acts on, and nothing else: SHOT SIZE (extreme wide / wide / \
medium / close-up / extreme close-up), CAMERA HEIGHT (high above / eye \
level / low / ground level), and SUBJECT ORIENTATION (facing camera / \
three-quarter / profile / from behind). Do NOT specify where the camera \
stands in the world -- "from a ceiling corner at the west end", "beside \
the boot of the car in bay 15", "camera east of the aisle" are all \
wasted: an image model does not place a virtual camera in your location's \
floor plan, and a beat's composition comes mostly from its reference \
image regardless. Naming a position the model cannot honour only \
guarantees the shot fails its own description.
- When multiple beats share a `location_id`, give them real "coverage" \
(the standard film-production term) using exactly those three terms: no \
two consecutive beats should share the same combination. A wide high shot \
from behind, then a medium eye-level three-quarter, then a low close-up \
in profile. The same framing repeated can be a legitimate deliberate \
choice for a specific effect, but must never be the unplanned default \
outcome of two beats sharing a location.
- Beyond camera position, also place the character at a genuinely \
different physical position *within* that location's own space for each \
beat that shares it, whenever the location's own geography supports it -- \
a staircase has a top, a middle, and a bottom; a hallway has a near end \
and a far end; a room has multiple walls and corners. Two beats at "the \
staircase" reading as basically the same image is usually this specific \
gap: state explicitly where in the space the character is (e.g. "near \
the top step" vs. "three steps from the bottom"), not just a pose or \
camera change layered onto an otherwise identical composition.
- Also vary the character's body position and what they're physically \
doing across beats -- avoid repeating the same standing position, \
orientation, and pose in consecutive beats at the same location. Give \
each beat a distinct, concrete physical action (reaching, turning, \
stepping, sitting, gesturing). A slightly different look for the \
character between beats (hair catching light differently, a minor \
pose-driven wardrobe shift) is fine and expected -- prioritize dynamic, believable movement over rigid \
visual sameness.

- Keep SCREEN DIRECTION consistent across consecutive beats at the same \
location -- if the character moves or faces toward the left of frame in \
one beat, keep that in the next unless something in the story turns them \
around. This is the readable half of the 180-degree rule: which way the \
subject faces within the frame is something an image model can honour, \
whereas which side of an imaginary line the camera sits on is not, so \
state the former and never the latter.
- Give each beat a clear anticipation beat when it helps: a brief, \
readable lead-in to the main action (a breath, a shift of weight, a \
glance) rather than starting the beat already mid-action with no setup -- \
this gives a viewer, and the eventual video-generation step, a clearer \
sense of what's about to happen.
- Add a concrete secondary action when it reinforces what's happening -- \
a small supporting detail beyond the main pose (hair or fabric caught by \
wind, a hand tightening on a strap, steam rising) rather than a flat, \
static figure with nothing else happening in frame. Keep it subtle for a \
photorealistic scene and can be more pronounced for a stylized one.
{composition_rule}\
{threat_rule}\
- When a beat places a character near furniture or props (sitting at a \
table, leaning on a counter), describe the specific point of contact \
explicitly (e.g. "her feet rest flat on the floor in front of the low \
stool," "her forearm rests on the counter's edge") rather than leaving \
the spatial relationship implicit -- image models have a documented \
tendency to merge a limb into nearby furniture with no clear boundary \
between them when contact isn't specified precisely.
- Every `staging` entry's `action` must be a physical action done TO \
someone or something -- reaching for a door handle, stepping between two \
pillars, turning away from the noise, pressing a palm flat to the wall. \
"Stands", "is present", "waits", "watches" and "is visible" are states, \
not actions; a character given one of those is rendered upright, arms at sides, facing camera, \
like a character-select screen. This applies to a background or \
partially-hidden character exactly as much as to the focal one.
- Write that action as the frozen instant, not the movement through it. \
One still frame cannot show "spinning", "trembling", "turning", "leaning \
out" or "lowering" -- there is no before-and-after in a single image, so \
a process verb renders as the character standing still. Name the \
configuration a camera would freeze: which foot carries the weight, how \
far the torso is twisted from the hips, where the hair has already swung \
to, which hand has already closed on what.
- In EVERY beat with more than one character, the NON-FOCAL character's \
own `action` must take another character as its OBJECT -- reach for her, \
close a hand on her arm, put its face at hers, block the door she is \
moving toward. An action performed on scenery is not enough, however \
menacing the scenery makes it look: a real run put a stalking figure in a \
car with its victim and gave it "braces its shoulders into the rear bench \
cushion", "hands planted flat on the seat cushion", "hands closed on the \
top edge of the seat back" across all three beats. Every one of those is \
an action on upholstery, and the images read as two people sitting in a \
car together.
- The focal character must also react to them -- a flinch away, a step \
that puts something between them, a hand that stops halfway to a pocket. \
But that reaction ALONE does not satisfy the rule above: a victim \
reacting to a threat that is doing nothing to her is the exact failure \
this pair of rules exists to prevent.
- Whenever two characters physically TOUCH in a beat -- a grab, a hand \
on a shoulder, a body pinned against a rail -- you must also fill in that \
beat's `contact` field, and write it as ONE shape seen from the camera, \
not as two people's separate movements: "its grey hand closes round her \
right forearm at the centre of the frame, her arm pulled straight between \
them, their two bodies overlapping from this angle". Each `staging` entry \
describes one character on their own, so a grab written only there is two \
unrelated sentences, and the image comes back as two people standing near \
each other not touching. A real beat said "its bare hand is clamped around \
her right wrist" in one entry and "hauls her right arm back toward her \
sternum" in the other, and rendered no contact whatsoever. Name the two \
body parts that meet, where in the frame they meet, and what the contact \
does to the shape of both bodies. Leave `contact` empty only when nobody \
is touching anybody.
- Whenever a beat has two or more characters who are NOT touching, fill \
in that beat's `facing` field instead, and write it the same way -- ONE \
line seen from the camera saying which way each of them is turned \
relative to the other and how much space is between them: "he is turned \
three quarters toward her across the open hatch, her shoulders square to \
him, two paces of bare floor between them". `camera` carries a single \
subject orientation for the whole shot, and `staging` describes each \
character alone, so without this field "they face each other" is only a \
sentence in each of their separate entries and the image comes back with \
both of them aimed at the lens. A real beat gave the threat "its eyes \
fixed up onto her face" and the protagonist "her eyes locked down on the \
hatch" and rendered the threat staring straight into camera past her. \
Say it once, for the pair. Leave `facing` empty for a one-character beat, \
or when `contact` already describes the shape the two of them make.
- Every beat needs an `intensity`: how much physical force is in this \
moment, plus the evidence a single frozen frame would show of it. Every \
other field on a beat says where people are and how big they read, so \
with no field for force the whole scene comes out still, and a threat \
that never moves is what this pipeline keeps producing. State the level \
and then the frozen proof of it: "still -- nothing moving but her eyes"; \
"sudden -- her hair already swung past her cheek, one heel off the \
floor"; "violent -- the slicker flared out mid-lunge, the lantern swung \
wide on its arc, one boot clear of the grating, her sleeve wrenched out \
of shape where the hand has hold of it". Force in a still image reads \
through displaced hair and fabric, weight thrown off balance, limbs \
splayed past their resting line and objects caught out of position -- \
name those, never a process verb.
- `intensity` must CHANGE across the scene and must reach a real peak. A \
scene whose every beat is quiet has no escalation in it, only a series of \
poses. Horror in particular is not only the silent watcher: a threat that \
is loud, fast, angry and physically committed -- lunging, seizing, \
thrashing, bearing a victim backwards -- is most of the genre, and a \
figure that merely stands present in every beat while nothing happens to \
anyone reads as bored rather than frightening. If the scene builds to \
violence, the last beats must say so in `intensity`, in `contact` and in \
each character's `action` together.
- Let the LOCATION escalate too, not only the people in it. When several \
beats share a `location_id`, every later beat should show physical \
evidence of what has already happened there -- a chair gone over, a lamp \
down on the floor throwing its light from a new angle, a door that was \
shut now standing open, paper off the table and scattered. State the \
change in that beat's `intensity` or `action` so the frame has to show \
it, and never quietly reset a space to undisturbed once something has \
disturbed it. This is the cheapest escalation available: the props are \
already in the location's `fixed_props`, the shot does not have to hold \
anything new, and on a real run a single overturned chair sold a struggle \
better than any description of the struggle did.
- If a character gets closer, more threatening, or more exposed as the \
scene progresses, that change must show in the BODY -- a stoop, a reach, \
weight shifted onto the front foot, a hand leaving a pocket. Never encode \
an escalation only as a larger `size_in_frame`: a real run escalated a \
stalker purely from "finger-height in frame" to "a quarter of the frame" \
and got one motionless man rendered at four zoom levels.
- Only stage characters the camera can actually SEE. `staging` is the \
list of people the image model will draw, so a character behind a solid \
floor, on the far side of a wall, in another room, or outside the frame \
does not get an entry at all -- not even a tiny one. Asking for a \
character that is both invisible and a stated fraction of the picture is \
a contradiction, and the image model settles it by drawing them somewhere \
arbitrary. It is then unfixable: no human correction can move a figure to \
a place the plan never named. A real beat put a threat a floor below the \
camera, behind the metal grating the camera was standing on, and still \
asked for a sixth of the image height. If the threat needs to be seen, \
put it in the same space as the camera and hide it partially with \
something the camera can see past.
- Give EVERY character a `blocking`, a `size_in_frame` AND an \
`occlusion`, including the focal one.
- `blocking` says where they STAND and nothing else -- their place in \
the space, relative to the camera and to the other characters. Write it \
as a position in the room, not as a position in the picture: "on the same \
floor directly between her and the camera, near enough to touch her", \
"on the rear bench directly behind the driver's seat". Do NOT write \
"left third of frame" or "upper-left" here -- a frame coordinate is a \
projection of where someone stands through a particular camera, and \
asking for it produced a beat that placed a standing man at ceiling \
height. Do NOT state which way they FACE here either: that belongs in \
`action`, with the rest of what the body is doing. A real run wrote \
`blocking` "facing the windscreen" while the same character's `action` \
had her turning back over her shoulder at the thing behind her, and the \
image obeyed the `blocking` -- she stared out of the windscreen at \
nothing while the threat sat behind her unnoticed.
- `size_in_frame` says how much of the image they occupy -- "roughly a \
third of the image", "about a quarter of the image height", "a tenth of \
the image width". This is the field that makes depth render: across four \
blind runs, blocking WITHOUT a size never once produced the right depth \
ordering (0 of 10 images) and blocking WITH one never failed (14 of 14). \
Give every character one, always.
- `occlusion` names what physically stands between the camera and them \
and roughly how much of them survives it -- "the pillar's near face \
covers everything but his left shoulder and half his head", "nothing, she \
is fully in the open". An occluder does not have to be solid: fog, smoke, \
rain, spray and unlit darkness hide a figure as well as an object does, \
and are usually the better choice when the location already has one -- a \
run set in a fogged-in forest hid its threat behind a pine trunk and left \
it otherwise fully lit, with the fog concealing nothing in any beat. \
Write an atmospheric occluder to exactly the same standard as a solid \
one, naming what survives it: "the fog between him and the camera leaves \
the lantern's halo and a head-and-shoulder silhouette, no face". What \
fails to render is a vague adjective, not a soft occluder. Keep all three \
separate: `blocking` is WHERE THEY \
STAND, `size_in_frame` is HOW BIG THEY READ, `occlusion` is WHAT HIDES \
THEM. Hiding written into either of the other two is ignored -- across a \
four-beat run the position half of a combined field was right in three \
beats while the hiding half was wrong in all four, because position had \
its own field and hiding was prose inside it.
- If a Genre and/or Tone are given above, let them actually shape staging, \
expression, and wardrobe choices -- a comedic/ironic tone reads through \
confident, knowing expressions and poses (not just a funny premise \
description); a wholesome tone reads through soft, open body language; a \
dramatic tone reads through tension and restraint. Don't just repeat the \
genre/tone back in prose -- show it in what the character is doing.

Respond with ONLY a JSON object (no prose, no markdown fences) matching \
this exact shape:

{{
  "characters": [
    {{"id": "<short id>", "face_build": "...", "hair": "...",
      "wardrobe_signature": "...", "wardrobe_flexible": "...",
      "distinguishing_detail": "..."}}
  ],
  "locations": [
    {{"id": "<short id>", "architecture": "...", "fixed_props": "...",
      "ambient_light": "..."}}
  ],
  "beats": [
    {{"location_id": "<must match a location id above>", "subject": "...",
      "action": "<ONE sentence: the event this shot is about>",
      "staging": [
        {{"character_id": "<a character id above>",
          "action": "<what THIS character physically does, acting on someone or something>",
          "blocking": "<where they STAND -- in the space, relative to the camera and
            to the other characters. Not a frame coordinate>",
          "size_in_frame": "<how much of the image they occupy>",
          "occlusion": "<what physically hides them and how much survives, or 'nothing'>"}}
      ],
      "contact": "<the ONE shape two touching characters make, seen from the camera;
        empty string if nobody is touching anybody>",
      "facing": "<the ONE line between two characters who are NOT touching -- which way
        each is turned relative to the other and the space between them, seen from the
        camera; empty string for a one-character beat or when 'contact' is filled in>",
      "intensity": "<how much physical force is in this moment, and what a frozen
        frame shows of it>",
      "camera": "...", "lighting": "...",
      "audio": "...", "duration_seconds": "..."}}
  ]
}}
"""


def _require_str_fields(item: dict, fields_: list[str], *, item_desc: str) -> None:
    for f in fields_:
        if not isinstance(item.get(f), str) or not item[f]:
            raise ScenePlanningError(f"{item_desc} is missing or has an empty '{f}'")


def check_unique_ids(items: list, *, label: str) -> None:
    """Raise ScenePlanningError if any two `items` (Character or Location
    objects, or anything with an `.id`) share an id -- reused by
    `_parse_scene_plan` (the LLM's raw output) and by cli/review.py's
    `review_scene_plan` (after a human edit could just as easily
    introduce a collision the LLM didn't). A silent collision would make
    `character_refs`/`location_refs` -- plain dicts keyed by id -- drop
    one item's reference image in favor of another's without any warning.
    """
    ids = [item.id for item in items]
    if len(ids) != len(set(ids)):
        dupes = sorted({i for i in ids if ids.count(i) > 1})
        raise ScenePlanningError(f"Duplicate {label} id(s): {dupes}")


_POSE_IN_IDENTITY_PATTERNS = (
    "perfectly still",
    "arms straight at",
    "head tilted",
    "hands at his side",
    "hands at her side",
    "arms at his side",
    "arms at her side",
)

#: Sentence-initial verbs that usually make an identity field a behaviour
#: description. Anchored to the start so a garment term like "a standing
#: collar" doesn't trip it. Deliberately over-eager -- "stands a full head
#: taller" is height, not posture, and trips this. That is affordable
#: because the result is a printed warning, not a failed run (0048).
_POSE_LEADING_VERBS = ("stands", "sits", "holds", "leans", "walks", "moves", "keeps")


def identity_field_pose_warnings(characters: list) -> list[str]:
    """Warn where a Character's identity fields look like they describe a
    pose or behaviour rather than persistent appearance.

    `face_build`, `hair` and `distinguishing_detail` are emitted verbatim
    into every beat's prompt and baked into the reference image, so a pose
    written there is repeated on every frame and the character can never
    escape it -- docs/decisions/0042, which was prompted by a stalking
    figure whose `distinguishing_detail` read "Stands perfectly still with
    both arms straight at its sides and its head tilted slightly to one
    shoulder".

    **Warns rather than raises** (docs/decisions/0048). This is a keyword
    heuristic, and the first thing it did on a real run was reject
    "stands a full head taller than an ordinary adult" -- a description of
    height, not posture -- killing the run after a paid planning call and
    before the human could edit anything. Worse, phrases like "head
    tilted" are legitimate permanent traits for exactly the uncanny
    characters this project generates. A heuristic this fallible belongs
    in front of the human who is already reviewing every character, not in
    front of the parser.
    """
    warnings = []
    for character in characters:
        for field_name in ("face_build", "hair", "distinguishing_detail"):
            value = getattr(character, field_name)
            lowered = value.lower()
            found = sorted({p for p in _POSE_IN_IDENTITY_PATTERNS if p in lowered})
            found += [v for v in _POSE_LEADING_VERBS if lowered.startswith(v)]
            if found:
                warnings.append(
                    f"Character {character.id!r}'s {field_name!r} may describe a pose rather "
                    f"than appearance ({', '.join(found)}): {value!r}. That field repeats in "
                    "every beat's prompt, so a pose there is one the character can never "
                    "escape -- consider moving it to a beat's action."
                )
    return warnings


def check_beat_character_references(beats: list, characters: list) -> None:
    """Raise ScenePlanningError if a beat names a character id that no
    Character defines, or names none at all.

    Beats used to carry a single `subject` id and nothing else, so a plan
    could define an antagonist, spend money generating its reference image,
    and then have no way to put it in a frame -- which is exactly what
    happened on a real run: the threat appeared in zero of four beats
    (docs/decisions/0041). A prompt rule asked for threat presence that the
    data model could not express.

    Re-run after human edits, like the other checks here, for the reason in
    docs/decisions/0028.
    """
    if not characters:
        return  # nothing to check against; a plan with no cast is checked elsewhere
    known = {c.id for c in characters}
    for beat in beats:
        if not beat.staging:
            raise ScenePlanningError(
                f"A beat at {beat.location_id!r} has an empty 'staging' -- every beat must "
                "give every character visible in it an entry, even if that is just one."
            )
        unknown = [s.character_id for s in beat.staging if s.character_id not in known]
        if unknown:
            raise ScenePlanningError(
                f"A beat references character id(s) {unknown}, which don't match any defined "
                f"character ({sorted(known)})."
            )
        seen = [s.character_id for s in beat.staging]
        if len(seen) != len(set(seen)):
            raise ScenePlanningError(
                f"A beat at {beat.location_id!r} stages the same character twice: {seen}. "
                "One entry per character -- put everything they do in that one entry."
            )



#: Occlusion wordings that mean "the camera cannot see this character at
#: all". A staged character is one the image model is told to draw, so a
#: total occluder there is a plan contradicting itself -- and the model
#: resolves the contradiction by drawing them anyway, wherever it likes.
_TOTAL_OCCLUSION_PATTERNS = (
    "completely hidden",
    "entirely hidden",
    "fully hidden",
    "hidden entirely",
    "completely covered",
    "entirely covered",
    "completely obscured",
    "entirely obscured",
    "not visible",
    "no part of",
    "out of frame",
    "off frame",
    "off-camera",
    "off camera",
    "out of shot",
    "outside the frame",
)


def check_staging_visibility(beats: list) -> None:
    """Raise ScenePlanningError if a beat stages a character it also says
    the camera cannot see.

    `staging` is the list of characters the image model is told to draw,
    and every entry carries a `size_in_frame` claiming a share of the
    picture. A plan that assigns a share of the frame to something it has
    also placed behind a total occluder has stated two incompatible facts,
    and the image model resolves that by drawing the character in an
    arbitrary place at an arbitrary size -- which is unfixable by human
    feedback, because no correction can name a position the plan never
    gave. A real run put a threat "on the stair landing one flight below
    the catwalk" behind "the floor grating of the catwalk above" and still
    asked for a sixth of the image height; telling it to be smaller and
    further away simply moved it somewhere else arbitrary
    (docs/decisions/0071).

    A character the camera genuinely cannot see belongs out of `staging`
    altogether. Partial occlusion -- the case this project relies on for
    threat presence -- is untouched: "covers everything but one shoulder"
    names what survives and is not caught here.

    Re-run after human edits, like the other checks here
    (docs/decisions/0028).
    """
    for beat in beats:
        for staged in beat.staging:
            lowered = staged.occlusion.lower()
            hit = next((p for p in _TOTAL_OCCLUSION_PATTERNS if p in lowered), None)
            if hit is None:
                continue
            # "covers everything but his left shoulder" is partial, and
            # several of the patterns above appear inside exactly that
            # construction ("no part of him survives" vs "no part of him
            # but the hand"). An explicit exception clause means the plan
            # named what the camera still sees, which is what this check
            # is asking for.
            if any(word in lowered for word in (" but ", " except ", " apart from ", " save ")):
                continue
            raise ScenePlanningError(
                f"A beat at {beat.location_id!r} stages character {staged.character_id!r} "
                f"but its 'occlusion' says the camera cannot see it ({hit!r}: "
                f"{staged.occlusion!r}), while 'size_in_frame' claims "
                f"{staged.size_in_frame!r} of the picture. A character the camera cannot "
                "see must not be staged at all; if it should be visible, say what part of "
                "it survives the occluder (docs/decisions/0071)."
            )


#: Opaque surfaces that a camera cannot see through at all. Named as an
#: occluder these usually mean the character is in a different space from
#: the camera, which is the beat-2 failure in docs/decisions/0071 -- but
#: they are also legitimate partial occluders from the right angle (a
#: figure behind a wall's near corner), so this warns rather than raises.
_SOLID_OCCLUDER_WORDS = ("floor", "ceiling", "grating", "roof", "ground")


def beat_visibility_warnings(beats: list) -> list[str]:
    """Warn where a beat looks like it is asking one frame to show two
    separate spaces, or to show a person reflected.

    Both are failures of the same kind: the plan is legible as prose and
    unrenderable as one image. Warnings rather than errors, following the
    identity-field heuristic's reasoning (docs/decisions/0048) -- these
    are keyword matches over free text, and the human is already reviewing
    every beat.
    """
    warnings = []
    for n, beat in enumerate(beats, start=1):
        for staged in beat.staging:
            lowered = staged.occlusion.lower()
            solid = sorted({w for w in _SOLID_OCCLUDER_WORDS if w in lowered})
            if solid:
                warnings.append(
                    f"Beat {n} hides {staged.character_id!r} behind {', '.join(solid)} "
                    f"({staged.occlusion!r}). A camera cannot see through those, so this "
                    "usually means the character is in a different space from the camera "
                    "-- one frame cannot show both (docs/decisions/0071)."
                )
        text = " ".join(
            [beat.action, beat.lighting, beat.contact, beat.facing]
            + [s.action for s in beat.staging]
        ).lower()
        if "reflect" in text or "reflection" in text:
            warnings.append(
                f"Beat {n} describes a reflection. A reflected person renders as a second "
                "copy of that person standing in the frame, not as a reflection "
                "(docs/decisions/0071). Reflected light is fine; a reflected character "
                "is not."
            )
    return warnings


def check_beat_location_references(beats: list, locations: list) -> None:
    """Raise ScenePlanningError if any beat's location_id doesn't match a
    defined location -- reused by `_parse_scene_plan` (the LLM's raw
    output) and by cli/review.py's `review_scene_plan` (after a human edit to
    either a beat's location_id or a location's id could just as easily
    break the reference the LLM originally got right)."""
    location_ids = {loc.id for loc in locations}
    for beat in beats:
        if beat.location_id not in location_ids:
            raise ScenePlanningError(
                f"A beat references location_id {beat.location_id!r}, which doesn't match "
                f"any defined location ({sorted(location_ids)})"
            )


def _parse_staging(item: dict, characters: list, *, strict: bool) -> list[Staging]:
    """Parse one beat's `staging` list.

    `strict` is the difference between reading a model's answer and
    reading an archived file -- see `load_scene_plan` and
    docs/decisions/0065. Lenient parsing falls back to a single entry for
    the first character, not for `subject`: `subject` is not reliably an
    id -- real plans have used both a bare id ("w1") and a description
    ("The influencer") there. The first character is who a beat was
    rendered with before docs/decisions/0041, so an archived pre-0049 plan
    still loads as a usable single-character beat.
    """
    raw = item.get("staging")
    if not raw:
        if strict:
            raise ScenePlanningError(
                f"A beat has no 'staging' entries (beat subject: {item.get('subject')!r}). "
                "Every character visible in the beat needs one, including the threat "
                "(docs/decisions/0049)."
            )
        if not characters:
            return []
        return [Staging(character_id=characters[0].id, action=item.get("action", ""),
                        blocking="", size_in_frame="", occlusion="")]
    if not isinstance(raw, list):
        raise ScenePlanningError(f"A beat's 'staging' must be a list, got {raw!r}")
    staging = []
    for entry in raw:
        if not isinstance(entry, dict):
            raise ScenePlanningError(
                f"Each 'staging' entry must be an object with 'character_id', 'action' and "
                f"'blocking', got {entry!r}"
            )
        # A plan saved before docs/decisions/0059 has `frame_position`
        # instead, carrying both facts in one string. Read it into
        # `blocking` rather than dropping it: --fixture and
        # --video-gen-from both replay archived runs, and the alternative
        # is a stored plan that no longer loads.
        if "blocking" not in entry:
            entry = {**entry, "blocking": entry.get("frame_position", "")}
        _require_str_fields(
            entry, ["character_id", "action", "blocking"], item_desc="A staging entry"
        )
        if strict and not entry.get("size_in_frame"):
            raise ScenePlanningError(
                f"Staging for {entry['character_id']!r} has no 'size_in_frame'. It is the "
                "field that carries depth -- world placement without it never once "
                "rendered the right depth ordering (docs/decisions/0059)."
            )
        optional = {"occlusion", "size_in_frame"}
        staging.append(
            Staging(
                **{f: entry[f] for f in Staging.__dataclass_fields__ if f not in optional},
                size_in_frame=entry.get("size_in_frame", ""),
                occlusion=entry.get("occlusion", ""),
            )
        )
    return staging


def _parse_scene_plan(raw_content: str) -> ScenePlan:
    data = parse_json_response(raw_content, ScenePlanningError, "Scene-planning response")
    return load_scene_plan(data, strict=True)


def load_scene_plan(data: object, *, strict: bool = False) -> ScenePlan:
    """Build a ScenePlan from an already-decoded plan object -- the model's
    response and a saved plan read back off disk take the same path.

    `strict=True` is for a live model response and refuses the
    backward-compatibility fallbacks: a beat with no `staging`, or a
    staging entry with no `size_in_frame`, is a planner that ignored the
    prompt, and accepting it costs a paid image and a human review of a
    beat whose prompt silently lost its STANDS:/SIZE IN FRAME: lines. The
    default stays lenient so an archived pre-0049 plan still loads, which
    is what `--fixture`, `--video-gen-from` and the eval harness need.
    See docs/decisions/0065.

    Public because the eval harness reads plans from JSON too; it built
    beats with `Beat(**beat)` and so got plain dicts where `staging`
    should have been, which fails at the first attribute access rather
    than at parse time (docs/playbook/repo-audit-brief.md, finding 4).
    """
    if not isinstance(data, dict):
        raise ScenePlanningError("Scene-planning response is not a JSON object")

    characters = []
    for item in data.get("characters", []):
        _require_str_fields(
            item,
            ["id", "face_build", "hair", "wardrobe_signature", "wardrobe_flexible", "distinguishing_detail"],
            item_desc="A character",
        )
        characters.append(Character(**{f: item[f] for f in Character.__dataclass_fields__}))
    check_unique_ids(characters, label="character")

    locations = []
    for item in data.get("locations", []):
        _require_str_fields(
            item, ["id", "architecture", "fixed_props", "ambient_light"], item_desc="A location"
        )
        locations.append(Location(**{f: item[f] for f in Location.__dataclass_fields__}))
    check_unique_ids(locations, label="location")

    beats = []
    for item in data.get("beats", []):
        _require_str_fields(
            item,
            ["location_id", "subject", "action", "camera", "lighting", "audio",
             "duration_seconds"],
            item_desc="A beat",
        )
        if strict and not item.get("intensity"):
            raise ScenePlanningError(
                f"A beat has no 'intensity' (beat subject: {item.get('subject')!r}). It is "
                "the only field carrying physical force; without it the planner writes "
                "stillness into every beat (docs/decisions/0071)."
            )
        optional_beat_fields = {"staging", "contact", "facing", "intensity"}
        beats.append(
            Beat(
                **{
                    f: item[f]
                    for f in Beat.__dataclass_fields__
                    if f not in optional_beat_fields
                },
                contact=item.get("contact", ""),
                facing=item.get("facing", ""),
                intensity=item.get("intensity", ""),
                staging=_parse_staging(item, characters, strict=strict),
            )
        )
    check_beat_location_references(beats, locations)
    check_beat_character_references(beats, characters)
    check_staging_visibility(beats)

    if not beats:
        raise ScenePlanningError("Scene-planning response has no beats")

    return ScenePlan(characters=characters, locations=locations, beats=beats)


def run_scene_planning_stage(
    scene: Scene,
    *,
    model: str | None = None,
    max_beats: int | None = None,
    genre: str | None = None,
    tone: str | None = None,
    completion_fn: Callable = litellm.completion,
    rng: random.Random | None = None,
) -> ScenePlan:
    """Build a full `ScenePlan` (characters, locations, beats) from a
    `Scene`, before any image generation happens.

    `model` defaults to the pinned "scene_planning" model. `completion_fn`
    is an injection point for tests.

    `rng`, if given, is an injection point for tests wanting a
    deterministic `_random_character_trait_hint` (pass a seeded
    `random.Random`); defaults to a fresh, unseeded one per call.

    `max_beats`, if given, is passed to the model as a soft target *and*
    enforced afterward by truncating the parsed beat list -- a cost-control
    flag (useful while iterating on image/video quality) needs a real
    guarantee, not just hope that the model honored the instruction.

    `genre`/`tone` (docs/decisions/0035), if given, are woven into the
    prompt and are meant to actually shape staging/expression/wardrobe
    choices, not just be echoed back -- see the "Genre and/or Tone"
    planning rule. `genre` now always reaches the prompt: it used to be
    shown only on an ungrounded run, because on a grounded one it was
    always the string "historical" and the preamble said so already. With
    grounding gone (docs/decisions/0069) a default run's genre is real
    information the planner was not being given.

    `genre`/`tone` also resolve `composition_mode` (docs/decisions/0036)
    -- a second early, closed-set routing signal, selecting between
    `_STAGED_COMPOSITION_RULE` and `_CHAOTIC_COMPOSITION_RULE` -- rather
    than the LLM inferring which composition instinct applies from one
    rule's inline prose hedges. Both are layered on top of
    `_BASE_COMPOSITION_RULE`, which every run gets (docs/decisions/0052).

    `genre`/`tone` also resolve a third such signal, whether
    `_THREAT_PRESENCE_RULE` applies -- keeps a horror/suspense scene's
    threat visually traceable across most beats instead of only the one
    beat that happens to mention it.

    Raises ScenePlanningError if the response isn't valid JSON, is missing
    required fields, or a beat references an undefined location.
    """
    resolved_model = model or get_stage_model("scene_planning")
    max_beats_line = (
        f"\nKeep this scene tight: produce at most {max_beats} beat(s) total, not more.\n"
        if max_beats is not None
        else ""
    )
    genre_tone_parts = []
    if genre:
        genre_tone_parts.append(f"Genre: {genre}.")
    if tone:
        genre_tone_parts.append(f"Tone: {tone}.")
    genre_tone_line = " ".join(genre_tone_parts)
    preamble = _PREAMBLE.format(
        time=scene.time,
        place=scene.place,
        description=scene.description,
        genre_tone_line=genre_tone_line,
        max_beats_line=max_beats_line,
    )
    composition_rule = (
        _BASE_COMPOSITION_RULE
        + _COMPOSITION_RULES[_resolve_composition_mode(genre, tone)]
    )
    threat_rule = _THREAT_RULES[_resolve_threat_mode(genre, tone)]
    character_variety_rule = _CHARACTER_VARIETY_RULE.format(
        character_trait_hint=_random_character_trait_hint(rng or random.Random())
    )
    prompt = preamble + _PLANNING_RULES_AND_SHAPE.format(
        complexity_budget_rule=_COMPLEXITY_BUDGET_RULE,
        composition_rule=composition_rule,
        threat_rule=threat_rule,
        character_variety_rule=character_variety_rule,
    )

    response = completion_fn(model=resolved_model, messages=[{"role": "user", "content": prompt}])
    raw_content = response.choices[0].message.content
    plan = _parse_scene_plan(raw_content)
    if max_beats is not None and len(plan.beats) > max_beats:
        plan = ScenePlan(
            characters=plan.characters, locations=plan.locations, beats=plan.beats[:max_beats]
        )
    return plan
