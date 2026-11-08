# Failure analysis (simulation)

Every structure was built by the UR5e in Isaac Sim 6.2 with BrickSim's
joint-strength (breakage) model on. A **run** is one complete build attempt at
the default settings:
- 1 N press;
- 1 s gripper release;
- gripper contacts logged rather than fatal.

Runs at other settings are listed separately below. The simulation is
deterministic, so repeating a run gives the same result; the repeats below
confirm that.

Nothing here ran on hardware. Every run, with its settings, is in the
[sweep summaries](sweeps/README.md), and every structure is pictured in the
[structure catalog](../../docs/STRUCTURES.md).

## What we tested

Generated from the sweep summaries by `catalog.py`.

<!-- results:start -->
| Structure | What it tests | Runs | Completed | What stopped it | Mechanism |
|---|---|---|---|---|---|
| [Dog](../../docs/STRUCTURES.md#dog) | wide bricks bridging legs; ten-brick figure | 3 | 3 | — | — |
| [Arch bridge](../../docs/STRUCTURES.md#bridge) | a deck landing on two piers (corbel arch) | 1 | 1 | — | — |
| [House](../../docs/STRUCTURES.md#house) | a lintel over a doorway; stepped roof | 1 | 1 | — | B |
| [Log cabin](../../docs/STRUCTURES.md#log_cabin) | courses alternating direction; interlocking corners | 1 | 1 | — | — |
| [Steam locomotive](../../docs/STRUCTURES.md#locomotive) | a chassis resting on three wheels | 1 | 0 | a brick slipped from the grasp | — |
| [Lighthouse](../../docs/STRUCTURES.md#lighthouse) | a seven-layer tower on a wide base | 1 | 1 | — | — |
| [Castle gate](../../docs/STRUCTURES.md#castle_gate) | a lintel over a gate; battlements | 1 | 0 | a joint broke | — |
| [Tree](../../docs/STRUCTURES.md#tree) | a crown on a 2x2 trunk (4-stud joints) | 1 | 1 | — | B |
| [Table](../../docs/STRUCTURES.md#table) | four legs, then tops spanning them | 2 | 0 | no room to release | C |
| [Table, grip-aware](../../docs/STRUCTURES.md#table_grip) | the table with grips chosen for room | 1 | 0 | grasp failed | — |
| [Table, wide gaps](../../docs/STRUCTURES.md#table_wide) | 4-stud gaps on both axes | 1 | 0 | a joint broke | — |
| [Trestle table](../../docs/STRUCTURES.md#trestle_table) | slab legs gripped end to end | 1 | 1 | — | — |
| [Cross-bonded tower](../../docs/STRUCTURES.md#cross_tower) | alternating quarter turns (4-stud overlaps) | 1 | 1 | — | E |
| [Spiral tower](../../docs/STRUCTURES.md#spiral_tower) | repeated quarter turns (4-stud overlaps) | 2 | 0 | a joint broke | E |
| [L corner](../../docs/STRUCTURES.md#l_corner) | a corner brick joining two posts | 2 | 0 | a joint broke | A |
| [Offset tower](../../docs/STRUCTURES.md#tower) | alternating directions with 1-stud shifts | 1 | 1 | — | B |
| [Cantilever](../../docs/STRUCTURES.md#cantilever) | a press on a cantilever tip | 3 | 0 | a joint broke | A |
| [Cantilever, two bricks at the tip](../../docs/STRUCTURES.md#cantilever_tip2) | two bricks at a cantilever tip | 2 | 0 | a brick did not seat | A |
| [Cantilever, two bricks over the support (control)](../../docs/STRUCTURES.md#cantilever_root2) | the same bricks over the support (control) | 2 | 2 | — | — |
| [Leaning ladder](../../docs/STRUCTURES.md#lean_ladder) | a lean that grows every layer | 2 | 0 | a joint broke | B |
| [2x2 tower](../../docs/STRUCTURES.md#tower_2x2) | ten 4-stud joints | 2 | 0 | a joint broke | B |
| [Lean 6](../../docs/STRUCTURES.md#lean_6) | 2-stud shifts (4-stud joints) | 2 | 0 | a joint broke | B |
| [Zigzag 6](../../docs/STRUCTURES.md#zigzag_6) | shear at every joint | 2 | 0 | a joint broke | A |
| [Column of ten](../../docs/STRUCTURES.md#column_10) | load on the base growing with height | 1 | 1 | — | B |
| [Column, turned 90 degrees](../../docs/STRUCTURES.md#column_turned) | the column with bricks turned 90 degrees | 2 | 2 | — | — |
| [Single brick](../../docs/STRUCTURES.md#single) | one brick (sanity check) | 2 | 2 | — | — |
| [Column](../../docs/STRUCTURES.md#column) | aligned 8-stud joints | 3 | 3 | — | — |
| [Stairs](../../docs/STRUCTURES.md#stairs) | mixed sizes stepping up | 2 | 2 | — | — |
<!-- results:end -->

The mechanism letters are explained below. A dash means the structure
completed every run.

## Every failure, step by step

"Brick 4 of 10" means the fourth brick placed. "Its own joint" is the joint
just formed between that brick and its support. All failures below happen at
the default settings, and repeated runs fail at the same step.

| Structure | Where it fails | What happens | Likely cause | Fixes to try |
|---|---|---|---|---|
| Table | brick 4 of 10 (fourth leg), release | The controller refuses to open: one finger sits in a 16 mm gap beside leg 3, and opening would touch it. | Gripper geometry (C) | Tighter release margin; legs 4 studs apart on the finger side ([grip-aware table](../../docs/STRUCTURES.md#table_grip)); [trestle legs](../../docs/STRUCTURES.md#trestle_table) gripped end to end |
| Mixed tower | brick 6 of 8, press | A 2x4 half supported by a 2x2 tips when pressed at its middle, slides in the fingers and never seats. | Pressed over the unsupported half (D) | Grip and press over the supported half; deeper press |
| Cross-bonded tower | brick 2 of 10, release | Its own 4-stud joint (a quarter turn on the brick below) breaks after four breakage-solver non-convergences. | Simulator numerics on a 4-stud overlap (E) | Slower release; grip end to end |
| Spiral tower | brick 2 of 10, release | The same as the cross-bonded tower. | Simulator numerics (E) | Slower release; grip end to end |
| L corner | brick 3 of 4, release | Its own 4-stud joint breaks, overloaded since the press. | Press load released on a 4-stud joint (A, B) | Slower release; grip over the support |
| Offset tower | brick 6 of 6, release | The joint between bricks 1 and 2 (4 studs) breaks. | Release load reaching a low joint (B) | Slower release |
| Lean 6 | brick 4 of 6, release | The joint between bricks 2 and 3 breaks. | Release load, growing overhang (B) | Slower release |
| Zigzag 6 | brick 4 of 6, release | The joint between bricks 1 and 2 breaks. | Release load, shear (B) | Slower release |
| Leaning ladder | brick 7 of 8, release | The joint between bricks 1 and 2 breaks as the lean grows. | Overturning moment (B); designed to fail | Slower release; it may be at its limit |
| 2x2 tower | brick 4 of 10, release | The base joint (4 studs) breaks. | Release load on 4-stud joints (B) | Slower release |
| Column of ten | brick 10 of 10, release | The base joint breaks after breaking and re-forming on earlier releases. | Release load on the base (B) | Slower release |
| Tree | brick 6 of 6, release | The trunk's base joint (4 studs) breaks. | Release load on a 4-stud joint (B) | Slower release |
| House | brick 3 of 8, release | The first wall joint (8 studs) breaks with no visible motion. | Release load (B) | Slower release: **a 2 s release completes** |
| Cantilever | brick 4 of 4, release | After the tip press, the joint between the two column bricks breaks. | The tip press levers the column (A) | Slower release; sub-assembly: attach the load to the 2x6 first, then place the pair |
| Cantilever, two bricks at the tip | brick 4 of 5, press | The press pries the column's base joint loose before the brick seats. | Press lever (A) | Sub-assembly; designed to fail |

Two patterns stand out:
- **13 of the 15 joint losses happen while the gripper opens.**
  - 12 are recorded during a release.
  - The column of ten's break phase is missing from its log, but its base
    joint broke and re-formed on earlier releases.
- **The press puts the load in; the release lets it out.** Even the A
  failures, overloaded by a press, break on the release that follows.

A slower or gentler release is therefore the first fix to try. Grip strategy
and sub-assembly come next.

## How builds fail

Failures fall into two groups.
- **Physics failures** are what BrickSim's joint model predicts: a joint is
  overloaded and breaks.
- **Gripper and controller limits** come from how this robot grips and
  places bricks. A different grasp or a smarter controller could remove them,
  which is future work.

### Physics failures

**A. Pressing a brick breaks a joint below.**
- Pushing a new brick down loads everything under it.
- Joints with only 4 studs of contact, or joints that carry an overhang, give
  way.
- Seen in: cantilever, cantilever with two bricks at the tip, L corner, zigzag.
- Clearest evidence: the same two bricks fail at the tip of a cantilever and
  complete over its support (see
  [Controlled comparisons](#controlled-comparisons)).

**B. Letting go breaks a joint below.**
- The press stores load in the new joint. When the fingers open, that load
  reaches the joint below, which can break although nothing visibly moves.
- Seen in:
  - the tree, 2x2 tower, column of ten, offset tower, lean 6 and leaning
    ladder;
  - the column pressed at 3 N and 5 N;
  - the house and the castle gate at the default 1 s release.
- Clearest evidence: the house completes when the gripper opens over 2 s
  instead of 1 s, while a shallower press does not help.

**E. The breakage solver struggles, then a joint breaks.**
- On the cross-bonded and spiral towers, the solver that computes joint loads
  failed to converge four times in a row.
- A 4-stud joint then broke, although its load had never been sampled above
  80% of capacity.
- This is a numerical weakness of the simulator, not a clear overload.

### Gripper and controller limits

**C. No room for the fingers.**
- The RG2's fingertips are about 11 mm thick and open outward.
- Table legs 2 studs (16 mm) apart leave no opening that frees the held brick
  without touching its neighbour, so the controller stops instead.
- Fix: grip the brick across its other axis, or design with wider gaps.

**D. A brick does not seat.**
- In the mixed tower, a brick slid slightly in the gripper at first contact
  and stopped on the studs, 1 mm above its seat.
- Fix: a deeper press, a small wiggle, or a re-grasp.

**F. A brick slips out of the grasp.**
- A 2x2 brick slipped from the fingers as the arm accelerated, and the
  controller did not notice until the press.
- It was seen once, in a small duck figure since removed from the library; the
  run stays in the [capture sweep](sweeps/2026-11-08-capture-sweep.summary.md).
- Fix: check the gripper width during transfer.

## Controlled comparisons

Each comparison changes one thing and keeps everything else the same.

**Where the load sits (cantilever).**

| Two 2x2 bricks pressed… | Result |
|---|---|
| at the free tip | fails: the column's base joint pries loose (A) |
| over the support | completes |

**How hard the robot presses (column of four 2x4 bricks).**

| Press force | Peak force | Result |
|---|---|---|
| 1 N (default) | 1.2 N | completes |
| 2 N | 2.2 N | completes |
| 3 N | 3.9 N | base joint breaks on the next release (B) |
| 5 N | 5.4 N | base joint breaks on a release (B) |

**How fast the gripper opens (house).**

| Setting | Result |
|---|---|
| 1 s release (default) | a wall joint breaks on a release (B) |
| 1 s release, shallower press (0.2 mm instead of 0.5 mm) | the same break |
| 2 s release | completes |
| Control: the column with bricks turned 90 degrees, 1 s release | completes, so turning the bricks is not the cause |

## What the simulator cannot tell us yet

- **The breaking moment is not recorded.** BrickSim breaks a joint inside the
  physics step, before any load is sampled, so some breaks look sudden.
- **Most breaks heal invisibly.** Most joint breaks re-form within a second,
  and the controller never sees them. The sweep summaries count them per run.
- **The solver often struggles.** Breakage-solver warnings appear in most runs,
  and most lasting breaks follow them.
- **Joint strength is unverified.** The capacity per stud contact comes from
  the BrickSim paper and has not been checked against real bricks under these
  loads.
- **Perfect perception.** Poses come from simulator ground truth, and pickup
  positions are known exactly.

## Proposed real-robot tests (not yet run)

| Mechanism | Test on the real UR5e |
|---|---|
| A | Build the cantilever pair; press at 1 N and 2 N with a force gauge. Does the lower joint lift? |
| B | Build the column and the house; release at 1 s and 2 s. Does the joint below lift when the gripper opens? |
| C | Find the smallest gap at which the RG2 can let go without touching the neighbour. |
| D | Does a real brick seat with the same press, or does it need a deeper press or a wiggle? |
| E | Build a quarter-turned 2x4 on a 2x4 (4 studs). Does it survive the release? |
