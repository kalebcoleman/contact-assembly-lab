#!/usr/bin/env bash
set -euo pipefail

cd -- "$(dirname -- "$0")/../../.."
export PYTHONPATH="$PWD/python${PYTHONPATH:+:$PYTHONPATH}"
exec "$PWD/.venv/bin/python" -m bricksim "$@" experiments/ur5e_lego/rise_ur5e_baseplate.py
