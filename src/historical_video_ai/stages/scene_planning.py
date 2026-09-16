"""Scene-planning stage -- inserted between fact-check and previz. See
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

from historical_video_ai.config import get_stage_model
from historical_video_ai.json_utils import parse_json_response
from historical_video_ai.stages.fact_check import FactCheckResult


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
class Beat:
    """One shot: the 7-part fields (minus setting, which comes from the
    Location this beat points at) plus duration. `location_id` must match
    one of the plan's `Location.id` values."""

    location_id: str
    subject: str
    action: str
    camera: str
    lighting: str
    cinematography: str
    audio: str
    duration_seconds: str
    #: Every character visible in this beat, by id -- not just the focal
    #: one named in `subject`. Without it a beat had no way to say a second
    #: character was present, so a planned antagonist could be given its own
    #: reference image and then never appear in a single frame
    #: (docs/decisions/0041). Defaults to empty so a plan captured before
    #: this field existed still loads.
    character_ids: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ScenePlan:
    """The reviewable artifact this stage produces -- see cli.py's
    per-item review loop (characters, then locations, then beats, in that
    order, docs/decisions/0023)."""

    characters: list[Character] = field(default_factory=list)
    locations: list[Location] = field(default_factory=list)
    beats: list[Beat] = field(default_factory=list)


# docs/decisions/0034: two preambles, not one -- historical grounding
# framing ("verified claims", "must hold at this time") is actively wrong
# for a scene that was never claiming to be real in the first place. The
# shared planning rules below apply to both; only the framing and whether
# claims get woven in differs.
_GROUNDED_PREAMBLE = """\
You are a shot-list planner for a short historical video scene. Break the \
scene below into a full plan BEFORE any image gets generated: the \
character(s) involved, the distinct locations the action moves through, \
and the individual beats (shots) that tell the story.

Scene -- Time: {time} | Place: {place} | What happens: {description}
{genre_tone_line}
Verified claims about this place (use these to ground locations and \
beats in real detail; some may describe other eras and must not be \
depicted unless they hold at {time} specifically):
{claims_block}
{max_beats_line}
"""

_CREATIVE_PREAMBLE = """\
You are a shot-list planner for a short creative video scene. This scene \
is not meant to be historically or factually accurate -- do not treat \
anything in it as needing real-world grounding, and do not flag anything \
as implausible on those terms. Break the scene below into a full plan \
BEFORE any image gets generated: the character(s) involved, the distinct \
locations the action moves through, and the individual beats (shots) \
that tell the story.

Scene -- Setting: {time}, {place} | What happens: {description}
{genre_tone_line}
{max_beats_line}
"""

# docs/decisions/0036: composition_mode is an early-resolved, closed-set
# routing signal -- generalizing the requires_grounding pattern (0034/0035)
# to a second axis -- computed once from genre/tone before the rule text
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

# A third early-resolved, closed-set routing signal alongside
# requires_grounding (0034/0035) and composition_mode (0036): whether this
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
object, a shape at the edge of vision), even when the beat's main action \
is just the character moving through a space.
- If that threat is an embodied character rather than an environmental \
effect -- a person, a creature, a figure -- define it as a Character and \
LIST ITS ID in `character_ids` on every beat where any part of it is \
visible, however little. Describing it only in a beat's prose is not \
enough: a real run defined a stalking figure, generated its reference \
image, mentioned it once in a lighting field, and produced four beats with \
no antagonist in any of them. Never rely on a vague \
adjective like "barely visible" or "half-hidden" to control how prominent \
the threat is -- an image model renders that as a bold, centered \
silhouette unless given a literal constraint instead. State it \
concretely: roughly what fraction of the frame it occupies, where in the \
frame (a background corner, a frame edge, never centered), and what \
specifically occludes it (a doorframe, furniture, deep unlit shadow).
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


_PLANNING_RULES_AND_SHAPE = """\
Planning rules:
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
- Every beat must list in `character_ids` EVERY character visible in that \
shot, by id, including partially visible ones -- a figure in the \
background, a silhouette in a doorway, a hand at the frame edge. Only \
characters listed there can be drawn; a character you define but never \
list in any beat will be given a reference image and then never appear in \
a single frame. `subject` names which of them the shot is *about*; \
`character_ids` says who is actually in it.
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
- When multiple beats share a `location_id`, give them real "coverage" \
(the standard film-production term): shots from genuinely different \
camera *positions* in that space, not just a different angle adjective on \
roughly the same spot -- move the camera to a different part of the room \
or street, and vary how close it is to the subject (a wider shot, then a \
closer one, not two medium shots back to back). The same static shot \
repeated can be a legitimate deliberate choice for a specific effect, but \
must never be the unplanned default outcome of two beats sharing a \
location.
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
stepping, sitting, gesturing) unless stillness is specifically the point \
of that beat. A slightly different look for the character between beats \
(hair catching light differently, a minor pose-driven wardrobe shift) is \
fine and expected -- prioritize dynamic, believable movement over rigid \
visual sameness.
- For a character who doesn't belong to the historical setting (a \
modern-day visitor, time traveler, narrator), describe \
`wardrobe_signature`/`wardrobe_flexible` with specific, concrete, \
contemporary clothing items -- not vague terms like "casual clothes" -- \
so the result actually reads as modern, not historical.
- Any lit screen (a phone, a device) should be described as a subtle, \
realistic light source, clearly weaker than the beat's main light source \
(sun, lamp, sky) -- e.g. "a faint, dim glow on her hands, much weaker \
than the daylight around her," not open-ended "glowing"/"electric glow" \
language, which image models tend to render as an unrealistically bright, \
star-like point light.
- When a beat has a character looking at a handheld or propped screen \
from a camera angle that would naturally hide the screen from camera (an \
over-the-shoulder shot from behind her, a side view, a back view), \
explicitly state in `action` or `camera` that the screen face is NOT \
visible to camera -- we see its back or edge instead. Image models \
default to rendering a screen's face toward the viewer regardless of the \
described geometry unless told the opposite outright.
- `cinematography` is for per-beat lens and grade notes ONLY: lens choice, \
depth of field, film grain, colour grade. It must NOT describe the art \
style or realism level -- do not write "photorealistic", "cartoon", \
"anime", "illustration", "3D render", "stylized" or similar here. The \
run's art style is chosen once elsewhere and is the only thing that sets \
it; a realism claim in this field is rejected outright, not overridden.
- Keep the camera on one consistent side of the "line of action" across \
consecutive beats at the same location (the 180-degree rule) -- if a \
character is moving left-to-right or two characters face each other \
across a space, don't flip which side of that line the camera is on \
between beats without a deliberate reason, or the sense of spatial \
geography breaks for the viewer.
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
between them when contact isn't specified precisely. When two characters \
interact, give each a specific reaction to the other (a returned glance, \
a mirrored gesture) so they read as one connected moment, not two \
independently-posed figures that happen to share a frame.
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
      "character_ids": ["<every character id visible in this beat>"],
      "action": "...", "camera": "...", "lighting": "...", "cinematography": "...",
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
    `_parse_scene_plan` (the LLM's raw output) and by cli.py's
    `_review_scene_plan` (after a human edit could just as easily
    introduce a collision the LLM didn't). A silent collision would make
    `character_refs`/`location_refs` -- plain dicts keyed by id -- drop
    one item's reference image in favor of another's without any warning.
    """
    ids = [item.id for item in items]
    if len(ids) != len(set(ids)):
        dupes = sorted({i for i in ids if ids.count(i) > 1})
        raise ScenePlanningError(f"Duplicate {label} id(s): {dupes}")


# Vocabulary that describes an art style or realism level rather than a
# lens or a grade. A beat may not claim one: the run's single chosen style
# preset is the only thing allowed to set it (docs/decisions/0039).
_STYLE_CLAIM_WORDS = (
    "photorealistic",
    "photoreal",
    "photograph",
    "cartoon",
    "anime",
    "illustration",
    "illustrated",
    "3d render",
    "3d-render",
    "cgi",
    "stylized",
    "cel-shaded",
    "cel shaded",
    "painterly",
    "comic",
)


def check_cinematography_is_not_a_style_claim(beats: list) -> None:
    """Raise ScenePlanningError if any beat's `cinematography` describes an
    art style or realism level instead of lens/grade notes.

    A prompt rule already tells the planner not to do this, and the planner
    did it anyway -- a real run emitted "35mm, deep focus, fine grain, cold
    blue-black grade" into what was then called `style`, which previz
    rendered as a STYLE line competing with the run's actual chosen style.
    An instruction the model can ignore is the weakest possible guarantee,
    so this makes the claim fail to parse instead (docs/decisions/0039).

    Also re-run after human edits, like the other checks here, since a
    hand-edit can introduce exactly what the planner was stopped from
    writing (same reasoning as docs/decisions/0028).
    """
    for beat in beats:
        text = beat.cinematography.lower()
        found = sorted({w for w in _STYLE_CLAIM_WORDS if w in text})
        if found:
            raise ScenePlanningError(
                f"A beat's 'cinematography' field makes an art-style claim ({', '.join(found)}): "
                f"{beat.cinematography!r}. That field is for lens and grade notes only -- the "
                "run's style preset is the single source for art style (docs/decisions/0039)."
            )


# Phrases that describe what a character DOES rather than what they look
# like. Evidence-based and expected to be incomplete, in the same spirit as
# every other pattern list here -- each entry comes from a real plan, not a
# guess. The first four come from one run where a stalking figure's
# `distinguishing_detail` read "Stands perfectly still with both arms
# straight at its sides and its head tilted slightly to one shoulder",
# which was then emitted into every beat prompt and left the figure unable
# to do anything but stand there.
_POSE_IN_IDENTITY_PATTERNS = (
    "perfectly still",
    "arms straight at",
    "head tilted",
    "hands at his side",
    "hands at her side",
    "arms at his side",
    "arms at her side",
)

#: Sentence-initial verbs that make an identity field a behaviour
#: description. Anchored to the start so a garment term like "a standing
#: collar" or "a sitting-room" doesn't trip it.
_POSE_LEADING_VERBS = ("stands", "sits", "holds", "leans", "walks", "moves", "keeps")


def check_identity_fields_describe_appearance(characters: list) -> None:
    """Raise ScenePlanningError if a Character's identity fields describe a
    pose or behaviour instead of persistent appearance.

    `face_build`, `hair` and `distinguishing_detail` are emitted verbatim
    into every beat's prompt and are baked into the character's reference
    image, so anything in them is repeated on every single frame. A pose
    written there is not a description, it is an instruction the character
    can never escape -- docs/decisions/0042.

    Same class as docs/decisions/0029's motivating case, where a hand-edit
    put "purple hair" into `face_build` and every beat inherited it.
    """
    for character in characters:
        for field_name in ("face_build", "hair", "distinguishing_detail"):
            value = getattr(character, field_name)
            lowered = value.lower().lstrip()
            found = [p for p in _POSE_IN_IDENTITY_PATTERNS if p in lowered]
            if lowered.startswith(_POSE_LEADING_VERBS):
                found.append(lowered.split()[0])
            if found:
                raise ScenePlanningError(
                    f"Character {character.id!r}'s {field_name!r} describes a pose or "
                    f"behaviour ({', '.join(sorted(set(found)))}) rather than persistent "
                    f"appearance: {value!r}. That field is repeated in every beat's prompt "
                    "and baked into the reference image, so a pose there is an instruction "
                    "the character can never escape -- put it in a beat's action instead."
                )


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
        if not beat.character_ids:
            raise ScenePlanningError(
                f"A beat at {beat.location_id!r} lists no character_ids -- every beat must "
                "name every character visible in it, even if that is just one."
            )
        unknown = [cid for cid in beat.character_ids if cid not in known]
        if unknown:
            raise ScenePlanningError(
                f"A beat references character id(s) {unknown}, which don't match any defined "
                f"character ({sorted(known)})."
            )



def check_beat_location_references(beats: list, locations: list) -> None:
    """Raise ScenePlanningError if any beat's location_id doesn't match a
    defined location -- reused by `_parse_scene_plan` (the LLM's raw
    output) and by cli.py's `_review_scene_plan` (after a human edit to
    either a beat's location_id or a location's id could just as easily
    break the reference the LLM originally got right)."""
    location_ids = {loc.id for loc in locations}
    for beat in beats:
        if beat.location_id not in location_ids:
            raise ScenePlanningError(
                f"A beat references location_id {beat.location_id!r}, which doesn't match "
                f"any defined location ({sorted(location_ids)})"
            )


def _truncate_references_safely(plan: ScenePlan, max_references: int) -> ScenePlan:
    """Drop characters/locations to fit `max_references` total, but only
    ones it's provably safe to drop -- never orphans a beat. Best-effort,
    not a hard guarantee like `max_beats`'s truncation: if every remaining
    reference is actually in use, this stops short of the target rather
    than silently breaking a beat's location_id (the same class of bug
    docs/decisions/0027/0028 fixed elsewhere).

    Safe to drop, in order: every character past the first (cli.py's
    `_generate_beats_with_choices` only ever conditions on
    `characters[0]` -- a documented v1 simplification, Beat has no
    character_id -- so the rest are already unused by construction), then
    any location no beat's `location_id` actually references.
    """
    characters = list(plan.characters)
    locations = list(plan.locations)

    while len(characters) + len(locations) > max_references and len(characters) > 1:
        characters.pop()

    used_location_ids = {b.location_id for b in plan.beats}
    i = len(locations) - 1
    while len(characters) + len(locations) > max_references and i >= 0:
        if locations[i].id not in used_location_ids:
            locations.pop(i)
        i -= 1

    if len(characters) + len(locations) == len(plan.characters) + len(plan.locations):
        return plan  # nothing was safe to drop
    return ScenePlan(characters=characters, locations=locations, beats=plan.beats)


def _parse_scene_plan(raw_content: str) -> ScenePlan:
    data = parse_json_response(raw_content, ScenePlanningError, "Scene-planning response")

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
            ["location_id", "subject", "action", "camera", "lighting", "cinematography", "audio",
             "duration_seconds"],
            item_desc="A beat",
        )
        # Falls back to the first character, not to `subject`: `subject` is
        # not reliably an id -- real plans have used both a bare id ("w1")
        # and a description ("The influencer") in that field. The first
        # character is exactly who a beat was rendered with before
        # docs/decisions/0041, so this reproduces the old behaviour.
        character_ids = item.get("character_ids") or (
            [characters[0].id] if characters else []
        )
        if not isinstance(character_ids, list) or not all(
            isinstance(cid, str) and cid for cid in character_ids
        ):
            raise ScenePlanningError(
                f"A beat's 'character_ids' must be a list of non-empty id strings, got "
                f"{item.get('character_ids')!r}"
            )
        # Falling back to [subject] rather than failing: a planning model
        # that ignores the new field still produces a usable single-character
        # beat, which is what every beat was before docs/decisions/0041.
        beats.append(
            Beat(
                **{f: item[f] for f in Beat.__dataclass_fields__ if f != "character_ids"},
                character_ids=character_ids,
            )
        )
    check_beat_location_references(beats, locations)
    check_cinematography_is_not_a_style_claim(beats)
    check_beat_character_references(beats, characters)
    check_identity_fields_describe_appearance(characters)

    if not beats:
        raise ScenePlanningError("Scene-planning response has no beats")

    return ScenePlan(characters=characters, locations=locations, beats=beats)


def run_scene_planning_stage(
    fact_check_result: FactCheckResult,
    *,
    model: str | None = None,
    max_beats: int | None = None,
    max_references: int | None = None,
    requires_grounding: bool = True,
    genre: str | None = None,
    tone: str | None = None,
    completion_fn: Callable = litellm.completion,
    rng: random.Random | None = None,
) -> ScenePlan:
    """Build a full `ScenePlan` (characters, locations, beats) from a
    verified fact sheet, before any image generation happens.

    `model` defaults to the pinned "scene_planning" model. `completion_fn`
    is an injection point for tests.

    `rng`, if given, is an injection point for tests wanting a
    deterministic `_random_character_trait_hint` (pass a seeded
    `random.Random`); defaults to a fresh, unseeded one per call.

    `max_beats`, if given, is passed to the model as a soft target *and*
    enforced afterward by truncating the parsed beat list -- a cost-control
    flag (useful while iterating on image/video quality) needs a real
    guarantee, not just hope that the model honored the instruction.

    `max_references` (characters + locations combined -- these, not
    beats, are what a scene can't generate a single image without) gets
    the same soft-target prompt treatment, but its enforcement is
    best-effort, not guaranteed -- see `_truncate_references_safely`.

    `requires_grounding` (docs/decisions/0034) selects which preamble is
    used -- historical-accuracy framing is actively wrong for a scene that
    was never claiming to be real (a meme/creative premise), not just
    unnecessary overhead. When False, `fact_sheet.claims` is ignored (a
    stub FactCheckResult for an ungrounded run has none anyway).

    `genre`/`tone` (docs/decisions/0035), if given, are woven into the
    prompt and are meant to actually shape staging/expression/wardrobe
    choices, not just be echoed back -- see the "Genre and/or Tone" \
    planning rule. `genre` is only shown when `requires_grounding` is
    False (it's always "historical" otherwise, redundant with the
    preamble's own framing).

    `genre`/`tone` also resolve `composition_mode` (docs/decisions/0036)
    -- a second early, closed-set routing signal, selecting between
    `_STAGED_COMPOSITION_RULE` and `_CHAOTIC_COMPOSITION_RULE` -- rather
    than the LLM inferring which composition instinct applies from one
    rule's inline prose hedges.

    `genre`/`tone` also resolve a third such signal, whether
    `_THREAT_PRESENCE_RULE` applies -- keeps a horror/suspense scene's
    threat visually traceable across most beats instead of only the one
    beat that happens to mention it.

    Raises ScenePlanningError if the response isn't valid JSON, is missing
    required fields, or a beat references an undefined location.
    """
    resolved_model = model or get_stage_model("scene_planning")
    fact_sheet = fact_check_result.fact_sheet
    max_beats_line = (
        f"\nKeep this scene tight: produce at most {max_beats} beat(s) total, not more.\n"
        if max_beats is not None
        else ""
    )
    if max_references is not None:
        max_beats_line += (
            f"\nAlso keep the cast and setting minimal: at most {max_references} "
            "character(s) and location(s) combined -- prefer one character and "
            "one location unless the scene genuinely needs more.\n"
        )
    genre_tone_parts = []
    if not requires_grounding and genre:
        genre_tone_parts.append(f"Genre: {genre}.")
    if tone:
        genre_tone_parts.append(f"Tone: {tone}.")
    genre_tone_line = " ".join(genre_tone_parts)
    if requires_grounding:
        claims_block = "\n".join(f"- {c.text}" for c in fact_sheet.claims) or "(no claims)"
        preamble = _GROUNDED_PREAMBLE.format(
            time=fact_sheet.time,
            place=fact_sheet.place,
            description=fact_sheet.description,
            claims_block=claims_block,
            max_beats_line=max_beats_line,
            genre_tone_line=genre_tone_line,
        )
    else:
        preamble = _CREATIVE_PREAMBLE.format(
            time=fact_sheet.time,
            place=fact_sheet.place,
            description=fact_sheet.description,
            genre_tone_line=genre_tone_line,
            max_beats_line=max_beats_line,
        )
    composition_rule = _COMPOSITION_RULES[_resolve_composition_mode(genre, tone)]
    threat_rule = _THREAT_RULES[_resolve_threat_mode(genre, tone)]
    character_variety_rule = _CHARACTER_VARIETY_RULE.format(
        character_trait_hint=_random_character_trait_hint(rng or random.Random())
    )
    prompt = preamble + _PLANNING_RULES_AND_SHAPE.format(
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
    if max_references is not None and len(plan.characters) + len(plan.locations) > max_references:
        plan = _truncate_references_safely(plan, max_references)
    return plan
