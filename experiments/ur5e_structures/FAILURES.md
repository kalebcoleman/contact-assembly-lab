# Failure catalogue (simulation, breakage on)

Two sweeps built every structure once in Isaac Sim 6.2 with the full breakage
model on 2026-11-08:

- The **failure sweep**: 15 structures, controller `92af9bd`.
- The **capture sweep**: 16 runs, recorded at 1080p. It covers:
  - re-records of dog, human and cantilever;
  - five figures;
  - four break tests;
  - a press-force sweep.

  Commit `45717a8` has the same controller logic plus video capture.

Settings shared by both sweeps:
- release opens as wide as neighbouring bricks allow;
- the arm is held still while the fingers open;
- gripper contacts are logged, not fatal (`DOG_GRIPPER_CONTACT=log`).

Everything here is simulation, judged by simulator ground truth, one run per
setting; the 6.2 runs are deterministic. No hardware was used. The "Real test"
notes are proposals for later and have not been run.

Per-run details are generated from the raw outputs, with the settings, the
joint breaks and the solver warnings of each run:
- [sweeps/2026-11-08-failure-sweep.summary.md](sweeps/2026-11-08-failure-sweep.summary.md)
- [sweeps/2026-11-08-capture-sweep.summary.md](sweeps/2026-11-08-capture-sweep.summary.md)

[sweeps/README.md](sweeps/README.md) defines each term. The trials are also in
[trials.json](trials.json) and the dashboard's **Structures** view.

## Reading a failure

Three things are kept apart:

- **What stopped the controller.** This is the first failure the controller
  detects, for example "brick 2 detached from its support" or "did not complete
  the press".
- **What the physics model did.** BrickSim removes a joint when a converged
  breakage solve reaches utilization 1. A removed joint is often re-formed at
  once (a *transient* break, invisible to the controller). A *lasting* break
  is one the joint does not recover from.
- **Numerical health.** The breakage solver may fail to converge or report high
  slack before a break. A non-converged step breaks nothing, but a break that
  follows several of them rests on numerically suspect solves.

Gripper contacts are a separate, policy-level matter. In both sweeps they were
logged and never stopped a run.

## Results

Breaks are counted as lasting / transient. "Warnings before" counts the
breakage-solver non-convergence warnings logged just before the lasting break.

### Failure sweep (controller `92af9bd`)

| Structure | Connected at end | Stopped by | Breaks | Lasting break: cause, warnings before | Mechanism | Contacts |
|---|---|---|---|---|---|---|
| single | 1/1 | — | 0 / 0 † | | | 0 |
| column | 4/4 | — | 0 / 2 | | | 0 |
| human | 8/8 | — | 0 / 1 † | | | 3 (retreat drag) |
| stairs | 8/8 | — | 0 / 4 † | | | 0 |
| dog | 10/10 | — | 0 / 2 † | | | 2 (retreat drag) |
| cantilever | 3/4 | brick 2 joint lost | 1 / 1 | overload seen (u 4.5), 1 | A: press on the overhang | 0 |
| l_corner | 2/4 | brick 3 joint lost | 1 / 0 | overload seen (capacity exhausted), 12 | A | 0 |
| zigzag_6 | 3/6 | brick 2 joint lost | 1 / 2 | overload seen (exhausted), 1 | A | 0 |
| tower | 5/6 | brick 2 joint lost | 1 / 5 | overload seen (exhausted), 4 | B: release load on a 4-stud joint | 0 |
| lean_6 | 3/6 | brick 3 joint lost | 1 / 3 | overload seen (exhausted), 0 | B | 0 |
| column_10 | 9/10 | brick 1 joint lost | 1 / 7 | not sampled, 6 | B, repeated | 1 |
| table | 4/10 | no release clearance (16.2 mm) | 0 / 0 | | C: no room for the fingers | 1 |
| mixed_tower | 5/8 | brick 6 did not seat | 0 / 3 | | D: press stops on the studs | 0 |
| cross_tower | 1/10 | brick 2 joint lost | 1 / 0 | sudden (u 0.80 sampled), 4 | E: break after solver non-convergence | 0 |
| spiral_tower | 1/10 | brick 2 joint lost | 1 / 0 | sudden (u 0.80 sampled), 4 | E | 0 |

† The console log of this run lost some or all of its BrickSim events (see
[sweeps/README.md](sweeps/README.md)). The breaks shown come from the recording,
which samples each brick's joint to its planned support. Breaks of other
joints may be missing. For example, the dog's last joint broke at release and
re-formed 16 ms later.

### Capture sweep: figures and break tests (commit `45717a8`)

| Run | Connected at end | Stopped by | Breaks | Lasting break: cause, warnings before | Mechanism | Video |
|---|---|---|---|---|---|---|
| dog | 10/10 | — | 0 / 2 † | | (completed; the last brick's joint re-formed 16 ms after breaking) | [mp4](../../docs/media/dog_breakage_on.mp4) |
| human | 8/8 | — | 0 / 1 † | | (completed) | [mp4](../../docs/media/human_breakage_on.mp4) |
| robot | 5/5 | — | 0 / 3 † | | (completed) | [mp4](../../docs/media/robot.mp4) |
| cat | 5/5 | — | 0 / 1 † | | (completed) | [mp4](../../docs/media/cat.mp4) |
| cantilever | 3/4 | brick 2 joint lost | 1 / 1 | overload seen (u 4.5), 1 | A | [mp4](../../docs/media/cantilever_failure.mp4) |
| giraffe | 2/6 | brick 1 joint lost | 1 / 1 | overload seen (u 3.5), 6 | A: neck pressed on the end of the body | [mp4](../../docs/media/giraffe.mp4) |
| tree | 5/6 | brick 1 joint lost | 1 / 5 | overload seen (u 2.5), 5 | B: release load on the 4-stud trunk base, repeated | [mp4](../../docs/media/tree.mp4) |
| duck | 2/4 | brick 3 lost from the grasp | 0 / 0 | | F: grasp lost during transfer | (local only) |
| lean_ladder | 6/8 | brick 2 joint lost | 1 / 3 | overload seen (exhausted), 0 | B: growing overturning moment | [mp4](../../docs/media/lean_ladder.mp4) |
| cantilever_tip2 | 2/5 | brick 4 did not seat | 1 / 1 | sudden, 1 (the column base, during the press) | A | [mp4](../../docs/media/cantilever_tip2.mp4) |
| cantilever_root2 | 5/5 | — | 0 / 3 | | (control: completed) | [mp4](../../docs/media/cantilever_root2.mp4) |
| tower_2x2 | 3/10 | brick 1 joint lost | 1 / 3 | overload seen (exhausted), 2 | B | [mp4](../../docs/media/tower_2x2.mp4) |

The duck's full-resolution video stays local. The capture sweep summary links
every run's video.

### Press-force sweep (column of four aligned 2×4, `DOG_REQUIRED_FORCE_N`)

The press force is the force the controller must reach before it counts a
connection. The peak is the largest contact force measured.

| Press force | Peak force | Result | Lasting break |
|---|---|---|---|
| 1 N (default) | 1.15 N | 4/4, completed (2 transient breaks) | |
| 2 N | 2.22 N | 4/4, completed (3 transient breaks) | |
| 3 N | 3.92 N | failed, brick 1 joint lost | baseplate joint (8 studs), during the release after brick 2, sudden (u 0.89 sampled) |
| 5 N | 5.37 N | failed, brick 1 joint lost | baseplate joint, during a release, sudden (u 0.81 sampled) |

In this model, an aligned 8-stud joint survives presses peaking at 2.2 N and
loses its base joint at 3.9 N, on the gripper release that follows the press.
That makes it a clean dose-response test for mechanism B. See the
[3 N video](../../docs/media/column_press_3N.mp4).

## Mechanisms

**A. Press load overloads a weak joint below.**
- The press of a later brick runs through the structure. Joints with 4 studs
  of contact, or that carry an overhang, exceed utilization 1.
- The cantilever pair isolates the load position. Two 2×2 bricks pressed onto
  the free tip of a 2×6 that rests by one end on a 2×2 column:
  - pry the column's base joint loose during the press;
  - tip the 2×6, so the new brick never seats (`cantilever_tip2`).
- The same bricks pressed over the support complete (`cantilever_root2`).
- The giraffe shows the same lever: its neck is pressed onto the far end of
  the body, and the 4-stud base joint fails.
- *Real test:* build the cantilever pair and the giraffe, and press each brick
  with a force gauge, or the robot's force/torque reading, at 1 N and 2 N.
  Check whether the lower joint lifts or pops.

**B. Release load on a joint.**
- The joint's utilization rises while the fingers open on the brick just
  placed, then the joint breaks. No gripper contact is involved.
- The pads let go of a brick that the arm was pressing, so the stored press
  load reaches the new joint.
- Evidence:
  - tree, tower_2x2 and column_10: a 4-stud (or deep) base joint breaks
    transiently on one release after another, then for good;
  - lean_ladder: the joint fails as the lean grows;
  - press-force sweep: a harder press makes even an 8-stud joint fail on
    release.
- *Real test:* place a 2×4 on a 2×4 shifted 2 studs, then a 2×2 column. Watch
  whether the lower joint lifts when the gripper opens, at two press forces
  and two opening speeds.

**C. No room for the fingers.**
- The RG2 fingertip is about 11 mm thick and opens outward.
- Bricks 2 studs (16 mm) apart leave no opening that frees the held brick while
  keeping 2 mm from its neighbour, so the controller stops instead of hitting it.
- This is a gripper limit, not a physics one.
- *Real test:* find the smallest gap at which the RG2 can let go without
  touching the neighbour.

**D. Press stops on the studs.**
- The brick slides a little inside the gripper at first stud contact, then
  rests 1–1.3 mm above its seat.
- The arm reaches its press target without pushing it home (mixed_tower).
- *Real test:* does a real brick seat, or does it need a deeper press or a
  wiggle?

**E. Break after breakage-solver non-convergence.**
- On cross_tower and spiral_tower, a quarter-turned 2×4 on a 4-stud overlap
  is sampled at utilization 0.80 at most.
- The breakage solver then fails to converge four times, and the joint breaks
  at the end of the release: on the next converged solve, which the telemetry
  does not sample.
- The RG2 records no contact.
- This was "unexplained" in the first catalogue. It is now attributed to a
  sudden break that follows numerically suspect solves. Whether the real joint
  is overloaded there is open.
- *Next step in simulation:* log the breaking solve's utilization and slack
  in BrickSim. Rerun with a tighter solver tolerance.
- *Real test:* a quarter-turned 2×4 on a 2×4 (4 studs): does it survive the
  release and retreat?

**F. Grasp lost during transfer.**
- The duck's 2×2 passed the lift check, then slipped out of the fingers as
  the arm accelerated into the transfer. It fell to the table while the
  gripper closed to its stop.
- The controller has no grasp check during transfer, so it went on to "correct"
  its placement by 15 cm toward the fallen brick before the press failed.
- This is a controller and grasp gap, not joint physics. A gripper-width check
  during transfer and a bound on the prepress correction would catch it.
- *Real test:* hold a 2×2 with the RG2 at the same grip force and transfer
  speed.

**Transient breaks.**
- 59 of the 75 joint breaks across the two sweeps were re-formed within 1 s.
- They occur in every completed run except single.
- The controller only sees lasting breaks.
- A joint that breaks transiently on every release (tree, tower_2x2,
  column_10) is the clearest warning sign of a later lasting break.

**Gripper contacts (logged, not fatal).**
- human, dog, table, column_10 and cantilever_tip2 record a finger touching
  another brick (impulse 0.03–6.4 mN·s).
- On human, dog and table it is a finger dragging a brick while the arm lifts,
  where a neighbour limited the opening to a few millimetres.
- On column_10 a finger touches the brick below during release. On
  cantilever_tip2 it touches the tipping 2×6 during the press.
- None of these contacts detached a brick.

## Simulation gaps these runs expose

- The breakage model's capacity μF₀ = 0.7 N per contact point, from the
  BrickSim paper, has not been checked against these press and release loads.
  Mechanisms A and B are where real joints may hold and simulated ones break,
  or the reverse.
- The breakage solver often struggles:
  - 23 of the 31 runs logged at least one non-convergence or high-slack warning;
  - 12 of the 16 lasting breaks came after such warnings;
  - BrickSim treats a non-converged step as "no information" and keeps the
    previous utilization.
- The breaking solve is not sampled, so a `sudden` break cannot be explained
  from the telemetry. The utilization 1e6 is a sentinel for exhausted
  capacity, not a load.
- The console log loses some or all of its BrickSim events in 8 of 31 runs,
  all of them completed runs (both human runs lost every one). Solver warnings
  and breaks of secondary joints counted from it are lower bounds there. For
  each brick's joint to its planned support, the recording fills the gap.
- The breakage load is computed from weld forces PhysX reports. On CPU TGS,
  PhysX misreports their torque; this repository corrects it
  (`TestWeldConstraintForce`).
- Poses come from simulator ground truth, with no perception, and the pickup
  positions are known exactly.
