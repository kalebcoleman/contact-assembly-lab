#!/usr/bin/env bash
set -euo pipefail

cd -- "$(dirname -- "$0")/.."
workspace=$(cd .. && pwd)
export OMNI_KIT_MCP_HOST=127.0.0.1
export OMNI_KIT_MCP_PORT=8766
export MCP_CLIENT_OUTPUT_DIR="$PWD/outputs/rise/mcp"
exec "$workspace/isaac-sim-mcp/.venv/bin/isaac-mcp"
