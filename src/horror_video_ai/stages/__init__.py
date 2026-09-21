"""Pipeline stage implementations.

One module per stage from docs/pipeline.md, added incrementally as each
stage gets built (see CLAUDE.md for which stages currently have code):
scene_planning.py, previz.py, video_generation.py, plus moderation.py (a
pre-flight check, not a numbered stage of its own -- see
docs/decisions/0022).

research.py and fact_check.py were deleted by docs/decisions/0069: the
pipeline no longer grounds a scene in verified real-world claims.
"""
