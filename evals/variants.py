"""Prompt-construction variants under test.

Each variant takes a scene body from scenes.yaml and returns the full
prompt an image model would receive. Only the style block differs -- that
is the variable being measured, and holding everything else identical is
what makes the comparison mean anything.

`current` reproduces what the real pipeline sends today, including the
contradiction: a photographic per-beat STYLE line followed by an override
declaring the opposite. The override text is imported from previz itself
rather than copied, so this variant can't silently drift away from what
the pipeline actually does.
"""

from __future__ import annotations

from historical_video_ai.stages.previz import _STYLE_INSTRUCTIONS

# Representative of what the scene-planning model really emits into a
# beat's `style` field -- lifted from a real run's stored prompt
# (outputs/run_20260915-202830.../run_log.json). Photographic, despite a
# planning rule telling it not to make realism claims here.
_TYPICAL_BEAT_STYLE = (
    "35mm, deep focus, fine grain, cold blue-black grade with warm lamp "
    "highlights, no on-screen text/UI/logos"
)

# One committed direction, stated once. Deliberately the same shape as the
# `photorealistic` instruction that the failure taxonomy's one
# "verified fixed" run used -- a short, decisive description plus hard
# negatives -- rather than the hedged `stylized` text.
_COMMITTED_HORROR_COMIC = (
    "Stylized horror comic panel -- heavy inked black shadows, bold "
    "confident linework, a restrained desaturated palette with one colour "
    "allowed to dominate, high contrast between lit and unlit areas. "
    "Explicitly NOT photorealistic, NOT 3D-rendered, NOT cute, NOT "
    "wholesome, NOT a soft or rounded children's cartoon. No on-screen "
    "text, no logos, no watermark."
)


def current(body: str) -> str:
    """What the pipeline sends today: two competing style claims, resolved
    by an appended instruction declaring which one wins."""
    return (
        f"{body}\n"
        f"STYLE: {_TYPICAL_BEAT_STYLE}\n"
        "OVERRIDING STYLE REQUIREMENT (takes priority over anything above): "
        f"{_STYLE_INSTRUCTIONS['stylized']}"
    )


def single_source(body: str) -> str:
    """One style instruction, stated once, committed. Nothing to override
    because nothing competes -- docs/decisions/0033's actual intent."""
    return f"{body}\nSTYLE: {_COMMITTED_HORROR_COMIC}"


VARIANTS = {
    "current": current,
    "single_source": single_source,
}
