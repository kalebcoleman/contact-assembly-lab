# UR5e brick assembly: meeting brief

**Status: simulation only.** No physical robot was connected and no safety setting
was changed. This is not a statement of hardware readiness.

## What I can show

Run `python3 experiments/ur5e_dashboard/server.py`, open `http://127.0.0.1:8765`, and
choose **Test cases**. Each case shows its inputs, written prediction, outcome,
measurements, assistance, limits and logs.

- Videos of real runs: [nominal](evidence/ur5e-case-C01-run.mp4),
  [rejection](evidence/ur5e-case-C05-run.mp4), [unreachable](evidence/ur5e-case-C12-run.mp4).
  Other cases link one of these, labeled as representative.
- [Suite manifest](evidence/ur5e-cases-suite.json) with commits, environment and asset hashes.
- [ROS 2 sample](evidence/ur5e-ros-graph-5.1.json), taken from a separate process.

## Verified results

Isaac Sim 5.1.0. C01 to C12 ran at `5f7f411`, C13 at `754f904`. Each ran **once**, in a
fresh process, so this is not a success rate. The simulator accepts up to 2 mm position
error, 5° yaw and requires 1 N.

| Case | Test | Predicted | Observed | Lateral (mm) | Yaw (°) |
|---|---|---|---|---|---|
| C01 | Nominal, three bricks | Connected | Connected, 3/3 | 0.15–0.18 | 0.8–1.8 |
| C02 | Nominal, one brick | Connected | Connected | 0.12 | 0.9 |
| C03 | Placement +1 mm X | Connected | Connected | 0.88 | 0.9 |
| C04 | Placement +1 mm Y | Connected | Connected | 0.98 | 0.9 |
| C05 | Placement +3 mm X | Rejected | Rejected | 2.25 | n/a |
| C06 | Placement yaw +3° | Connected | Connected | 0.20 | 3.5 |
| C07 | Placement yaw +8° | Rejected | Rejected | n/a | 8.7 |
| C08 | Placement +8 mm (one stud) | Wrong stud | Wrong stud, flagged | 7.89 | 0.9 |
| C09 | XY correction off | Connected | Connected | 1.03 | 0.9 |
| C10 | Grasp +2 mm, XY correction off | Rejected | **Connected** | 0.99 | 1.1 |
| C11 | Brick rotated 5° at pick | Connected | Connected | 0.14 | 1.0 |
| C12 | Brick out of reach | Not reached | Not reached | n/a | n/a |
| C13 | Grasp +2 mm, held brick not measured | Rejected | Rejected | 2.80 | 1.1 |

Lateral and yaw come from the last sample before connection. For rejected cases, C05 and
C13 show the checker's position error, and C07 shows the last recorded yaw.

**What this shows**

- The correction helps: 0.12 mm with it (C02) against 1.03 mm without (C09).
- **C10 was my wrong prediction, and the useful result.** The plan still read the held
  brick's true pose, which hid a 2 mm grasp error. Removing that (C13) caused a
  rejection. Hardware has no such measurement, so C13 is closer to hardware than C02,
  and it still uses true source and support poses.
- C05 was close: a commanded 3 mm produced 2.25 mm against a 2 mm limit. I did not locate
  the exact boundary.
- C12 failed only by a 15 s timeout. The arm moved to its limit first, and nothing checks
  reachability beforehand. **Hardware needs that check.**
- C08 shows that a one-stud error connects successfully in the simulator. Only the
  script's offset check caught it.

## What is physics and what is assisted

| Part | How it works in simulation |
|---|---|
| Contact physics | PhysX contact and a force-limited gripper drive hold the brick by friction. No attachment joint at grasp |
| Connection | **Assisted.** Studs are not inserted. When thresholds pass, the checker snaps the brick to the grid and adds a weld, closing a gap of about 1.7 mm |
| Ground truth | Exact source, support and held-brick poses. Some can be disabled by case; source and support never are |
| Other | Breakage off, kinematic baseplate, no latency or backlash, unmeasured mass and friction, forces not calibrated |

ROS 2 is verified on this setup only with no assembly running: clock, joint states and TF
matched USD to under 1 µm. Gripper frames do not connect to the arm in TF.

## Simulation versus the real world

| Area | In simulation | Unknown on hardware |
|---|---|---|
| Base and table frames | Exact, from the USD scene | Measured base-to-table and base-to-plate transforms |
| Tool frame | `tool0` plus a measured simulated offset | Real TCP and flange-to-fingertip offset |
| Brick and plate poses | Exact | How we measure them, and with what error |
| Gripper | RG2 joint drive and simulated closing | Real interface, grip force and repeatability. USD still references a Robotiq part |
| Grasp | Friction model, no measured slip | Slip, and whether fingers square the brick |
| Insertion | Snap and weld at 1 N | Real insertion force, alignment window and failure modes |
| Calibration | Not needed | Method, acceptance limit and how often to repeat |
| Control | RMPflow on ideal joint drives | Interface, speed and force limits, latency, tracking error, contact stop behavior |
| Reachability | Timeout after the motion | Check before moving, plus singularities and collisions |
| Timing | Simulation clock | Sync between robot, gripper and any sensors |

## Staged plan for a first supervised hardware test

This is a proposal for discussion. Each stage needs Max's approval, and limits and safety
procedure are for Max and the lab to set. **Stop on anything unexpected.**

| Stage | Do | Pass before moving on |
|---|---|---|
| 0. Agree | Name the responsible supervisor, E-stop operator, risk review, limits and workspace | Written sign-off |
| 1. Offline | Add a reachability pre-check. Run targets in URSim or fake hardware | No unreachable or colliding target is sent |
| 2. Read-only | Connect with no motion commands. Log joints and compare with simulation | Topics, frames and units confirmed |
| 3. Measure | Measure base, table, plate and TCP using the lab's method | Agreed accuracy, recorded |
| 4. Free motion | Supervised, low speed, no bricks, well clear of the table | Tracking error recorded; E-stop tested |
| 5. Gripper | Open and close with nothing, then on a loose brick, arm still | Grip force and repeatability recorded |
| 6. Pick | One brick, lift slightly, release at the same place | Pose error measured; compare with C10 and C13 |
| 7. Place | One brick, limited force, stop on contact, plate fixed | Result compared with simulation, then decide next step |

## Decisions for the meeting

1. Who supervises, and which safety limits apply?
2. How do we measure brick and plate poses without simulator ground truth?
3. What accuracy is enough? The 2 mm limit is a simulator setting, not a measurement.
4. Which control interface: ROS 2 driver, or something else?
5. Is the current RG2 the gripper for this test?

## Open items

- `check_parity.py` still fails on four unreferenced `robot/configuration/*` files. They
  are not in the robot's USD dependencies and were not recorded as a new baseline. The
  check should follow dependencies instead of listing the folder.
- isaac-mcp runtime tools need fixes on 5.1: see the
  [tool report](isaac-mcp-5.1-tool-report.md).
