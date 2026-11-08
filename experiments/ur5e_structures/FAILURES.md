# Failure catalogue (simulation, breakage on)

Every structure was built once in Isaac Sim 6.2 with the full breakage model
(2026-11-08, controller `92af9bd`). The controller settings are:
- release opens as wide as neighbouring bricks allow;
- the arm is held still while the fingers open;
- gripper contacts are logged, not fatal (`DOG_GRIPPER_CONTACT=log`).

These are simulation results judged by simulator ground truth, one run each;
the 6.2 runs are deterministic. Each row is a prediction to check on the real
UR5e. The trials are in [trials.json](trials.json) (notes "Documented sweep")
and in the dashboard's **Structures** view.

## Results

| Structure | Placed | Outcome | Mechanism | Gripper contacts |
|---|---|---|---|---|
| single | 1/1 | completed | | 0 |
| column | 4/4 | completed | | 0 |
| stairs | 8/8 | completed | | 0 |
| human | 8/8 | completed | | 3 (retreat drag) |
| dog | 10/10 | completed | | 2 (retreat drag) |
| cantilever | 4/4 | brick 2 detached | A: press on the overhang | 0 |
| l_corner | 3/4 | brick 3 detached | A: press load through a 4-stud joint | 0 |
| zigzag_6 | 4/6 | brick 2 detached | A: press load through a 4-stud joint | 0 |
| tower | 6/6 | brick 2 detached | B: release load on a 4-stud joint | 0 |
| lean_6 | 4/6 | brick 3 detached | B: release load on a 4-stud joint | 0 |
| column_10 | 10/10 | brick 1 detached | B: release load accumulated over 10 layers | 1 |
| table | 4/10 | stopped before brick 4 | C: no gripper clearance (16.2 mm to the next leg) | 1 |
| mixed_tower | 5/8 | brick 6 did not seat | D: press stops on the studs | 0 |
| cross_tower | 2/10 | brick 2 detached | E: joint lost during retreat, no overload | 0 |
| spiral_tower | 2/10 | brick 2 detached | E: joint lost during retreat, no overload | 0 |

"Placed" counts bricks that connected during the run; a failure later can
detach one of them.

## Mechanisms

**A. Press load overloads a weak joint below.** The press of a later brick
(about 1.1–1.5 N) runs through the structure. Joints with 4 studs of contact,
or that carry an overhang, exceed utilization 1. The cantilever case is the
clearest: pressing the 2×2 onto the free tip of a 2×6 that rests on one 2×2
levers the joint below.
*Real test:* build the same structures and press each brick with a force
gauge, or the robot's force/torque reading, at 1 N and 2 N; check whether the
lower joint lifts or pops.

**B. Release load on a 4-stud joint.** No gripper contact is involved. The
joint's utilization rises to 0.7–1.0 while the fingers open on the brick just
placed, then the joint breaks. The pads let go of a brick that the arm was
pressing, so the stored press load and the friction from the opening pads
reach the new joint.
*Real test:* place a 2×4 on a 2×4 shifted 2 studs (tower, lean_6) and watch
whether it lifts or rotates when the gripper opens. Repeat with a slower and a
faster opening.

**C. No room for the fingers.** The RG2 fingertip is about 11 mm thick and
opens outward. Bricks 2 studs (16 mm) apart leave no opening that frees the
held brick while keeping 2 mm from its neighbour, so the controller stops
instead of hitting it. This is a gripper limit, not a physics one: the
structure's 2-stud gap rule is too tight for the RG2.
*Real test:* place two bricks 2 studs apart and see whether the RG2 can let go
without touching the first one. Find the smallest gap that works, then set the
same-layer gap rule to it.

**D. Press stops on the studs.** The brick slides a little (about 1.4 mm on
stairs) inside the gripper at first stud contact, then rests 1–1.3 mm above
its seat. The arm reaches its press target (0.5 mm below seated) without
pushing it home. Stairs no longer shows this after the release changes;
mixed_tower still does.
*Real test:* same structure. Does a real brick seat, or does it need a deeper
press or a wiggle?

**E. Joint lost during the retreat without overload (unexplained).** On
cross_tower and spiral_tower, a quarter-turned 2×4 on a 4-stud overlap stays
below utilization 0.9 and the RG2 records no contact, its fingers fully open
47 mm clear. The joint is still gone after the 10 cm retreat. The contact
monitor covers only RG2 bodies, so the quick-changer and arm links are not
watched. BrickSim may also drop a joint for a reason other than breakage.
*Next step in simulation:* extend the contact monitor to the quick-changer and
UR5e links, and log why BrickSim removes the joint.
*Real test:* a quarter-turned 2×4 on a 2×4 (4 studs): does it survive the
retreat?

**Retreat drag (logged, not fatal).** human, dog and table record a finger
dragging the brick just released while the arm lifts (1–6 mN·s). It happens
where a neighbour limited the opening to a few millimetres. It did not detach
those bricks.
*Real test:* watch for the brick lifting with the finger when the opening is
small.

## Simulation gaps these runs expose

- The breakage model's capacity μF₀ = 0.7 N per contact point, from the
  BrickSim paper, has not been checked against these press and release loads.
  Mechanisms A and B are where real joints may hold and simulated ones break,
  or the reverse.
- The breakage load is computed from weld forces PhysX reports. On CPU TGS,
  PhysX misreports their torque; this repository corrects it
  (`TestWeldConstraintForce`).
- Mechanism E is not explained by the breakage model.
- Poses come from simulator ground truth, with no perception, and the pickup
  positions are known exactly.
