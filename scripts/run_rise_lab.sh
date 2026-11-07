#!/usr/bin/env bash
set -euo pipefail

cd -- "$(dirname -- "$0")/.."
workspace=$(cd .. && pwd)
ros_lib="$PWD/.venv/lib/python3.11/site-packages/isaacsim/exts/isaacsim.ros2.bridge/jazzy/lib"
export LD_LIBRARY_PATH="$ros_lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export ROS_DISTRO=jazzy
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp
export ROS_LOCALHOST_ONLY=1
export MCP_CLIENT_OUTPUT_DIR="$PWD/outputs/rise/mcp"

xrandr --output HDMI-0 --primary
exec uv run --locked bricksim \
    --ext-folder "$workspace/omni-kit-mcp/exts" \
    --ext-folder "$workspace/isaac-sim-mcp/exts" \
    --enable ur5e-dt \
    --/app/window/fullscreen=false \
    --/app/window/width=1280 \
    --/app/window/height=720 \
    --/persistent/app/window/width=1280 \
    --/persistent/app/window/height=720 \
    --/app/window/maximized=false \
    --/persistent/app/window/maximized=false \
    "$@"
