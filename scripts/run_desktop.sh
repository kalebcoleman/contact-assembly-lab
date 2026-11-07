#!/usr/bin/env bash
set -euo pipefail

# Workstation workaround: the lower monitor intersects only 32 pixels of the
# X11 work area, so GLFW computes a negative window height when it is primary.
xrandr --output HDMI-0 --primary
cd -- "$(dirname -- "$0")/.."

if [[ $# -eq 0 ]]; then
    set -- demos/demo_assembly.py
fi

exec uv run --locked bricksim \
    --/app/window/fullscreen=false \
    --/app/window/width=1280 \
    --/app/window/height=720 \
    --/persistent/app/window/width=1280 \
    --/persistent/app/window/height=720 \
    --/app/window/maximized=false \
    --/persistent/app/window/maximized=false \
    "$@"
