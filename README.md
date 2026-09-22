# Horror Video AI

An AI pipeline for generating short horror videos worth watching.

## Overview

The goal is videos good enough to draw real viewers — not historical education, and not accuracy for its own sake. See [decisions/0031](docs/decisions/0031-goal-is-quality-video-not-historical-accuracy.md) for the full reasoning.

This started as a historical-video pipeline, and grounded every scene in researched, fact-checked real-world claims. [decisions/0069](docs/decisions/0069-delete-historical-grounding.md) deleted all of it — a horror short set in a car park was paying for sourced claims it could not use — and [decisions/0070](docs/decisions/0070-rename-to-horror-video-ai.md) renamed the project to match what it actually makes. Nothing is verified against the real world now, and impossible things are welcome.

Horror is the committed genre ([decisions/0037](docs/decisions/0037-horror-motion-comic-shorts-wan-via-replicate.md)), in a motion-comic style, as vertical Shorts ([decisions/0002](docs/decisions/0002-shorts-first-format.md)).

The pipeline combines:
- structured scene planning: a scene becomes characters, locations, and beats
- automated image/video generation, one image per beat
- human review gates before every step that costs real money

## Goals

- Build a maintainable AI media pipeline capable of producing real audience-facing content
- Stay broadly capable across video genres rather than optimizing early for one

## Status

Early development.
