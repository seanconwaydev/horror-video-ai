# Historical Video AI

An AI pipeline for generating AI videos worth watching.

## Overview

The goal is videos good enough to draw real viewers — not historical education, and not historical accuracy for its own sake. See [decisions/0031](docs/decisions/0031-goal-is-quality-video-not-historical-accuracy.md) for the full reasoning.

Historical settings are what the pipeline has been built and tested against so far — research, fact-check, and structured scene planning stay genuinely useful for the parts of a scene meant to be real — but which genres are actually worth specializing in is meant to be discovered empirically across many kinds of scenes, not assumed from this project's name.

The pipeline combines:
- research grounded in real sources, for the parts of a scene meant to be real
- structured scene planning (characters, locations, beats)
- automated image/video generation with human review gates before every step that costs real money

## Goals

- Build a maintainable AI media pipeline capable of producing real audience-facing content
- Stay broadly capable across video genres rather than optimizing early for one
- Keep the parts of a scene meant to be real genuinely researched and grounded

## Status

Early development.
