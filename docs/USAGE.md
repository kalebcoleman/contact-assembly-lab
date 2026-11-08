# Using contact-assembly-lab

How to build the project, run structures and sweeps, reproduce the published
results and develop it further. The project overview is in the
[README](../README.md).

## Requirements

- x86-64 Linux with glibc ≥ 2.35 (Ubuntu 22.04+).
- An NVIDIA driver that meets the
  [Isaac Sim 6.2 requirements](https://docs.isaacsim.omniverse.nvidia.com/6.2.0/installation/requirements.html#system-requirements).
- [`uv`](https://docs.astral.sh/uv/getting-started/installation/) and
  [`pixi`](https://pixi.prefix.dev/latest/installation/).

## Build

```bash
git clone https://github.com/kalebcoleman/contact-assembly-lab.git
cd contact-assembly-lab
export CONDA_OVERRIDE_GLIBC=2.39   # only on glibc < 2.39 hosts, e.g. Ubuntu 22.04
pixi run build-native
uv sync --locked
```

[docs/ISAACSIM_6.2_PORT.md](ISAACSIM_6.2_PORT.md) explains the glibc
override, the version changes (Kit 110.4, omni.physx 110.4.4, PhysX SDK 5.9.2,
torch 2.11 cu130) and how the Isaac Sim SDK pins are regenerated.

The UR5e experiments also need the lab assets (UR5e with `tool0`, RG2 gripper,
Vention bench) and an `isaac-mcp` checkout; see
[experiments/ur5e_lego/README.md](../experiments/ur5e_lego/README.md).

## Build a structure

```bash
OMNI_KIT_ACCEPT_EULA=YES bash experiments/ur5e_dog/run_loop.sh \
  --attempts 1 --config experiments/ur5e_structures/column.json
```

Each attempt starts a fresh scene. Console logs and outcomes go to
`outputs/ur5e_dog/<time>/`, per-step recordings to `outputs/ur5e_lego/`.
`--attempts` takes 1–5; the loop stops at the first failure. Structures are in
[experiments/ur5e_structures/](../experiments/ur5e_structures/README.md); the
ten-piece dog (the default config) is in
[experiments/ur5e_dog/](../experiments/ur5e_dog/README.md), with results in
[RESULTS.md](../experiments/ur5e_dog/RESULTS.md).

Controller settings (environment variables, read in
`experiments/ur5e_dog/controller.py` and `run.py`):

| Variable | Default | Effect |
|---|---|---|
| `DOG_BREAKAGE` | `1` | `0` disables breakage, so joints cannot break under load |
| `DOG_REQUIRED_FORCE_N` | `1.0` | Press force (N) needed to form a connection |
| `DOG_PRESS_DEPTH_M` | `0.0005` | Press target below the seated pose (m) |
| `DOG_PRESS_HOLD_S` | `0.05` | Time (s) a connection must hold before release |
| `DOG_FREEZE_ON_CONNECTION` | `1` | Stop descending once the connection forms |
| `DOG_RELEASE_RAMP_S` | `1.0` | Gripper opening time (s) |
| `DOG_HOLD_S` | `10` | Time (s) the finished structure stays on screen |

## Reproducing the results

The results were produced on this stack:

| Component | Version |
|---|---|
| OS | Ubuntu 22.04.5 LTS (glibc 2.35, built with the glibc 2.39 sysroot) |
| GPU, driver | NVIDIA RTX PRO 6000 Blackwell Max-Q, 595.99.02 |
| Isaac Sim | 6.2.0.0 (Kit 110.4.0, omni.physx 110.4.4, PhysX SDK 5.9.2, OpenUSD 25.11) |
| Python | 3.12 with torch 2.11.0+cu130, locked in `uv.lock` |
| Media | ffmpeg (for `scripts/make_media.sh`) |

**Lab assets.** The UR5e model with its `tool0` frame, the RG2 gripper and the
Vention bench are not in this repository. They come from a separate asset store
that is loaded through the public
[isaac-mcp](https://github.com/kalebcoleman/isaac-mcp) resolver; see
[experiments/ur5e_lego/README.md](../experiments/ur5e_lego/README.md). Their
hashes are pinned in
[`assets/lab_assets_sha256.json`](../experiments/ur5e_lego/assets/lab_assets_sha256.json).
`scripts/check_parity.py` checks the checkout, the locked packages, the native
build and these assets.

1. Build (see [Build](#build)), then check the setup:

   ```bash
   .venv/bin/python scripts/check_parity.py
   ```

2. Re-run a committed sweep into a fresh copy. Run ids, videos and close-up
   stills are written as the runs finish. Kit needs a display.

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

4. Make the media and regenerate the catalog:

   ```bash
   scripts/make_media.sh .cache/videos/my-rerun/bridge.mp4 docs/media/bridge
   scripts/make_media.sh --closeup \
     .cache/videos/my-rerun/bridge_closeup_three_quarter.png docs/media/bridge_closeup.jpg
   .venv/bin/python -m experiments.ur5e_structures.catalog
   ```

**Determinism.** On the machine above, repeated runs of the same structure
matched exactly:
- outcome;
- joint breaks;
- solver warnings;
- the simulator step of every logged joint event.

Expect the same outcomes on other GPUs and drivers, but not necessarily
bit-identical steps. Each sweep records the controller commit it ran.

## Case suite

Thirteen single-case experiments (C01–C13), each with a prediction written
before it runs; see
[experiments/ur5e_lego/docs/ur5e-cases.md](../experiments/ur5e_lego/docs/ur5e-cases.md).

```bash
.venv/bin/python experiments/ur5e_lego/scripts/run_ur5e_cases.py
.venv/bin/python experiments/ur5e_lego/scripts/run_ur5e_cases.py --case C01 C05
```

## Dashboard

```bash
python3 experiments/ur5e_dashboard/server.py
```

Open http://127.0.0.1:8765. The read-only viewer lists recorded runs and the
case suite; Isaac Sim need not be running. See
[experiments/ur5e_dashboard/README.md](../experiments/ur5e_dashboard/README.md).

## Development

```bash
pixi run build-native          # rebuild after C++ changes
pixi run test-native-release   # and test-native-debug
.venv/bin/ruff check            # not `uv run`: it would rebuild the native module
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
| `experiments/ur5e_dog/` | UR5e assembly controller and fresh-scene attempt loop |
| `experiments/ur5e_structures/` | Structure specs (JSON), sweeps and their summaries, failure catalogue |
| `experiments/ur5e_lego/` | UR5e scene, recording format, case suite C01–C13 |
| `experiments/ur5e_dashboard/` | Results dashboard |
| `docs/ISAACSIM_6.2_PORT.md` | Isaac Sim 5.1 → 6.2 changes and rebuild notes |
| `docs/STRUCTURES.md` | Structure catalog: design, picture, result and video of every structure |
| `docs/EVALUATION_PRACTICES.md` | Telemetry and evaluation practices for the Jenga work |
| `scripts/` | Native build, Isaac Sim pin resolver, environment parity check |

