# UR5e simulation test cases

A small, reproducible simulation-only suite built on the
[baseplate experiment](ur5e-baseplate.md). It never connects to a robot. Each
case is one JSON file in `experiments/ur5e_lego/configs/cases/`, with its
prediction written before it runs, and runs once in a fresh Isaac Sim process.

## Run

From the repository root, with the environment from the
[experiment README](../README.md):

    .venv/bin/python experiments/ur5e_lego/scripts/run_ur5e_cases.py
    .venv/bin/python experiments/ur5e_lego/scripts/run_ur5e_cases.py --case C01 C05

`--publish` also copies results to `docs/evidence/`. Set `ISAAC_MCP_COMMIT` to
record the resolver version. Results are written under
`outputs/ur5e_lego/cases/<suite id>/`. The command exits 1 if any outcome differs
from its prediction. Review results in the
[dashboard](../../ur5e_dashboard/README.md) under **Test cases**.

The published suite used a read-only export of the resolver, since edits to a live
checkout can reload extensions inside a running simulator:

    mkdir -p outputs/ur5e_lego/isaac-mcp-af85e6b
    git -C ~/Desktop/isaac-mcp archive af85e6b exts config scripts mcp \
      | tar -x -C outputs/ur5e_lego/isaac-mcp-af85e6b
    export ISAAC_MCP_ROOT="$PWD/outputs/ur5e_lego/isaac-mcp-af85e6b"
    export ISAAC_MCP_ASSET_PATH="$HOME/Desktop/isaac-mcp-assets"
    export ISAAC_MCP_ASSET_STRICT=1
    export ISAAC_MCP_COMMIT=af85e6b6
    .venv/bin/python experiments/ur5e_lego/scripts/run_ur5e_cases.py --publish

Cases ran with no launcher arguments, MCP bridge or ROS bridge. `ISAAC_MCP_COMMIT` is a
label you supply; the driver does not check it. C01 to C12 ran at `5f7f411`, C13 at
`754f904`. Later commits changed only post-run behavior and viewers. The manifest's
`run_notes` lists edits made after the runs.

To run one case by hand, for recording or inspection:

    ./experiments/ur5e_lego/scripts/run_ur5e_case.sh \
      experiments/ur5e_lego/configs/cases/C05.json --manual

On Isaac Sim 6.2.0.0 (2026-11-07, suite `20261107T191150Z`, not published to
`docs/evidence/`) all 13 cases gave the same observed outcome as the published 5.1
suite: 12 as predicted, and C10 connected although `rejected` was predicted, as on
5.1. The command therefore exits 1 on both versions.

## Inputs

All are optional and zero or unset by default. Positions are meters in the
simulator world frame; angles are radians.

| Field | Meaning |
|---|---|
| `placement_error_xy_m` | World XY error added to the commanded placement |
| `placement_error_yaw_rad` | Yaw about the target brick center added to the placement |
| `grasp_error_xy_m` | World XY error added to the commanded grasp |
| `source_yaw_rad` | Rotation of each loose brick about world Z at the start |
| `ground_truth_xy_correction` | `false` disables the held brick's XY correction |
| `held_brick_pose_assumed_from_grasp` | `true` plans placement without the grasp error |

Placement errors are applied after the ground-truth correction, so without
disabling it they measure a known offset rather than an estimate of real error.

## Outcomes

`connected` means the script's checks passed after release and settling.
`rejected` means the press timed out with no connection. `wrong_stud` means a
connection formed at a stud other than the target and the script flagged it.
`target_not_reached` means the arm did not settle at a commanded pose within the
timeout. The manifest `ur5e-cases-suite.json` in `docs/evidence/` holds the
commit, environment, asset hashes, inputs, outcomes and measurements.

## ROS 2 check

`scripts/verify_ros_graph.py` samples `/clock`, `/joint_states`,
`/rg2/joint_states` and `/tf` from a separate process. ROS graphs are not part of
the cases; see the [meeting brief](ur5e-meeting-brief.md) for what was verified.
