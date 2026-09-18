# Fixtures

Captured *real* research + fact-check output, saved here so later
development (previz, and stages 4+ once built) can iterate against real
historical claims without paying for a Perplexity/Gemini call every time.

## Why this exists

The `research` and `fact_check` stages are the two paid, network-dependent
stages upstream of everything else in the pipeline. `--mock`
(`src/historical_video_ai/cli/`) avoids that cost too, but with synthetic
placeholder text ("[MOCK] A placeholder claim...") that isn't useful for
judging how a real fact sheet reads once it reaches previz's prompt-building
or a future narrative/shot-list stage. A fixture is the middle ground: real
model output, captured once, replayed for free after that.

## How to add one

1. Run the real pipeline for a scene you like: `uv run historical-video-ai
   --time "..." --place "..." --description "..."` (needs real API keys --
   see `.env.example`).
2. Look at the run's `outputs/run_<timestamp>/run_log.json`. If the research
   and fact-check output are good, copy that file here, e.g.
   `tests/fixtures/apollo-11-launch.json`.
3. Reuse it with `uv run historical-video-ai --fixture
   tests/fixtures/apollo-11-launch.json` -- no research/fact-check API calls
   happen; previz still runs for real unless `--mock` is also passed.

No fixtures are committed yet -- none of the three v1 model integrations
have been exercised against a live key from this repo (see
`docs/decisions/0007-research-fact-check-previz-models.md`), so there's
nothing real to capture until that first live run happens.
