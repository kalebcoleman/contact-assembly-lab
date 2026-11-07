# UR5e brick experiments

This folder contains the RISE lab UR5e brick work: the scripts, workstation
scene, settings, launchers, experiment notes, and recorded evidence. The
existing project demos and other experiments remain outside this folder.

[Review recorded experiments](../ur5e_dashboard/README.md) in a local results
dashboard.

## Same setup on every machine

`main` on the `fork` remote is the shared version. On each machine, from the
repository root:

    git pull --ff-only
    ./scripts/download_prebuilt_native.sh
    uv sync --locked
    .venv/bin/python scripts/check_parity.py

`check_parity.py` exits 1 and names the difference if the checkout is dirty or
not at its upstream, an installed package differs from `uv.lock`, the native
extension differs from its prebuilt manifest, or a lab asset differs from the
hashes in `assets/lab_assets_sha256.json`. OS, GPU, driver and Python are only
reported. After an intentional asset change, run it with `--record` and commit
the hash file.

The lab robot (with its `tool0` frame) and the Vention bench are not in Git.
The experiments load the asset resolver from the `isaac-mcp` code checkout at
`~/Desktop/isaac-mcp` (`ISAAC_MCP_ROOT` overrides it). The resolver reads the
separate asset store `~/Desktop/isaac-mcp-assets`, which is not a Git checkout;
`ISAAC_MCP_ASSET_PATH` overrides it. The robot is `ur5e-dt/robot/ur5e.usd` and
the bench is `ur5e-dt/workstation/vention.usd` inside the store. Set
`ISAAC_MCP_ASSET_STRICT=1` to refuse remote fallback.

From the repository root, choose an experiment:

- [Pick up and transfer one brick](docs/ur5e-lego.md):
  `./experiments/ur5e_lego/scripts/run_ur5e_lego.sh`
- [Place three bricks on the baseplate](docs/ur5e-baseplate.md):
  `./experiments/ur5e_lego/scripts/run_ur5e_baseplate.sh`
- [Stack three bricks](docs/ur5e-stack.md):
  `./experiments/ur5e_lego/scripts/run_ur5e_stack.sh`
- [Stack four bricks](docs/ur5e-stack-four.md):
  `./experiments/ur5e_lego/scripts/run_ur5e_stack_four.sh`
- [Simulation test cases](docs/ur5e-cases.md):
  `.venv/bin/python experiments/ur5e_lego/scripts/run_ur5e_cases.py`

See also the [meeting brief](docs/ur5e-meeting-brief.md) and the
[isaac-mcp 5.1 tool report](docs/isaac-mcp-5.1-tool-report.md).

The guides describe the Isaac Sim 5.1 and lab asset requirements, controls,
results, and limitations. `configs/` contains the scene and placement settings,
`assets/` contains the workstation layout, and `docs/evidence/` contains the
versioned results. Earlier local recordings remain under the ignored
`outputs/rise/` directory.

All four scenes load Isaac Sim's Simple Room through the configured Isaac asset
root. The room is a visual backdrop: its table is removed and its colliders and
rigid bodies are disabled. The existing tabletop collider supports the bricks.
The room asset must be accessible from the configured asset root; the scripts
fail if it cannot be loaded. The settings panel is selected when each scene
starts. [Stage inspection](docs/evidence/ur5e-room-stage.json).

Each run writes a time-stamped JSON Lines file under `outputs/ur5e_lego/` and
prints its path. Its metadata records the experiment settings, joint names,
units and frames. Physics-step samples contain the phase, robot joint commands
and simulated joint positions, velocities and efforts, gripper state, tool
targets and measured poses, brick poses, placement errors, active assembly and
breakage settings, and simulated contact and connection details.
The final record reports completion, Stop, or interruption/failure; the console
contains any exception details. An abrupt process exit can leave a log without
a final record.

Positions are in meters, angles in radians, and quaternions use wxyz order.
Tool and part poses are in the simulator world frame; placement errors are in
the support part frame. Samples carry simulation elapsed time and host UTC and
monotonic timestamps. Samples are taken before the physics step ending at
`simulation_elapsed_s`, so subtract `physics_dt_s` for the sample time.
Contact data is the latest available, and USD poses may update at the rendering rate. Host
clocks are not automatically synchronized with hardware. The scalar gripper
target is for `rg2_gripper_joint`. Simulated
object poses, contacts, connections, and efforts are ground-truth or solver
outputs, not physical sensor readings. Compare only fields available from the
lab setup after calibrating frames and clocks.

One related change is outside this folder: the shared
[`physics_step.py`](../../python/bricksim/utils/physics_step.py) utility checks
whether a physics callback still exists before removing it after an
interruption. Other project code uses this utility too. The separate untracked
two-arm research is not part of these brick experiments.
