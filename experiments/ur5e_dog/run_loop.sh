#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "$0")/../.."
exec ../.venv/bin/python experiments/ur5e_dog/loop.py "$@"
