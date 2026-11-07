# 2026-10-26 — Lab scene audit

The user's first target is two arms manipulating a shared object. This audit
documents the supplied single-arm lab starting point and does not claim that
the cooperative task is implemented or physically validated.

On 2026-10-26 in America/Phoenix, the local bridge's read-only USD inspection
reported these prims present:

- `/World/UR5e`
- `/World/QuickChanger`
- `/World/RG2_Gripper`
- `/World/Vention`
- `/World/workspace_camera_sim`

The stage reported articulation roots at `/World/UR5e/root_joint` and
`/World/RG2_Gripper/rg2_base_link`. The current root layer was the upstream
default stage; no clean project-owned scene copy has been saved yet. The lab
asset revisions and locations are documented in the [research overview](../../README.md).

A fresh local Codex chat subsequently called `mcp__rise_isaac__status` and
`mcp__rise_isaac__run_python` directly; both succeeded. The status reported
Isaac Sim 5.1.0, a visible process on port 8766, and 30 available bridge tools.
The five prims above were valid, active, and loaded. This verifies the local MCP
connection and scene presence; motion, force behavior, and camera output were
not tested by that verification.

The lab Quick Start disables gravity on the robot chain for position mirroring.
Its workstation is visual-only, with a ground-plane collider acting at
tabletop height. These are material assumptions for contact studies. No real
robot driver or external hardware was connected during this inspection.

Next, discuss the actual lab cell's gripper, robot-base poses, shared object,
sensor data, and task success criteria with the supervisor. Before trials,
create a separate scene copy, audit reference dependencies and frames, and
record measured versus assumed quantities.
