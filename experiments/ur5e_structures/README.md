# Store-brick structures

Structures built only from 2x4 bricks (some rotated to 4x2), run with the dog
controller: `bash experiments/ur5e_dog/run_loop.sh --attempts 1 --config experiments/ur5e_structures/<name>.json`.
`python3 -m experiments.ur5e_structures.specs` regenerates and validates the JSON.

Design rule: same-layer bricks keep at least a 2-stud (16 mm) gap, the spacing the
dog showed the gripper can place beside. Each brick rests on one brick below with at
least 4 studs of contact and may overhang toward a neighbor. Touching same-layer
bricks were dropped from the first draft.

## Trials

Every attempt at a structure, in simulation or on the real UR5e, is one entry in
[trials.json](trials.json); the dashboard (`python3 experiments/ur5e_dashboard/server.py`,
**Structures** filter) shows each structure's layers and trials, and an overview of
the latest result per setting.

After simulation runs, add them from their recordings:

    .venv/bin/python -m experiments.ur5e_structures.record_trials

Add a real-robot trial by hand, with the same fields:

```json
{
  "structure": "tower",
  "kind": "real",
  "platform": "UR5e (lab)",
  "date_utc": "2026-11-10T15:00:00+00:00",
  "breakage": null,
  "bricks_total": 6,
  "bricks_connected": 5,
  "outcome": "failed",
  "failure": "Brick 6 did not seat; brick 4 lifted with it",
  "recording": null,
  "notes": "Operator-fed bricks; video: <path or link>"
}
```

`bricks_connected` counts bricks still connected at the end, so a joint that broke
after forming is not counted. `outcome` is `completed` when every brick connected and the run ended cleanly,
otherwise `failed` (or `incomplete`/`timeout` for simulation). `breakage` is the
simulator's breakage model (`true`/`false`); use `null` for real trials.

## Results on Isaac Sim 5.1 (simulation, one run each)

| Structure | Bricks | Connections | Outcome |
|---|---|---|---|
| tower | 6 | 6/6 | completed, clean exit |
| l_corner | 4 | 4/4 | completed |
| stairs | 8 | 8/8 | completed |

One run per structure, default pickup grid, yaw 0. No retries exist, so none were used.
Peak contact force per press was 1.0–1.5 N. Poses and snap/weld connections are
simulator ground truth with breakage disabled; this is not perception or physical
insertion. Pickup positions are a placeholder grid, not planned.

## Screenshots

Contact sheets (one frame every 5–8 s) of the plate region. The viewport framing
differed from the dog runs and clips the plate at the screen edge. Full recordings
stay local.

![Tower](media/tower_progress.png)
![L corner](media/l_corner_progress.png)
![Stairs](media/stairs_progress.png)
