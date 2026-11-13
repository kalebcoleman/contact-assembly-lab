# Usage

How to build the project, run structures and sweeps, reproduce the published
results and develop it further. The overview is in the [README](../README.md).
Everything here runs in simulation; nothing drives a real robot.

## Requirements

- x86-64 Linux with glibc ≥ 2.35 (Ubuntu 22.04+).
- An NVIDIA driver that meets the
  [Isaac Sim 6.2 requirements](https://docs.isaacsim.omniverse.nvidia.com/6.2.0/installation/requirements.html#system-requirements).
- [`uv`](https://docs.astral.sh/uv/getting-started/installation/) and
  [`pixi`](https://pixi.prefix.dev/latest/installation/).
- The lab assets (UR5e with `tool0`, RG2 gripper, Vention bench) and an
  isaac-mcp (now twinsmith) checkout at commit `7e5de2c` or earlier; see
  [Lab assets](#lab-assets).
- A display for Kit, and ffmpeg for `scripts/make_media.sh`.

## Build

```bash
git clone https://github.com/kalebcoleman/contact-assembly-lab.git
cd contact-assembly-lab
export CONDA_OVERRIDE_GLIBC=2.39   # only on glibc < 2.39 hosts, e.g. Ubuntu 22.04
pixi run build-native
uv sync --locked
.venv/bin/python scripts/check_parity.py
```

[ISAACSIM_6.2_PORT.md](ISAACSIM_6.2_PORT.md) explains the glibc override, the
version changes and how the Isaac Sim SDK pins are regenerated.

### Lab assets

The UR5e model with its `tool0` frame, the RG2 gripper and the Vention bench
are not in this repository. They come from a separate asset store loaded
through the resolver `exts/ur5e-dt/ur5e_dt/asset_cache.py` of the public
isaac-mcp project, now [twinsmith](https://github.com/kalebcoleman/twinsmith).
twinsmith removed that file on 2026-11-13 (commit `8c1b231`), so check out
`7e5de2c` or earlier for these experiments. `ISAAC_MCP_ROOT` (default
`~/isaac-workspace/isaac-mcp`) and
`ISAAC_MCP_ASSET_PATH` (default `~/isaac-workspace/isaac-mcp-assets`) locate
them. Their hashes are pinned in
[`lab_assets_sha256.json`](../experiments/ur5e_lego/assets/lab_assets_sha256.json).
`scripts/check_parity.py` checks the checkout, the locked packages, the native
build and these assets. Details:
[experiments/ur5e_lego/README.md](../experiments/ur5e_lego/README.md).

## Build one structure

```bash
OMNI_KIT_ACCEPT_EULA=YES bash experiments/ur5e_assembly/run_loop.sh \
  --attempts 1 --config experiments/ur5e_structures/<name>.json
```

- The default config is `experiments/ur5e_structures/dog.json`.
- `--attempts` takes 1–5; each attempt is a fresh scene and the loop stops at
  the first failure.
- Console logs and outcomes go to `outputs/ur5e_assembly/<time>/`, per-step
  recordings to `outputs/ur5e_lego/`.

The structures are listed in
[experiments/ur5e_structures/](../experiments/ur5e_structures/README.md) and
the [catalog](STRUCTURES.md). How the controller handles each brick is in
[experiments/ur5e_assembly/README.md](../experiments/ur5e_assembly/README.md).

## Controller settings

Set as environment variables. The tunable ones (with a config key) can also be
set per structure; see [Per-structure settings](#per-structure-settings).

| Variable | Config key | Default | Effect |
|---|---|---|---|
| `ASSEMBLY_BREAKAGE` | | `1` | `0` disables breakage, so joints cannot break under load |
| `ASSEMBLY_GRIPPER_CONTACT` | | `fail` | `fail` stops the run at the first gripper contact with another brick; `log` records contacts and continues |
| `ASSEMBLY_REQUIRED_FORCE_N` | `required_force_n` | `1.0` | Press force (N) needed to form a connection |
| `ASSEMBLY_PRESS_DEPTH_M` | `press_depth_m` | `0.0005` | Press target below the seated pose (m) |
| `ASSEMBLY_PRESS_HOLD_S` | `press_hold_s` | `0.05` | Time (s) a connection must hold before release |
| `ASSEMBLY_FREEZE_ON_CONNECTION` | | `1` | Stop descending once the connection forms |
| `ASSEMBLY_RELEASE_RAMP_S` | `release_ramp_s` | `1.0` | Gripper opening time (s) |
| `ASSEMBLY_RELEASE_LIFT_M` | `release_lift_m` | `0.0` | Hold the tool this much higher (m) while the fingers open: ease off before letting go |
| `ASSEMBLY_TIP_CLEARANCE_M` | `tip_clearance_m` | `0.003` | Fingertip height above the held brick's bottom (m) |
| `ASSEMBLY_RELEASE_MARGIN_M` | `release_margin_m` | `0.002` | Distance (m) the opening fingers keep from a neighbouring brick |
| `ASSEMBLY_RELEASE_MIN_CLEARANCE_M` | `release_min_clearance_m` | `0.001` | Smallest gap (m) between fingers and held brick that counts as released |
| `ASSEMBLY_HOLD_S` | | `10` | Time (s) the finished structure stays on screen |
| `ASSEMBLY_CAPTURE_DIR` | | unset | Write video frames here; close-up stills go to `<dir>_stills` |
| `ASSEMBLY_CAPTURE_EVERY` | | `2` | App updates between captured frames |
| `ASSEMBLY_CONFIG` | | `dog.json` | Structure config; `run_loop.sh --config` sets it |

The older `DOG_*` names are still accepted as aliases.

### Per-structure settings

A structure config may carry a `controller` block with any of the config keys
above:

```json
"controller": {"release_ramp_s": 2.0, "release_lift_m": 0.0005}
```

Each value comes from the environment variable if set, else the `controller`
block, else the default. An unknown key fails the run. Every run prints the
values it used, so the console log records them:

```text
UR5e baseplate: controller settings {"required_force_n": 1.0, ...}
```

### Grasp offsets

By default the gripper closes over the brick's centre. A per-brick
`grasp_offsets_m` list (one `[x, y]` per brick, meters, in the brick's own
frame) moves the grip off-centre, for example over the part of a brick that
rests on its support (here, three bricks):

```json
"grasp_offsets_m": [[0.0, 0.0], [0.0, -0.004], [0.0, 0.0]]
```

### Fix-attempt variants

Variant configs for fix attempts live in
[experiments/ur5e_structures/attempts/](../experiments/ur5e_structures/attempts/).
Each names the structure it varies and how, so the catalog lists it under that
structure:

```json
"variant_of": "mixed_tower",
"variant": "grip over the supported part"
```

## Sweeps and reruns

A sweep definition lists runs (label, config, environment overrides) plus a
sweep-wide environment and the controller commit. `run_sweep.py` runs every
entry without a run id and writes the id, video and stills back;
`summarize_sweep.py` writes the summary. Details and how to read a summary:
[sweeps/README.md](../experiments/ur5e_structures/sweeps/README.md).

```bash
OMNI_KIT_ACCEPT_EULA=YES python3 -m experiments.ur5e_structures.run_sweep \
  experiments/ur5e_structures/sweeps/<name>.json --capture
python3 -m experiments.ur5e_structures.summarize_sweep \
  experiments/ur5e_structures/sweeps/<name>.json
.venv/bin/python -m experiments.ur5e_structures.record_trials   # add runs to trials.json
```

`--rerun <copy>.json` runs a committed sweep into a fresh copy instead of
editing it.

## Reproducing the results

The results were produced on this stack:

| Component | Version |
|---|---|
| OS | Ubuntu 22.04.5 LTS (glibc 2.35, built with the glibc 2.39 sysroot) |
| GPU, driver | NVIDIA RTX PRO 6000 Blackwell Max-Q, 595.99.02 |
| Isaac Sim | 6.2.0.0 (Kit 110.4.0, omni.physx 110.4.4, PhysX SDK 5.9.2, OpenUSD 25.11) |
| Python | 3.12 with torch 2.11.0+cu130, locked in `uv.lock` |
| Media | ffmpeg (for `scripts/make_media.sh`) |

1. [Build](#build) and pass `scripts/check_parity.py`.
2. Check out the controller commit the sweep names, then re-run it into a
   fresh copy:

   ```bash
   OMNI_KIT_ACCEPT_EULA=YES python3 -m experiments.ur5e_structures.run_sweep \
     experiments/ur5e_structures/sweeps/2026-11-08-showcase-sweep.json \
     --rerun experiments/ur5e_structures/sweeps/my-rerun.json --capture
   ```

3. Summarize the copy and compare it with the committed
   [summary](../experiments/ur5e_structures/sweeps/2026-11-08-showcase-sweep.summary.md):

   ```bash
   python3 -m experiments.ur5e_structures.summarize_sweep \
     experiments/ur5e_structures/sweeps/my-rerun.json
   ```

**Determinism.** On the machine above, repeated runs of the same structure
matched exactly in outcome, joint breaks, solver warnings and the simulator
step of every logged joint event. On other GPUs and drivers, expect the same
outcomes but not necessarily bit-identical steps.

## Media

`scripts/make_media.sh` turns captured runs into the published media, then
the catalog is regenerated:

```bash
scripts/make_media.sh .cache/videos/my-rerun/bridge.mp4 docs/media/bridge
scripts/make_media.sh --closeup \
  .cache/videos/my-rerun/bridge_closeup_three_quarter.png docs/media/bridge_closeup.jpg
.venv/bin/python -m experiments.ur5e_structures.catalog
```

## Case suite

Thirteen single-case experiments (C01–C13), each with a prediction written
before it runs; see
[ur5e-cases.md](../experiments/ur5e_lego/docs/ur5e-cases.md).

```bash
.venv/bin/python experiments/ur5e_lego/scripts/run_ur5e_cases.py
.venv/bin/python experiments/ur5e_lego/scripts/run_ur5e_cases.py --case C01 C05
```

## Dashboard

```bash
python3 experiments/ur5e_dashboard/server.py
```

Open http://127.0.0.1:8765. The read-only viewer shows recorded runs with
their sweep evidence, the structures with their results at standard settings
(from `docs/structures/index.json`), and the case suite; Isaac Sim need not be
running. The first load of the run list parses every recording under
`outputs/ur5e_lego/` (about 21 GB here) and took several minutes. Screenshots
are in the [README](../README.md#dashboard). See
[experiments/ur5e_dashboard/README.md](../experiments/ur5e_dashboard/README.md).

## Development

```bash
pixi run build-native          # rebuild after C++ changes
pixi run test-native-release   # and test-native-debug
pixi run format-native
.venv/bin/ruff check           # not `uv run`: it would rebuild the native module
.venv/bin/python -m pytest experiments
.venv/bin/python -m experiments.ur5e_structures.specs     # regenerate structure configs
.venv/bin/python -m experiments.ur5e_structures.catalog   # regenerate docs/STRUCTURES.md
```

Coding rules are in [AGENTS.md](../AGENTS.md).

## Repository layout

| Path | Contents |
|---|---|
| `native/` | C++26 native extension: brick connection and breakage physics, PhysX 5.9.2 patches, tests |
| `python/bricksim/` | Isaac Sim extension, launcher and Python API |
| `experiments/ur5e_assembly/` | UR5e assembly controller and fresh-scene attempt loop |
| `experiments/ur5e_structures/` | Structure configs, fix-attempt variants, sweeps and summaries, failure analysis |
| `experiments/ur5e_lego/` | UR5e scene, recording format, single-brick experiments, case suite C01–C13 |
| `experiments/ur5e_dashboard/` | Results dashboard |
| `docs/STRUCTURES.md` | Catalog: design, picture, result and video of every structure |
| `docs/ISAACSIM_6.2_PORT.md` | Isaac Sim 5.1 → 6.2 changes and rebuild notes |
| `docs/EVALUATION_PRACTICES.md` | Evaluation practices to carry over to the Jenga work |
| `scripts/` | Native build, Isaac Sim pin resolver, parity check, media script |
