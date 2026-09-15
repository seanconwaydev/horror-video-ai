#!/usr/bin/env bash
# Quick standalone stitcher -- joins generated video clips into one file with
# ffmpeg's concat demuxer. NOT part of the pipeline/CLI (stage 11 "Assembly"
# in docs/pipeline.md is still unbuilt); this is a throwaway helper for
# manually assembling a few clips picked by hand, not a general solution
# (no transitions, no audio mixing, assumes all inputs share codec/resolution
# since it uses stream copy).
#
# Usage: scripts/stitch_clips.sh OUTPUT.mp4 CLIP1.mp4 CLIP2.mp4 [CLIP3.mp4 ...]

set -euo pipefail

if [ "$#" -lt 3 ]; then
    echo "Usage: $0 OUTPUT.mp4 CLIP1.mp4 CLIP2.mp4 [CLIP3.mp4 ...]" >&2
    exit 1
fi

output="$1"
shift

list_file="$(mktemp)"
trap 'rm -f "$list_file"' EXIT

for clip in "$@"; do
    if [ ! -f "$clip" ]; then
        echo "Clip not found: $clip" >&2
        exit 1
    fi
    printf "file '%s'\n" "$(cd "$(dirname "$clip")" && pwd)/$(basename "$clip")" >> "$list_file"
done

ffmpeg -y -f concat -safe 0 -i "$list_file" -c copy "$output"
echo "Stitched $# clip(s) -> $output"
