# UR5e brick stack

This simulation picks up three loose 2×4 bricks and builds a vertical stack on
an anchored 20×20 baseplate. The lower brick connects to the plate at stud
offset `(3, 8)`. The middle and upper bricks connect to the brick immediately
below at offset `(0, 0)`; all three connections use yaw index 0. Each link is
checked directly after release and again after the final settling interval.

Use the Isaac Sim 5.1 environment and lab assets described in
[`ur5e-lego.md`](ur5e-lego.md). From the repository root, run:

    ./experiments/ur5e_lego/scripts/run_ur5e_stack.sh

Set `ISAAC_MCP_ROOT` if the lab asset checkout is elsewhere. Press Play when
prompted; Stop rebuilds the initial scene. The stack settings are in
`experiments/ur5e_lego/configs/ur5e_stack.json`. A `null` support means the baseplate; a
number is the zero-based index of an earlier brick. The shared controller
measures the grasp, computes a target from the current support and held brick
poses, and corrects the held brick's world XY error before descending. This
correction uses simulated ground-truth poses. The controller commands a 0.5 mm
press below the nominal connection pose and holds it for one simulated second
after a connection appears. Positions are
in meters, joint angles in radians, and quaternions use wxyz order.

## Results

On 2026-10-31, corrected stack trials in Simple Room retained the plate-to-red,
red-to-blue, and blue-to-green connections after release and settling. In two
identical fixed-scene runs, the lateral error immediately before connection
was 0.150, 0.181, and 0.161 mm, compared with 1.009, 1.238, and 1.075 mm in
the measured baseline. Connection formation still corrected the vertical
position by approximately 1.7–1.8 mm. USD poses may update at the rendering
rate. These results are not a statistical success rate or a physical-force
calibration; hardware would need measured brick and support poses to perform
the same correction.

- [Video](evidence/ur5e-stack-room.mp4) and [final scene](evidence/ur5e-stack-trial-01.png)
- [First trial log](evidence/ur5e-stack-trial-01.txt) and [connection query](evidence/ur5e-stack-connections-01.json)
- [Second trial log](evidence/ur5e-stack-trial-02.txt) and [connection query](evidence/ur5e-stack-connections-02.json)
- [Alignment comparison](evidence/ur5e-stack-alignment-comparison.json) and [full run data](evidence/ur5e-stack-run.jsonl.gz)
- [Baseplate runs in Simple Room](ur5e-baseplate.md)

Before adding the room, a separate replay sampled brick positions during the lifts. The largest
per-axis variation relative to the gripper hand was 0.15 mm for the red brick
and 0.22 mm for the blue brick. In a different replay, their largest variations
relative to the robot tool were 1.24 and 1.57 mm. The different frames can
include movement between the gripper hand and the tool, so these measurements
do not establish finger slip or grip strength. Physics callbacks also reported
a nearly stationary gripper joint angle alongside a velocity of about
1.79 rad/s; the inconsistent readings need further investigation. Neither a
contact-force measurement nor a disturbance test was performed.
[Grasp measurements](evidence/ur5e-stack-grasp-observations.json).

## Controlled rejection

In a separate room trial, the red brick was connected to the plate normally. With the
timeline paused before the red-to-blue connection formed, the simulated
assembly requirement was raised from 1 N to 1000 N. After resuming, the blue
brick press timed out with `connected=False`; the last available contact debug
readings were about 6.4 N. The physics graph still showed the plate-to-red
connection and no red-to-blue connection. The timeline was still playing after
the reported failure, so it was paused before restoring the normal 1 N
requirement. This checks rejection and reporting under an
artificial threshold; it does not model or measure physical brick breakage.
[Video](evidence/ur5e-stack-rejection-room.mp4), [injection settings](evidence/ur5e-stack-failure-injection.json),
[failure log](evidence/ur5e-stack-failure.txt),
[post-failure graph](evidence/ur5e-stack-failure-result.json), and
[restored threshold](evidence/ur5e-stack-threshold-restored.json). The
[full run data](evidence/ur5e-stack-rejection-run.jsonl.gz) includes the
active threshold at each step.

To repeat this rejection test, start the stack with the generic bridge as in
[`ur5e-lego.md`](ur5e-lego.md), verifying its process and port. After the log
reports `1/3 bricks secured`, pause before the second connection forms. With
`ISAAC_MCP_ROOT` set to the checkout and port 8766 selected, run:

    PYTHONPATH="$ISAAC_MCP_ROOT/mcp" .venv/bin/python -m isaac_mcp.client --port 8766 run_python '{"code":"import omni.timeline\nfrom bricksim.core import get_assembly_thresholds, set_assembly_thresholds, lookup_physics_connection\nassert not omni.timeline.get_timeline_interface().is_playing()\nassert lookup_physics_connection(\"/World/managed/Parts/Part_1\", 1, \"/World/managed/Parts/Part_2\", 0) is None\nt = get_assembly_thresholds()\nt.required_force = 1000.0\nset_assembly_thresholds(t)\nresult = get_assembly_thresholds().required_force"}'

Resume Play and expect the second press to report failure. Pause, then restore
`required_force` to 1.0 with `get_assembly_thresholds()` and
`set_assembly_thresholds()` before another trial. Change thresholds only
while the timeline is paused.
