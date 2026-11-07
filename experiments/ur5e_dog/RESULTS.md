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
