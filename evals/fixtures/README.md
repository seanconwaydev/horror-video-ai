# Eval fixtures

Committed, unlike `evals/results/`, which is gitignored because it holds
generated images.

`still_9x16.png` exists so `motion_test.py` has something to point at in
CI. That script takes still images and animates them, and with no
arguments it globs `evals/results/` -- so in a clean checkout it found
nothing and failed, which is why it was the one eval script with no smoke
coverage at all (see `.github/workflows/ci.yml`). A `--dry-run` never
opens the file, but pointing at a real 9:16 still keeps the smoke
invocation honest rather than passing a path that happens to exist.

Deliberately tiny and flat: nothing here is meant to be animated for
real, and a fixture nobody is tempted to spend money on is the point.
