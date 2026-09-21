# Historical Video AI

An AI pipeline for generating AI videos worth watching.

## Overview

The goal is videos good enough to draw real viewers — not historical education, and not accuracy for its own sake. See [decisions/0031](docs/decisions/0031-goal-is-quality-video-not-historical-accuracy.md) for the full reasoning.

The name is historical for historical reasons. The pipeline began by grounding every scene in researched, fact-checked real-world claims; [decisions/0069](docs/decisions/0069-delete-historical-grounding.md) deleted all of it, because a horror short set in a car park was paying for sourced claims it could not use. Nothing is verified against the real world now, and impossible things are welcome. The current genre is horror ([decisions/0037](docs/decisions/0037-horror-motion-comic-shorts-wan-via-replicate.md)), and which genres are worth specializing in is meant to be discovered empirically rather than assumed from the name.

The pipeline combines:
- structured scene planning: a scene becomes characters, locations, and beats
- automated image/video generation, one image per beat
- human review gates before every step that costs real money

## Goals

- Build a maintainable AI media pipeline capable of producing real audience-facing content
- Stay broadly capable across video genres rather than optimizing early for one

## Status

Early development.
