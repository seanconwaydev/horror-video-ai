> ⚠️ Superseded — kept for reference only, not current. See [docs/pipeline.md](../pipeline.md) for the current stage-by-stage design.

---

Define the lifecycle of a video:

Topic

↓

Historical Research Artifact

Input:

Historical topic

Output:

Structured research document

Purpose:

Gather reliable historical information that later stages can use.

↓

Narrative Artifact

Input:

Research document

Output:

Narration/script

Purpose:

Turn research into an engaging story.

↓

Scene Artifact

Input:

Research
Script

Output:

Scene descriptions

Purpose:

Decide what the viewer experiences throughout the video.

↓

Music Artifact
TODO: ADD INPUT/OUTPUT/PURPOSE

↓

Voice Artifact
TODO: ADD INPUT/OUTPUT/PURPOSE

↓

Picture Artifact

PICTURE TO BUILD VIDEO FROM
TODO: ADD INPUT/OUTPUT/PURPOSE

↓

Video Project Artifact

Input:

Script
Scenes

Output:

Complete project definition

Purpose:

Create a fully validated artifact before any expensive media generation begins.

↓

Generated Media (LIKELY WILL INCUR COSTS)

↓

Published Content

Video generation is intentionally separated from planning and generation steps. The system should produce a complete validated video project artifact before expensive media generation begins.


# Pipeline Principles
- Each stage consumes structured input and produces structured output.
- Later stages should not repeat work performed earlier.
- Expensive media generation should occur only after all planning stages have completed successfully.
- Every stage should be independently testable.
- Intermediate artifacts should be saved so the pipeline can be resumed or debugged.


# TODOS
- PICTURE STEP, IT'LL BE ALONGSIDE THE FINAL SCRIPT, IMPORTANT FOR GROUNDING THE VIDEO GENERATION WITH A PARTICULAR VISION/PERSPECTIVE
- AGENTS TO ADD: VOICE AND MUSIC