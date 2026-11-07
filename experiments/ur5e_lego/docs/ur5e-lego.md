# UR5e brick transfer

This separate simulation places three 2×4 bricks on the Vention workstation.
The lab UR5e stays fixed on the workstation rail and uses the RG2 gripper to
attempt one pick, transfer, and release. The robot, gripper, rail, and
workstation come from the `isaac-mcp` assets; their files are not modified.

The experiment requires Isaac Sim 5.1 and an `isaac-mcp` checkout of `main` at
PR #16 or later, which provides `exts/ur5e-dt/ur5e_dt/asset_cache.py`. The tested workstation layout is versioned here in
`experiments/ur5e_lego/assets/ur5e_workstation.usda`. It preserves the tested world and
physics settings but omits the unused ROS graphs. An ignored checkpoint or its
manifest is no longer required. The versioned scene's SHA-256 at validation was
`fcdb197ba399b0acd065d62119ab2529befdd082fd6c46dd934d9f0ab2c0a830`.
It was derived from the tested local checkpoint whose SHA-256 was
`b2b999038cf26a8cc9d55980f5b50c8520506a101ea66653edaa3bd40bf34081`;
the old MCP manifest records a different checksum and is not used by this
experiment.

The experiment resolves each relative asset reference of the scene in memory
with the MCP's `resolve_uri`: the asset store `~/Desktop/isaac-mcp-assets`
(`ISAAC_MCP_ASSET_PATH` overrides it), then NVIDIA's pinned URL unless
`ISAAC_MCP_ASSET_STRICT=1`. Open the scene through the experiment so those
references are resolved. The experiment needs the lab-rigged
`ur5e-dt/robot/ur5e.usd`, which has a `tool0` frame that NVIDIA's published robot
lacks. The Vention bench has no public source; supply
`ur5e-dt/workstation/vention.usd` in the store.

The default code checkout in `experiments/ur5e_lego/configs/ur5e_lego.json` is
`~/Desktop/isaac-mcp`. For another layout, set `ISAAC_MCP_ROOT` to the checkout
before launching:

    git clone https://github.com/kalebcoleman/isaac-mcp.git /path/to/isaac-mcp
    export ISAAC_MCP_ROOT=/path/to/isaac-mcp

Earlier recorded runs used an older `isaac-mcp` revision
(`e93e06921ecef381dd62f8668c54c2137f850baa`, asset tree
`af27b735d00ff25c0a861c74e96a5d9f3139ab79`) that bundled all assets; changed
assets can alter the simulation.

The workstation is a visual model. Its black tabletop is lower than the
scene's invisible ground plane, so the experiment disables that plane and
adds a collision box aligned with the tabletop mesh. Table and brick positions
are in meters; joint angles are in radians and quaternions use wxyz order. The
rail remains stationary. Isaac Sim's Simple Room is loaded from its configured
asset root at z = -0.11 m, matching the lab workstation scene. Its built-in
table is removed and its colliders and rigid bodies are disabled. The camera
shows the workstation and room, with a dome light providing additional fill.

From the repository root, start a separate simulator instance with:

    ./experiments/ur5e_lego/scripts/run_ur5e_lego.sh

The script opens the Stage, Property, Console, and settings panels and selects the arm.
It pauses after loading. Press Play to attempt the transfer. It reports each
phase in the terminal, checks whether the brick rose with the gripper, and
checks its final position after release. Press Stop to restore the starting
scene, whether the transfer has finished or is still moving. Wait for the
`press Play to begin` message, then press Play to run the full transfer again.
The configuration is in `experiments/ur5e_lego/configs/ur5e_lego.json`; it contains the
default MCP location and brick positions.

On 2026-10-31, the transfer succeeded in Simple Room; the brick settled at
(-0.24955, -0.34889, -0.08547) m. [Video](evidence/ur5e-transfer-room.mp4),
[final frame](evidence/ur5e-transfer-room-result.png), and
[run log](evidence/ur5e-transfer-room-log.txt) record this run. The
[full run data](evidence/ur5e-transfer-run.jsonl.gz) includes the robot,
gripper, tool, brick and settings samples.

Earlier attempts without the room failed because the RG2 fingertips move downward as the
gripper closes and hit the table. The script now measures the closed fingertip
geometry in free air before approaching the brick. On 2026-10-30, one simulated
trial picked, lifted, transferred, and released the red brick; it settled at
(-0.24923, -0.35067, -0.08547) m, about 1 mm from the requested XY location.
The portable scene completed the same transfer twice with Stop and Play between
runs. The brick was dynamic and non-kinematic. These trials do not establish
robustness or physical calibration. Evidence is in
`outputs/rise/ur5e-lego-inspection/agent-run.log` and `success.png`.
The portable-scene log is `outputs/rise/ur5e-lego-portable/isolated.log`.
The full-window recording is
`outputs/rise/ur5e-lego-video/ur5e-brick-transfer.mp4`.
The recording and logs are local outputs ignored by Git.

## Changes and ownership

The experiment consists of `experiments/ur5e_lego/rise_ur5e_lego.py`,
`experiments/ur5e_lego/assets/ur5e_workstation.usda`, `experiments/ur5e_lego/configs/ur5e_lego.json`,
and `experiments/ur5e_lego/scripts/run_ur5e_lego.sh`. The script composes the workstation in a new
scene, adds the tabletop collider and bricks, measures gripper clearance, and
runs the arm and gripper through the transfer. Its Stop handler reloads it.
`python/bricksim/utils/physics_step.py` checks whether Isaac Sim already
removed a physics callback before cleaning it up after an interruption.

The separate `isaac-mcp` repository received documentation changes in
`README.md` and `docs/MCP-SERVER.md`. They explain how agents can inspect
windows, distinguish host tools from the in-simulator bridge, select and verify
the simulator process, and use the bridge client when tool discovery is stale.
No MCP source code or lab asset was changed for this experiment.

To control a separate experiment process through the generic MCP bridge, set
`ISAAC_MCP_ROOT` to the checkout and `ISAAC_MCP_PORT` to an unused port, then
pass the extension options to the launcher:

    export ISAAC_MCP_ROOT=/path/to/isaac-mcp
    ISAAC_MCP_PORT=8766 ./experiments/ur5e_lego/scripts/run_ur5e_lego.sh \
      --ext-path "$ISAAC_MCP_ROOT/exts/isaac.mcp.bridge" \
      --enable isaac.mcp.bridge

Verify the process and port with the bridge's `status` before acting. Do not use
this experiment to control physical hardware.
