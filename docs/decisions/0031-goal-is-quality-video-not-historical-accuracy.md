# 31. The goal is videos worth watching, not historical accuracy for its own sake

Date: 2026-09-02

Status: Accepted

## Context

This project's docs (`CLAUDE.md`'s "What this is," `docs/architecture.md`'s "Vision," `README.md`) all describe the pipeline as centrally about turning a *historical* topic into a video, with fact-check and a premise-conflict refusal mechanism (ADR 0008) built to prevent depicting anything that couldn't have existed or happened. That framing was accurate to how the project started, but not to its actual current goal.

The real goal, stated explicitly by the project owner earlier in this project's life: producing AI-generated videos good enough to draw real viewers -- not historical education, and not historical accuracy as an end in itself. Historical settings are simply what's been built and tested against so far (the research/fact-check stages happen to be useful there); which genres are actually worth specializing in is meant to be discovered empirically from real results across many kinds of scenes, not decided upfront by the pipeline's own name or its existing machinery. A scene can deliberately mix a real historical setting with openly fantastical elements (ADR 0025's "keep as intentional fiction"), and the pipeline needs to eventually handle *any* video genre well, not just historical ones.

This was already a real decision -- acted on repeatedly in this project's actual code (ADR 0025, ADR 0026, ADR 0030 all exist because of it) -- but never written down as its own ADR, only ever stated in conversation. That gap had a real, concrete cost: without a discoverable canonical record, later work re-centered "historical accuracy" as the project's defining scope by simple accident of the docs' own wording (an assistant researching a genre-taxonomy question referred to historical-accuracy anachronism detection as "this project's actual niche" -- language the project's own CLAUDE.md and architecture.md invited, since both still described the pipeline as fundamentally about historical topics).

## Decision

The goal is: AI-generated videos worth watching, across whatever genres turn out to perform well, discovered empirically rather than assumed. Historical accuracy is a real, still-valued concern *when the scene calls for it* -- research and fact-check stay genuinely grounded for the parts of a scene meant to be real -- but it is not the project's defining scope, and mechanisms built around strict historical-accuracy gating should be weighed against this actual goal, not treated as an inviolable constraint.

`CLAUDE.md`'s "What this is," `docs/architecture.md`'s "Vision," and `README.md` are corrected to state this directly, rather than leaving it recoverable only from conversation history or scattered ADRs.

Explicitly not decided by this ADR: the project's name, repository, Python package name (`historical_video_ai`), or CLI command (`historical-video-ai`) are unchanged. A rename was considered and deliberately deferred -- premature to rename toward some other specific label before real evidence identifies what the pipeline should actually specialize in; renaming later, once evidence exists, is far cheaper than reversing a rename made from a discussion rather than data.

## Consequences

Future design decisions should be weighed against "does this help produce videos worth watching," not "does this preserve historical accuracy," unless the scene in question specifically calls for the latter. Any future session or contributor asking "what is this project's actual scope" should find this ADR before re-deriving (or mis-deriving) an answer from the pipeline's name or its historical-genre-heavy implementation history.
