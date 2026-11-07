<div align="center">

# contact-assembly-lab

### UR5e brick-assembly experiments on Isaac Sim 6.2

<p>
  <a href="https://docs.isaacsim.omniverse.nvidia.com/6.2.0/index.html"><img src="https://img.shields.io/badge/Isaac%20Sim-6.2-76B900?logo=nvidia&amp;logoColor=white" alt="Isaac Sim 6.2"></a>
  <a href="https://docs.python.org/3.12/"><img src="https://img.shields.io/badge/python-3.12-3776AB?logo=python&amp;logoColor=white" alt="Python 3.12"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-yellow.svg" alt="MIT License"></a>
  <a href="https://arxiv.org/abs/2603.16853"><img src="https://img.shields.io/badge/built%20on-BrickSim-b31b1b.svg?logo=arxiv" alt="Built on BrickSim"></a>
</p>

</div>

> **Built on BrickSim.** This repository is a derivative of
> [BrickSim](https://github.com/intelligent-control-lab/BrickSim) by Haowei Wen,
> Ruixuan Liu, Weiyi Piao, Siyu Li and Changliu Liu (Intelligent Control Lab,
> Carnegie Mellon University). The brick physics, connection model, breakage
> solver, native extension and simulator UI are their work, released under the
> MIT License (see [LICENSE](LICENSE), copyright retained). This repository adds
> the following:
> - a port to Isaac Sim 6.2 / Python 3.12;
> - UR5e (RG2 gripper, Vention bench) assembly experiments and structure test cases;
> - a results dashboard.
>
> Please cite BrickSim (below) if you use this work.

## What is here

| Path | Purpose |
|---|---|
| `native/` | C++26 native extension (from BrickSim; PhysX 5.9.2 offsets for Isaac Sim 6.2) |
| `python/bricksim/` | Isaac Sim extension and Python API (from BrickSim) |
| `experiments/ur5e_dog/` | UR5e assembly controller and fresh-scene attempt loop |
| `experiments/ur5e_structures/` | Structure test cases (JSON) built from 2×4 bricks |
| `experiments/ur5e_lego/` | UR5e scene, recording format, single-case experiments and test-case suite |
| `experiments/ur5e_dashboard/` | Read-only browser dashboard for recorded runs |
| `docs/ISAACSIM_6.2_PORT.md` | What the Isaac Sim 5.1 → 6.2 move changed, and how to rebuild |
| `demos/` | BrickSim demos |

All results in this repository are simulation results, judged by simulator
ground truth, unless a document says otherwise.

## Setup

Requirements:
- x86-64 Linux with glibc ≥ 2.35 (Ubuntu 22.04+).
- An NVIDIA driver that meets the
  [Isaac Sim 6.2 requirements](https://docs.isaacsim.omniverse.nvidia.com/6.2.0/installation/requirements.html#system-requirements).
- [`uv`](https://docs.astral.sh/uv/getting-started/installation/) and
  [`pixi`](https://pixi.prefix.dev/latest/installation/).

The native extension has no prebuilt binary for this port, so build it from
source:

```bash
git clone https://github.com/kalebcoleman/contact-assembly-lab.git
cd contact-assembly-lab
export CONDA_OVERRIDE_GLIBC=2.39   # only on glibc < 2.39 hosts, e.g. Ubuntu 22.04
pixi run build-native
uv sync --locked
```

See [docs/ISAACSIM_6.2_PORT.md](docs/ISAACSIM_6.2_PORT.md) for the following:
- why the glibc override is needed;
- how to keep pixi, caches and build output inside the checkout;
- how the Isaac Sim SDK pins were derived.

The UR5e experiments also need the lab assets (UR5e with `tool0`, RG2 gripper,
Vention bench) and an `isaac-mcp` checkout; see
[experiments/ur5e_lego/README.md](experiments/ur5e_lego/README.md).

## Run

```bash
# One fresh-scene assembly of a structure; logs go to outputs/ur5e_dog/<time>/
OMNI_KIT_ACCEPT_EULA=YES bash experiments/ur5e_dog/run_loop.sh \
  --attempts 1 --config experiments/ur5e_structures/column.json

# Browse recorded runs at http://127.0.0.1:8765
python3 experiments/ur5e_dashboard/server.py

# Open an empty stage with the extension loaded
uv run bricksim
```

Controller settings are environment variables documented in
`experiments/ur5e_dog/controller.py`: `DOG_BREAKAGE`, `DOG_PRESS_HOLD_S`,
`DOG_RELEASE_RAMP_S`, `DOG_FREEZE_ON_CONNECTION` and `DOG_REQUIRED_FORCE_N`.

## Development

```bash
pixi run build-native          # rebuild after C++ changes
pixi run test-native-release   # and test-native-debug
uv run ruff check
python -m unittest experiments.ur5e_dog.test_geometry
python -m unittest discover -s experiments/ur5e_dashboard -p 'test_*.py'
```

Coding rules for the C++ modules and Python are in [AGENTS.md](AGENTS.md).

## Citation

This work builds on BrickSim. Please cite:

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

BrickSim: [website](https://intelligent-control-lab.github.io/BrickSim/),
[paper](https://arxiv.org/abs/2603.16853),
[code](https://github.com/intelligent-control-lab/BrickSim),
[video](https://www.youtube.com/watch?v=VGuHfz4yxLU).

The Isaac Sim 6.0 groundwork (SDK pins resolver, Python 3.12 build changes)
comes from BrickSim's `isaacsim-6.0` branch.

## License

MIT, see [LICENSE](LICENSE). The copyright notice of the original BrickSim
authors is retained; changes in this repository are released under the same
license.
