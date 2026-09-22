"""Scene-plan artifacts shared by the cli test modules.

Kept out of any one test file because the split of test_cli.py leaves
several modules building the same Character, Location and Beat -- the
review widgets, the beat loop, and scene-plan validation all need one.
Deliberately boring and fully specified: a test that wants a particular
field different should say so at the call site.
"""

from horror_video_ai.stages.scene_planning import Beat, Character, Location

#: A 1x1 PNG. Anything that only needs *a* real image file on disk uses
#: this; the mock pipeline's own stand-in is 9:16 and lives in cli/mocks.py.
TINY_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
    "+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


def a_character() -> Character:
    return Character(
        id="influencer",
        face_build="young woman, mid-20s",
        hair="light brown wavy",
        wardrobe_signature="white crop top, gray leggings",
        wardrobe_flexible="accessories may vary",
        distinguishing_detail="a glowing phone",
    )


def a_location() -> Location:
    return Location(
        id="street",
        architecture="stone-paved Pompeii street",
        fixed_props="an archway entrance",
        ambient_light="bright midday sun",
    )


def a_beat(location_id="street", action="checks her phone") -> Beat:
    return Beat(
        location_id=location_id,
        subject="The influencer",
        action=action,
        camera="medium shot",
        lighting="bright midday sun",
        audio="street ambience",
        duration_seconds="3",
    )
