# Dog assembly results

Simulation only. Each run is a fresh virtual scene; nothing is reset or edited mid-run.

| Run | Pickup layout | Connections | Outcome |
|---|---|---|---|
| 1 | `dog.json`, head at (-0.34,-0.38) | 8/10 | head not retained (finger closed on baseplate edge) |
| 2 | same | 8/10 | identical failure |
| 3 | `dog.json`, head at (-0.43,-0.295) | 10/10 | success; continuous video recorded |
| 4–8 | `variants/seed_1..5.json` | 10/10 each | 5/5 success |

Variants jitter every pickup XY by up to ±15 mm (seeded, validator-checked; yaw 0).
Across the five: max grasp-center error 0.8 mm, max pre-press XY correction 1.6 mm
(mean 1.3 mm), 0 timeouts. No recovery logic exists, so "0 recovery attempts" means
none were implemented, not that none were needed.

## What is and is not sensed

Pickup poses, held-brick pose and the pre-press XY correction come from simulator
ground truth, as do snap/weld connections (breakage disabled). Pickup positions are
known to the controller exactly. This is not perception and not stud insertion.
The jitter set is small and in-distribution; it says nothing yet about piles,
unknown positions, yaw or contact uncertainty.

## Structures, yaw and the full model (2026-11-07)

Structure specs are in `experiments/ur5e_structures/`. Every run below is simulation,
one attempt each, simulator ground truth for poses (not sensing). "Breakage off" runs
used the baseline's lenient assembly check (2 mm, 5 degrees, 1 N) and are **not**
the full BrickSim model.

Breakage-off successes: dog (10), tower (6), l_corner (4), stairs (8), spiral_tower
(10, each brick turned a quarter turn), human v1 (9, whose 2x6 shoulder bar rocked
before seating on a 4-stud patch).

### Why breakage on failed, and what fixed it

The breakage solver sees every joint's load; `get_connection_utilization` over 1 means
overloaded. A per-step utilization log (`outputs/ur5e_dog/utilization-*.csv`) showed:

1. **One-step gripper release** discharged the press load as an impulse; the lower
   joint hit 0.98 at release and the new joint broke. Fixed by easing the arm back to
   the seat height and opening the gripper over 1 s (`DOG_RELEASE_RAMP_S`).
2. **Press force grew with stack height** (about 1.2 N on bricks 1-2, about 7 N on
   bricks 3-4) because the arm kept descending after seating; lower joints reached
   1.1-3.1 times capacity. Fixed by freezing the arm target once the connection
   forms (`DOG_FREEZE_ON_CONNECTION`).
3. **Pressing harder is not free**: a 5 N required force with a 3 mm press broke the
   first joint with breakage on. Tighter angle (2 degrees) and position (1 mm)
   tolerances are set; required force stays at 1 N for breakage on.
4. Some "failed to converge" solver events were logged and counted as breaks by the
   native code; they are numerical failures, not confirmed overloads.

Result with the fixes (breakage on): single brick 1/1, aligned 8-stud column 4/4.
The 6-brick cross-bonded tower (4-stud joints) built 5 bricks, then the brick-4 joint
let go after brick 5; its cause is not yet established.

The UI "Enable breakage check" box reads the setting once at startup and does not
reflect the controller's later change; use the console line `breakage enabled=` or
`breakage_settings.enabled` in the run log.

### Run index

Logs are about 100 MB each and stay local; the dashboard reads them from
`outputs/ur5e_lego/` (`python3 experiments/ur5e_dashboard/server.py` from this
checkout shows them with the committed evidence). "off (not set)" means breakage was
left at its default, disabled. The first row is the EULA stop.

| Run (UTC) | Bricks | Breakage | Connected | Outcome | First error |
|---|---|---|---|---|---|
| 20261107T031244 | ? | off (not set) | 0/? | failed |  |
| 20261107T031508 | 10 | off (not set) | 8/10 | failed | Brick 9 was not retained during lift |
| 20261107T032556 | 10 | off (not set) | 8/10 | failed | Brick 9 was not retained during lift |
| 20261107T033059 | 10 | off (not set) | 10/10 | success |  |
| 20261107T034550 | 10 | off (not set) | 10/10 | success |  |
| 20261107T034953 | 10 | off (not set) | 10/10 | success |  |
| 20261107T035357 | 10 | off (not set) | 10/10 | success |  |
| 20261107T035759 | 10 | off (not set) | 10/10 | success |  |
| 20261107T040202 | 10 | off (not set) | 10/10 | success |  |
| 20261107T171358 | 6 | off (not set) | 6/6 | success |  |
| 20261107T171648 | 4 | off (not set) | 4/4 | success |  |
| 20261107T171848 | 8 | off (not set) | 8/8 | success |  |
| 20261107T172758 | 10 | off (not set) | 10/10 | success |  |
| 20261107T173221 | 9 | off (not set) | 9/9 | success |  |
| 20261107T173622 | 9 | off (not set) | 9/9 | success |  |
| 20261107T174117 | 6 | True | 1/6 | failed | Brick 2 detached during the press |
| 20261107T174237 | 10 | True | 0/10 | failed | Brick 1 detached during the press |
| 20261107T174515 | 1 | True | 1/1 | success |  |
| 20261107T174615 | 6 | True | 1/6 | failed | Brick 2 detached during the press |
| 20261107T174729 | 4 | True | 2/4 | failed | Brick 2 detached from its support |
| 20261107T174924 | 4 | True | 0/4 | failed | Brick 1 detached during the press |
| 20261107T175024 | 6 | False | 5/6 | failed | Brick 6 did not complete the press: connected=False, held=0.00 s, bric |
| 20261107T175559 | 4 | True | 2/4 | failed | Brick 2 detached from its support |
| 20261107T175751 | 4 | True | 4/4 | failed | Brick 4 detached from its support |
| 20261107T180020 | 4 | True | 4/4 | success |  |
| 20261107T180225 | 6 | True | 5/6 | failed | Brick 4 detached from its support |

## Isaac Sim 6.2 regression (2026-11-07)

Same controller and tuning (no setting changed), Isaac Sim 6.2.0.0 / PhysX 5.9.2,
one run per row, simulation only. The 6.2 runs are deterministic: a repeated
stairs run failed with bit-identical brick coordinates. All trials, with failure
reasons, are in `experiments/ur5e_structures/trials.json` and the dashboard's
**Structures** view. "Connected" counts bricks still connected at the end.

Reproduced from 5.1: dog and seeds 1–5 (10/10 each, breakage off), single, tower,
l_corner, spiral_tower, human (8/8, the current 8-brick recipe), column 4/4 with
breakage on, and the tower with breakage on failing the same way (brick 4 detaches
after brick 5). The case suite C01–C13 also reproduces (see
`experiments/ur5e_lego/docs/ur5e-cases.md`), as do the baseplate (3/3), stack (3/3)
and stack-four (4/4) experiments. The transfer experiment was not run: it waits for
Play, and desktop input could not reach the window.

Differs from 5.1: **stairs 6/8** (8/8 on 5.1). Brick 7 (2-stud shift onto brick 4)
slid about 1.4 mm in -x inside the gripper at first stud contact, then rested
1.28 mm above its seat at 0.5° tilt; the arm had already reached its press target
(0.5 mm below seated), so the brick never seated and no connection formed.

New structures (`experiments/ur5e_structures/specs.py`):

| Structure | Breakage off | Breakage on (first failure) |
|---|---|---|
| cantilever (4) | 4/4 | 4/4 |
| lean_6 (6) | 6/6 | 1/6 (brick 2 detached) |
| zigzag_6 (6) | 6/6 | 2/6 (brick 3 detached) |
| mixed_tower (8) | 5/8 (brick 6 did not seat) | 4/8 (brick 3 detached) |
| table (10) | 10/10 | 0/10 (brick 1 detached) |
| cross_tower (10) | 10/10 | 1/10 (brick 2 detached) |
| column_10 (10) | 7/10 (brick 8 did not seat) | 3/10 (brick 4 detached) |

With breakage on, the 5.1 structures stairs (3/8), spiral_tower (1/10), dog (1/10)
and human (1/8) also fail; l_corner (4/4) completes.

Two failure modes recur. Breakage off: a press high in a stack stops with the
brick resting on the studs (stairs, mixed_tower, column_10). Breakage on: a
joint near the base, often a 4-stud joint, breaks while a later brick is placed,
including bricks beside it rather than above it (table, human, dog). Neither cause
is established yet; the release ramp and freeze-on-connection fixes were tuned on
aligned stacks.

## Why joints broke with breakage on (2026-11-07)

The breakage model (BrickSim paper, Eq. 10) loads each brick with
b = (momentum change - external impulse) / dt. In the code the external impulse
is the momentum change minus the PhysX weld-constraint impulses, so each brick's
load is the weld (connection) force and torque PhysX reports. A joint breaks when
utilization max (|F_t| + F_a) / (mu (F_r + F_0)) exceeds 1 for longer than the
0.05 s cooldown.

**1. A PhysX reporting error (fixed in native code).** PhysX's CPU TGS solver,
which Isaac Sim uses here, reports a weld's torque about the weld point short by
2 rA x F, rA being the distance from body A's centre of mass to the weld
(`writeBack1DStep`, DyTGSContactPrep.cpp; identical in PhysX 5.6.1 and 5.9.x, so
5.1 had it too). For a brick welded to the baseplate, rA is the brick's distance
from the plate centre. Under a robot press (about 2.4 N) a 2x2 at stud (6, 6) got
a spurious 0.12 N*m and utilization 2.1 on its first solve, so it broke while
still being pressed; the same brick at (9, 9) read 0.00. `TestWeldConstraintForce`
reproduces the PhysX behaviour on raw PhysX (PGS reports 0, CPU TGS -2 rA x F),
and `PhysicsLegoGraph` now adds 2 rA x F back on CPU TGS scenes. Afterwards the
(6, 6) brick peaks at 0.26 and builds.

**2. The opening gripper finger hits the neighbouring brick (controller).** With
the fix, `human` still breaks its first brick (an 8-stud 2x4 on the plate) while
the second brick, 2 studs away along x, is released: the first brick is welded
to the kinematic plate and does not move, yet its joint load rises from 0 to 0.83
within 0.05 s as the RG2 fingers start opening (about 0.12 rad), then it breaks
and the brick jumps 2.4 mm away from the gripper. A welded brick on a fixed plate
only gains load from contact, so the opening finger is pushing it. The 2-stud
same-layer gap clears the closed fingers but not the opening ones. table, dog and
human fail this way; this would also happen on the real robot.

**3. Marginal 4-stud joints during release.** l_corner and cantilever now fail
at 1.000x utilization on a 4-stud joint during the 1 s gripper-release ramp (they
passed before the fix, by the spurious torque partly cancelling the real one).

Breakage on, bricks connected during the run (console), before -> after the fix:
single 1/1 -> 1/1, column 4/4 -> 4/4, tower 5/6 -> **6/6**, spiral_tower 2/10 ->
6/10, stairs 4/8 -> 6/8, cross_tower 2/10 -> 4/10, column_10 4/10 -> 6/10, lean_6
2/6 -> 3/6, table 1/10 -> 2/10, zigzag_6 3/6, human 2/8, mixed_tower 5/8, dog 2/10
unchanged, l_corner 4/4 -> 3/4, cantilever 4/4 -> 3/4. Trials after the fix are
marked in `experiments/ur5e_structures/trials.json`.

Next: open the gripper only as far as the gap allows (or place so the fingers open
away from neighbours), then look at the release load on 4-stud joints.

## Gripper contact fix and documented failures (2026-11-08)

The release now opens only as wide as neighbouring bricks allow and holds the
arm still while the fingers open, and every gripper contact with another brick
is logged (or fails the run). The whole set was then built once with breakage on.
Completed: single, column, stairs 8/8, human 8/8, dog 10/10. The ten failures,
grouped by mechanism with a real-robot test for each, are in
[../ur5e_structures/FAILURES.md](../ur5e_structures/FAILURES.md).
