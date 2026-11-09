# Failure analysis (simulation)

Every structure was built by the UR5e in Isaac Sim 6.2 with BrickSim's
joint-strength model on.

**Controller defaults** are:
- breakage on;
- a 1 N press, 0.5 mm below the seat;
- a 1 s gripper release;
- the brick gripped at its middle;
- gripper contacts logged rather than fatal.

When a structure failed at the defaults, it was tried again with other
settings, grips or small design changes. Anything that made it build is
written into its config, so it now builds with its own settings and no
special commands. See [docs/USAGE.md](../../docs/USAGE.md) for how a config
carries settings.

The simulation is deterministic: repeating a run gives the same result. Every
run, with the settings it used, is in the [sweep summaries](sweeps/README.md);
every structure is pictured, with each attempt listed, in the
[structure catalog](../../docs/STRUCTURES.md). Nothing here ran on hardware.

## What we tested, and what fixed it

Generated from the sweep summaries by `catalog.py`. "Other attempts" counts the
runs at any other setting, grip or design variant.

<!-- results:start -->
| Structure | What it tests | At the controller defaults | What it needs | With it | Other attempts |
|---|---|---|---|---|---|
| [Dog](../../docs/STRUCTURES.md#dog) | wide bricks bridging legs; ten-brick figure | 3 of 3 built | nothing | — | 0 |
| [Arch bridge](../../docs/STRUCTURES.md#bridge) | a deck landing on two piers (corbel arch) | 1 of 1 built | nothing | — | 0 |
| [House](../../docs/STRUCTURES.md#house) | a lintel over a doorway; stepped roof | 0 of 1 built | ease off 0.5 mm before letting go | 2 of 2 built | 3 |
| [Log cabin](../../docs/STRUCTURES.md#log_cabin) | courses alternating direction; interlocking corners | 1 of 1 built | nothing | — | 0 |
| [Steam locomotive](../../docs/STRUCTURES.md#locomotive) | a chassis resting on three wheels | 0 of 1 built | 0.5 s gripper release | 2 of 2 built | 6 |
| [Lighthouse](../../docs/STRUCTURES.md#lighthouse) | a seven-layer tower on a wide base | 1 of 1 built | nothing | — | 0 |
| [Castle gate](../../docs/STRUCTURES.md#castle_gate) | a lintel over a gate; battlements | 0 of 1 built | ease off 0.5 mm before letting go, 0.5 s gripper release | 2 of 2 built | 4 |
| [Tree](../../docs/STRUCTURES.md#tree) | a crown on a 2x2 trunk (4-stud joints) | 0 of 2 built | ease off 0.5 mm before letting go | 2 of 2 built | 2 |
| [Table](../../docs/STRUCTURES.md#table) | four legs, then tops spanning them | 0 of 2 built | not buildable yet: no room for the RG2 fingers between legs 2 studs apart (C); the trestle table builds | — | 1 |
| [Table, grip-aware](../../docs/STRUCTURES.md#table_grip) | the table with grips chosen for room | 0 of 1 built | not buildable yet: a 2x8 gripped end to end slips out of the fingers | — | 0 |
| [Table, wide gaps](../../docs/STRUCTURES.md#table_wide) | 4-stud gaps on both axes | 0 of 1 built | not buildable yet: the 4-stud leg joints break while the tops go on (B) | — | 2 |
| [Trestle table](../../docs/STRUCTURES.md#trestle_table) | slab legs gripped end to end | 1 of 1 built | nothing | — | 0 |
| [Mixed tower](../../docs/STRUCTURES.md#mixed_tower) | three brick sizes with offsets | 0 of 2 built | grip half-supported bricks over their support | 1 of 1 built | 4 |
| [Cross-bonded tower](../../docs/STRUCTURES.md#cross_tower) | alternating quarter turns (4-stud overlaps) | 0 of 2 built | 0.5 s gripper release | 2 of 2 built | 2 |
| [Spiral tower](../../docs/STRUCTURES.md#spiral_tower) | repeated quarter turns (4-stud overlaps) | 0 of 2 built | not buildable yet: its quarter-turned 4-stud joints break on release (E) | — | 2 |
| [L corner](../../docs/STRUCTURES.md#l_corner) | a corner brick joining two posts | 0 of 2 built | 0.5 s gripper release | 2 of 2 built | 2 |
| [Offset tower](../../docs/STRUCTURES.md#tower) | alternating directions with 1-stud shifts | 0 of 2 built | ease off 0.5 mm before letting go | 2 of 2 built | 2 |
| [Cantilever](../../docs/STRUCTURES.md#cantilever) | a press on a cantilever tip | 0 of 3 built | not buildable yet: the press on the overhang levers the column (A); needs building as a sub-assembly | — | 4 |
| [Cantilever, two bricks at the tip](../../docs/STRUCTURES.md#cantilever_tip2) | two bricks at a cantilever tip | 0 of 2 built | not buildable yet: the press on the overhang levers the column (A); needs building as a sub-assembly | — | 3 |
| [Cantilever, two bricks over the support (control)](../../docs/STRUCTURES.md#cantilever_root2) | the same bricks over the support (control) | 2 of 2 built | nothing | — | 0 |
| [Leaning ladder](../../docs/STRUCTURES.md#lean_ladder) | a lean that grows every layer | 0 of 2 built | 0.5 s gripper release | 2 of 2 built | 2 |
| [2x2 tower](../../docs/STRUCTURES.md#tower_2x2) | ten 4-stud joints | 0 of 2 built | not buildable yet: ten stacked 4-stud joints; the base breaks on a release (B) | — | 4 |
| [Lean 6](../../docs/STRUCTURES.md#lean_6) | 2-stud shifts (4-stud joints) | 0 of 2 built | not buildable yet: 2-stud shifts leave 4-stud joints that break on release (B) | — | 4 |
| [Zigzag 6](../../docs/STRUCTURES.md#zigzag_6) | shear at every joint | 0 of 2 built | 0.5 s gripper release | 2 of 2 built | 2 |
| [Column of ten](../../docs/STRUCTURES.md#column_10) | load on the base growing with height | 0 of 2 built | 0.5 s gripper release | 2 of 2 built | 2 |
| [Column, turned 90 degrees](../../docs/STRUCTURES.md#column_turned) | the column with bricks turned 90 degrees | 2 of 2 built | nothing | — | 0 |
| [Single brick](../../docs/STRUCTURES.md#single) | one brick (sanity check) | 2 of 2 built | nothing | — | 0 |
| [Column](../../docs/STRUCTURES.md#column) | aligned 8-stud joints | 3 of 3 built | nothing | — | 3 |
| [Stairs](../../docs/STRUCTURES.md#stairs) | mixed sizes stepping up | 2 of 2 built | nothing | — | 0 |
<!-- results:end -->

## What fixed failures

**1. Ease off before letting go.**
- After the press, the arm is still pushing down when the fingers start to
  open, and that stored push loads the joint below.
- Holding the tool 0.5 mm higher while the fingers open removes the push.
- It fixed the tree, the offset tower and the house.

**2. Let go faster.**
- Opening the gripper over 0.5 s instead of 1 s lets go before the load builds
  up in the joint below.
- It fixed the column of ten, the cross-bonded tower, zigzag, the leaning
  ladder, the L corner and the steam locomotive.
- The castle gate needs both fixes together.
- The opposite, a slower 2 s release, made most structures worse; it fixed
  only the house.

**3. Press where the brick is supported.**
- A 2x4 resting on a 2x2 is half unsupported. Gripped and pressed at its
  middle, it tips and never seats.
- Gripping it 8 mm toward its support, so the press goes straight down,
  fixed the mixed tower.
- A 4 mm shift was not enough.

**4. Grip so the fingers have room.**
- The RG2 fingertips are about 11 mm thick and open outward, so they need
  room beside the brick.
- Gripping a 2x4 end to end, by its short faces, keeps the fingers out of a
  narrow gap. The trestle table builds this way.
- Gripping a 2x8 end to end does not hold: it slipped out during the lift.

**5. Change the design slightly.**
- The castle gate also builds with its battlements over the towers only,
  without the one over the middle of the lintel.
- The steam locomotive's first design, with a two-brick cab and a two-brick
  smokestack, never built: every variant lost the cab's joint to the
  chassis on a release (B). With a one-brick cab under the roof and a
  one-brick smokestack it builds, with the faster release (fix 2).

## What still does not build

Each of these failed at the defaults and with every fix that applied. They
are documented results, not dead ends.

- **Table (original):** the legs are 2 studs apart on both axes, so the last
  leg has no side where a finger fits. This is a gripper limit.
- **Table, wide gaps:** the fingers fit, but the legs' 4-stud joints break
  while the tops go on. The trestle table builds instead.
- **Spiral tower, 2x2 tower, lean 6:** all rest on 4-stud joints. In this
  model those break on a release however the gripper lets go.
- **Cantilever, and two bricks at the tip:** pressing on the overhang levers
  the column below. The fix is to build the top as a sub-assembly first
  (attach the load to the 2x6, then place the pair); that needs controller
  support for moving a built part and is future work.

<a id="mechanisms"></a>

## How builds fail

The letters in the catalog refer to these mechanisms.

- **A. Pressing a brick breaks a joint below.** Pushing a new brick down loads
  everything under it; joints with only 4 studs, or carrying an overhang,
  give way.
- **B. Letting go breaks a joint below.** The press stores load in the new
  joint, and opening the fingers releases it into the joint below. Nothing
  visibly moves. Fixes 1 and 2 address this.
- **C. No room for the fingers.** The gripper cannot open without touching a
  neighbour, so the controller stops. Fix 4 addresses this.
- **D. A brick does not seat.** It tips on the studs. Fix 3 addresses this.
- **E. The breakage solver struggles, then a joint breaks.** A numerical
  weakness of the simulator on 4-stud quarter-turn joints. The fast release
  avoids it on the cross-bonded tower but not on the spiral tower.
- **F. A brick slips out of the grasp.** Seen once, in a small duck figure
  since removed from the library. A gripper-width check during transfer would
  catch it.

## Controlled comparisons

Each comparison changes one thing and keeps everything else the same.

**Where the load sits (cantilever, two 2x2 bricks).**

| Pressed… | Result |
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

**How the gripper lets go (house).**

| Setting | Result |
|---|---|
| 1 s release (default) | a wall joint breaks on a release (B) |
| shallower press (0.2 mm) | the same break |
| 2 s release | completes |
| 0.5 s release | completes |
| ease off 0.5 mm, 1 s release | completes (the house's setting) |

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

| Question | Test on the real UR5e |
|---|---|
| Do the release fixes matter on real bricks? | Build the column of ten and the tree with each release setting; does the base lift when the gripper opens? |
| Does the press lever break real cantilevers? | Build the cantilever pair; press at 1 N and 2 N with a force gauge. |
| How much room do the fingers need? | Find the smallest gap at which the RG2 can let go without touching the neighbour. |
| Does pressing over the support seat real bricks? | Build the mixed tower with centred and off-centre grips. |
| Are 4-stud quarter-turn joints really this weak? | Build a quarter-turned 2x4 on a 2x4 (4 studs); does it survive the release? |
