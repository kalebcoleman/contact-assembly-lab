# UR5e four-brick stack

This experiment picks up four loose 2×4 bricks and stacks them on an anchored
20×20 baseplate. The red brick connects to the plate at stud offset `(3, 8)`;
the blue, green, and yellow bricks each connect to the one below at `(0, 0)`.
Every connection uses yaw index 0.

Use the Isaac Sim 5.1 environment and lab assets described in
[`ur5e-lego.md`](ur5e-lego.md). From the repository root, run:

    ./experiments/ur5e_lego/scripts/run_ur5e_stack_four.sh

Set `ISAAC_MCP_ROOT` if the lab asset checkout is elsewhere. Press Play when
prompted; Stop rebuilds the scene. The source positions and support order are
in `experiments/ur5e_lego/configs/ur5e_stack_four.json`. The existing
[three-brick experiment](ur5e-stack.md) remains available separately.

The same controller measures the simulated held-brick and support poses,
corrects the XY target before the press, and checks each connection after
release and final settling. These poses are simulation ground truth; hardware
would need measured poses and calibrated frames. Run logs contain the active
settings, commands, poses, contacts, and placement errors as described in the
[experiment index](../README.md).

## Recorded run

On 2026-10-31, the four-brick run completed in Simple Room. All four direct
connections remained after release and settling. The lateral errors just
before connection were 0.145, 0.187, 0.193, and 0.191 mm for the red, blue,
green, and yellow bricks respectively. The vertical error at those samples
was 1.53–1.92 mm; the simulation still corrects that position when making a
connection. USD poses can update at the render rate. This is one fixed-scene
simulation trial, not a physical calibration or measured success rate.

- [Video with settings visible](evidence/ur5e-stack-four-room.mp4) and
  [completed stack](evidence/ur5e-stack-four-result.png)
- [Connection check](evidence/ur5e-stack-four-connections.json) and
  [phase and error summary](evidence/ur5e-stack-four-summary.json)
- [Full physics-step log](evidence/ur5e-stack-four-run.jsonl.gz) (12,236 samples)

The original three-brick stack was also replayed after the controller change;
all three connections remained after settling. [Connection check](evidence/ur5e-stack-three-regression-after-four.json).
