#!/usr/bin/env bash
set -euo pipefail

# Usage: run_ur5e_case.sh <case config> [--manual] [-- launcher args...]
cd -- "$(dirname -- "$0")/../../.."
export PYTHONPATH="$PWD/python${PYTHONPATH:+:$PYTHONPATH}"
config=$1
shift
script_args=()
while (($#)) && [[ $1 != -- ]]; do
    script_args+=("$1")
    shift
done
(($#)) && shift
exec "$PWD/.venv/bin/python" -m bricksim "$@" experiments/ur5e_lego/rise_ur5e_case.py \
    "$config" "${script_args[@]}"
