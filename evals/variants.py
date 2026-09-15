"""Prompt-construction variants under test.

Each variant takes a scene's body and its committed style from
scenes.yaml, and returns the full prompt an image model would receive.
Only the style block differs -- that is the variable being measured, and
holding everything else identical is what makes the comparison mean
anything.

`current` reproduces what the real pipeline sends today, contradiction
included: a photographic per-beat STYLE line followed by an override
declaring the opposite. The override text is imported from previz rather
than copied, so this variant can't silently drift from what the pipeline
actually does.

`single_source` uses the scene's own committed style, stated once.

Deliberately NOT one house style. Each scene in scenes.yaml carries a
different committed style -- comic panel, 16mm photography, painterly,
graphic poster, cel-shaded -- because the goal is stylistic range across
outputs, not every short looking like a comic book. What is being tested
is whether committing to ONE look per run beats hedging across many
inside a single instruction, which is what the current `stylized` text
does.

Noted honestly: giving each scene a different committed style varies two
things at once (commitment, and which style). That is the right trade
here -- a single shared committed style would test commitment more
cleanly while smuggling in exactly the house-style lock-in this project
is trying to avoid. If the hedged variant reads as mush across all five
while the committed one reads as decisive across all five, the finding is
about commitment regardless of which styles were drawn.
"""

from __future__ import annotations

from historical_video_ai.stages.previz import _STYLE_INSTRUCTIONS

# Representative of what the scene-planning model really emits into a
# beat's `style` field -- lifted from a real run's stored prompt
# (outputs/run_20260915-202830.../run_log.json). Photographic, despite a
# planning rule telling it not to make realism claims in that field.
_TYPICAL_BEAT_STYLE = (
    "35mm, deep focus, fine grain, cold blue-black grade with warm lamp "
    "highlights, no on-screen text/UI/logos"
)

_NO_TEXT = "No on-screen text, no logos, no watermark."


def current(body: str, style: str) -> str:
    """What the pipeline sends today: two competing style claims, resolved
    by an appended instruction declaring which one wins. The scene's own
    committed style is deliberately unused -- today's pipeline has no way
    to express one."""
    del style
    return (
        f"{body}\n"
        f"STYLE: {_TYPICAL_BEAT_STYLE}\n"
        "OVERRIDING STYLE REQUIREMENT (takes priority over anything above): "
        f"{_STYLE_INSTRUCTIONS['stylized']}"
    )


def single_source(body: str, style: str) -> str:
    """One style instruction, stated once, committed. Nothing to override
    because nothing competes -- docs/decisions/0033's actual intent."""
    return f"{body}\nSTYLE: {style} {_NO_TEXT}"


VARIANTS = {
    "current": current,
    "single_source": single_source,
}
