# contact-assembly-lab

[![Isaac Sim 6.2](https://img.shields.io/badge/Isaac%20Sim-6.2-76B900?logo=nvidia&logoColor=white)](https://docs.isaacsim.omniverse.nvidia.com/6.2.0/index.html)
[![Python 3.12](https://img.shields.io/badge/python-3.12-3776AB?logo=python&logoColor=white)](https://docs.python.org/3.12/)
[![MIT License](https://img.shields.io/badge/license-MIT-yellow.svg)](LICENSE)

Research on assembling complex brick structures with a UR5e (RG2 gripper,
Vention bench) in Isaac Sim 6.2. The simulator is a port of BrickSim from Isaac
Sim 5.1 / Python 3.11 to Isaac Sim 6.2.0.0 / Python 3.12.

**Credit.** The brick physics (connection and breakage model), the C++ native
extension, the simulator UI and the Isaac Sim 6.0 groundwork of this port come
from
[BrickSim](https://github.com/intelligent-control-lab/BrickSim) by Haowei Wen,
Ruixuan Liu, Weiyi Piao, Siyu Li and Changliu Liu (Intelligent Control Lab,
Carnegie Mellon University), released under the MIT License. Please cite it
([below](#citation)) if you use this work.

All results are simulation, judged by simulator ground truth, unless a document
says otherwise.

## Demos

UR5e with an RG2 gripper building brick structures in Isaac Sim 6.2, with
BrickSim's full joint-strength (breakage) model on. These are simulation
recordings rendered in the simulator at 1080p, 30 frames per second of
simulated time. The GIFs play 16× faster and the MP4s 8×. Poses come from
simulator ground truth, and the final pose is held at the end of each video.

| Dog, 10 bricks: completed | Human figure, 8 bricks: completed |
|---|---|
| ![Dog build](docs/media/dog_breakage_on.gif) | ![Human build](docs/media/human_breakage_on.gif) |
| [MP4](docs/media/dog_breakage_on.mp4) · [final pose](docs/media/dog_breakage_on_final.png) | [MP4](docs/media/human_breakage_on.mp4) · [final pose](docs/media/human_breakage_on_final.png) |

**Figures.** Each still links to its video.

| Robot: completed | Cat: completed | Tree: base joint lost | Giraffe: base joint lost |
|---|---|---|---|
| [![Robot](docs/media/robot_final.png)](docs/media/robot.mp4) | [![Cat](docs/media/cat_final.png)](docs/media/cat.mp4) | [![Tree](docs/media/tree_final.png)](docs/media/tree.mp4) | [![Giraffe](docs/media/giraffe_final.png)](docs/media/giraffe.mp4) |

The tree still looks whole, but the joint of its bottom 2×2 to the baseplate
broke at the last release.

**Breaking it on purpose.** Each break test pushes one failure mechanism. In
the cantilever, a 2×6 rests by one end on a column of 2×2 bricks. Pressing the
last 2×2 onto its free tip overloads the joint below, and the cantilever tips
over.

![Cantilever failure](docs/media/cantilever_failure.gif)

| Load at the tip: fails | Same load over the support: completes | Column pressed at 3 N: base joint lost | Leaning ladder: collapses | Ten 2×2 bricks: base joint lost |
|---|---|---|---|---|
| [![Tip load](docs/media/cantilever_tip2_final.png)](docs/media/cantilever_tip2.mp4) | [![Root load](docs/media/cantilever_root2_final.png)](docs/media/cantilever_root2.mp4) | [![3 N press](docs/media/column_press_3N_final.png)](docs/media/column_press_3N.mp4) | [![Lean ladder](docs/media/lean_ladder_final.png)](docs/media/lean_ladder.mp4) | [![2x2 tower](docs/media/tower_2x2_final.png)](docs/media/tower_2x2.mp4) |

The failures are documented as test cases in
[FAILURES.md](experiments/ur5e_structures/FAILURES.md). Each is broken down
into:
- what stopped the controller;
- what the breakage model did (lasting or transient joint breaks);
- whether the breakage solver was struggling numerically.

Every run links to its configuration, settings and video in the
[sweep summaries](experiments/ur5e_structures/sweeps/README.md). They are
simulation results only.

The [dashboard](experiments/ur5e_dashboard/README.md)'s **Structures** view shows
each structure layer by layer, every trial in simulation and on the robot, and
the latest result per setting:

![Dashboard structures view](docs/media/dashboard_structures.png)

## Roadmap (planned)

The main research direction is Jenga with MPC and RL, developed in separate
projects. This repository remains the demo and a supporting contact-physics and
evaluation testbed. [docs/EVALUATION_PRACTICES.md](docs/EVALUATION_PRACTICES.md)
lists the telemetry and evaluation practices from these sweeps that carry over.

1. Build more complex structures in simulation and document each run in the
   dashboard.
2. Build the same structures on the real UR5e and compare what fails against
   simulation.
3. Close the telemetry gaps the sweeps found: log the breaking solve and record
   joint events in the recording.

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

[docs/ISAACSIM_6.2_PORT.md](docs/ISAACSIM_6.2_PORT.md) explains the glibc
override, the version changes (Kit 110.4, omni.physx 110.4.4, PhysX SDK 5.9.2,
torch 2.11 cu130) and how the Isaac Sim SDK pins are regenerated.

The UR5e experiments also need the lab assets (UR5e with `tool0`, RG2 gripper,
Vention bench) and an `isaac-mcp` checkout; see
[experiments/ur5e_lego/README.md](experiments/ur5e_lego/README.md).

## Build a structure

```bash
OMNI_KIT_ACCEPT_EULA=YES bash experiments/ur5e_dog/run_loop.sh \
  --attempts 1 --config experiments/ur5e_structures/column.json
```

Each attempt starts a fresh scene. Console logs and outcomes go to
`outputs/ur5e_dog/<time>/`, per-step recordings to `outputs/ur5e_lego/`.
`--attempts` takes 1–5; the loop stops at the first failure. Structures are in
[experiments/ur5e_structures/](experiments/ur5e_structures/README.md); the
ten-piece dog (the default config) is in
[experiments/ur5e_dog/](experiments/ur5e_dog/README.md), with results in
[RESULTS.md](experiments/ur5e_dog/RESULTS.md).

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

## Case suite

Thirteen single-case experiments (C01–C13), each with a prediction written
before it runs; see
[experiments/ur5e_lego/docs/ur5e-cases.md](experiments/ur5e_lego/docs/ur5e-cases.md).

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
[experiments/ur5e_dashboard/README.md](experiments/ur5e_dashboard/README.md).

## Development

```bash
pixi run build-native          # rebuild after C++ changes
pixi run test-native-release   # and test-native-debug
uv run ruff check
python3 -m unittest experiments.ur5e_dog.test_geometry
python3 -m unittest discover -s experiments/ur5e_dashboard -p 'test_*.py'
python3 -m unittest experiments.ur5e_structures.test_summarize_sweep
```

Coding rules are in [AGENTS.md](AGENTS.md).

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
| `docs/EVALUATION_PRACTICES.md` | Telemetry and evaluation practices for the Jenga work |
| `scripts/` | Native build, Isaac Sim pin resolver, environment parity check |

## Citation

```
@article{wen2026bricksim,
    title = {BrickSim: A Physics-Based Simulator for Manipulating Interlocking Brick Assemblies},
    author = {Wen, Haowei and Liu, Ruixuan and Piao, Weiyi and Li, Siyu and Liu, Changliu},
    journal = {arXiv:2603.16853},
    year = {2026},
    eprint = {2603.16853},
    archiveprefix = {arXiv},
    primaryclass = {cs.RO},
    url = {https://arxiv.org/abs/2603.16853}
}
```

## License

MIT, see [LICENSE](LICENSE). The original BrickSim copyright notice is retained
there; changes in this repository are released under the same license.
