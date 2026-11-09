# Contact Assembly Lab

### Robotic brick assembly with joint-strength physics in Isaac Sim 6.2

**Kaleb Coleman**

[Structure catalog](docs/STRUCTURES.md) ·
[Failure analysis](experiments/ur5e_structures/FAILURES.md) ·
[Assembly controller](experiments/ur5e_assembly/README.md) ·
[Usage and reproduction](docs/USAGE.md) ·
[Isaac Sim 6.2 port](docs/ISAACSIM_6.2_PORT.md) ·
[Citation](#citation)

[![Isaac Sim 6.2](https://img.shields.io/badge/Isaac%20Sim-6.2-76B900?logo=nvidia&logoColor=white)](https://docs.isaacsim.omniverse.nvidia.com/6.2.0/index.html)
[![Python 3.12](https://img.shields.io/badge/python-3.12-3776AB?logo=python&logoColor=white)](https://docs.python.org/3.12/)
[![MIT License](https://img.shields.io/badge/license-MIT-yellow.svg)](LICENSE)
[![Built on BrickSim](https://img.shields.io/badge/built%20on-BrickSim-c0392b)](https://github.com/intelligent-control-lab/BrickSim)

![The UR5e building the arch bridge in simulation](docs/media/bridge.gif)

A UR5e arm with an RG2 gripper builds interlocking-brick structures in NVIDIA
Isaac Sim 6.2. BrickSim's joint-strength model decides, at every physics step,
whether each stud connection holds. The project asks what a robot can build
reliably and why builds fail, and it is the contact-physics testbed for my
research on Jenga with MPC and RL. All results are simulation.

## Showcase

Each picture links to its video, rendered in the simulator.

<!-- showcase:start -->
| Dog, 10 bricks | Arch bridge, 7 bricks |
|---|---|
| [![Dog](docs/media/dog_breakage_on_closeup.jpg)](docs/media/dog_breakage_on.mp4) | [![Arch bridge](docs/media/bridge_closeup_front.jpg)](docs/media/bridge.mp4) |
| Legs, a wide body bridging them, a neck, a head and a tail. | Stepped piers and a deck that lands on both. |

| House, 8 bricks | Log cabin, 8 bricks |
|---|---|
| [![House](docs/media/house_closeup.jpg)](docs/media/house.mp4) | [![Log cabin](docs/media/log_cabin_closeup.jpg)](docs/media/log_cabin.mp4) |
| A doorway, a lintel across it, a stepped roof and a chimney. Builds when the arm eases off before letting go. | Every log interlocks two corners. |

| Lighthouse, 7 bricks | Castle gate, 8 bricks |
|---|---|
| [![Lighthouse](docs/media/lighthouse_closeup.jpg)](docs/media/lighthouse.mp4) | [![Castle gate](docs/media/castle_gate_closeup.jpg)](docs/media/castle_gate.mp4) |
| A striped tower on a rock, a lamp and a cap: seven layers. | Two towers, a lintel over the gate and battlements. Builds with an eased-off, faster release. |

| Steam locomotive, 8 bricks | Trestle table, 5 bricks |
|---|---|
| [![Steam locomotive](docs/media/locomotive_closeup.jpg)](docs/media/locomotive.mp4) | [![Trestle table](docs/media/trestle_table_closeup.jpg)](docs/media/trestle_table.mp4) |
| Three wheels under a long chassis, a cab, a boiler and a smokestack. Builds with a faster release. | Slab legs gripped end to end, so the fingers stay out of the gap under the top. |
<!-- showcase:end -->

**[All structures →](docs/STRUCTURES.md)** For each one the catalog gives the
design, the simulated build, the bricks and joints, how many runs completed,
and a video.

## Failures

Every structure was first built with the same controller settings. When one
failed, the run showed where and why, and it was tried again with a different
release, grip or design. Some failures are planned break tests: the cantilever
below tips over when a brick is pressed onto its free end.

![Cantilever failure](docs/media/cantilever_failure.gif)

<!-- failures:start -->
| What went wrong | What fixed it | Now builds |
|---|---|---|
| A joint breaks as the gripper opens: the arm is still pushing | Ease off 0.5 mm before letting go | tree, offset tower, house |
| A joint breaks as the gripper opens: load builds while it opens | Let go faster (0.5 s instead of 1 s) | column of ten, cross-bonded tower, zigzag, leaning ladder, L corner, steam locomotive |
| Both of the above | Both fixes together | castle gate |
| A half-supported brick tips and never seats | Grip and press it over its support | mixed tower |
| No room for the fingers beside a brick | Grip the brick end to end | trestle table |

**Still not buildable:**
- the original table: no room for the fingers;
- the wide-gap table, spiral tower, 2x2 tower and lean 6: their 4-stud joints
  break;
- both cantilevers: they need building as a sub-assembly.

Where each structure fails, every attempt and how many runs it took are in
[FAILURES.md](experiments/ur5e_structures/FAILURES.md).
<!-- failures:end -->

## Dashboard

A local, read-only viewer for every run: each structure layer by layer, every
trial, and per-step recordings. Isaac Sim need not be running.

```bash
python3 experiments/ur5e_dashboard/server.py   # then open http://127.0.0.1:8765
```

![Dashboard structures view](docs/media/dashboard_structures.png)

## Reproducibility

- **Every run is recorded.** Each sweep definition names the configs, the
  settings and the controller commit, and its generated summary lists every
  run's outcome, joint breaks and solver warnings
  ([sweeps](experiments/ur5e_structures/sweeps/README.md)).
- **Runs are deterministic.** Repeating a structure gave identical results on
  the reference machine (Ubuntu 22.04, RTX PRO 6000 Blackwell, Isaac Sim
  6.2.0.0, PhysX 5.9.2).
- **One command re-runs a sweep** into a fresh copy, for comparison with the
  committed summary:

  ```bash
  OMNI_KIT_ACCEPT_EULA=YES python3 -m experiments.ur5e_structures.run_sweep \
    experiments/ur5e_structures/sweeps/2026-11-08-showcase-sweep.json \
    --rerun experiments/ur5e_structures/sweeps/my-rerun.json --capture
  ```

- **One requirement is outside this repository.** The UR5e, gripper and bench
  models come from a separate asset store, pinned by hash.

Build steps, the exact stack and all commands:
[docs/USAGE.md](docs/USAGE.md).

## My version

This repository builds on [BrickSim](https://github.com/intelligent-control-lab/BrickSim)
by Haowei Wen, Ruixuan Liu, Weiyi Piao, Siyu Li and Changliu Liu (Intelligent
Control Lab, Carnegie Mellon University), released under the MIT License. The
brick connection and breakage physics, the C++ native extension and the
simulator UI are theirs. This version adds:
- **the Isaac Sim 6.2 port**, from 5.1 / Python 3.11 to 6.2.0.0 / Python 3.12
  ([notes](docs/ISAACSIM_6.2_PORT.md));
- **a weld-torque correction** for PhysX 5.9's CPU TGS solver, which
  misreported the loads the breakage model reads;
- **a UR5e assembly controller** that builds any structure config, releases
  bricks without touching their neighbours and logs every gripper contact
  ([controller](experiments/ur5e_assembly/README.md));
- **the structure library** of 29 structures, its design renderer and
  the [catalog](docs/STRUCTURES.md);
- **reproducible sweeps**, run summaries that separate physics failures from
  numerical and controller ones, and the failure analysis;
- **the dashboard**.

## Roadmap

1. Grip bricks in more ways (across the long side, re-grasping) to remove the
   gripper limits found so far.
2. Use more LEGO elements, such as plates, 1-wide bricks and offsets, for more
   complex builds.
3. Build the same structures on the real UR5e and compare what fails.
4. Carry the evaluation methods over to Jenga
   ([notes](docs/EVALUATION_PRACTICES.md)).

## Citation

If you use this work, please cite it and BrickSim, which it builds on.

```bibtex
@software{coleman2026contactassemblylab,
    title = {Contact Assembly Lab: Robotic Brick Assembly with Joint-Strength Physics in Isaac Sim 6.2},
    author = {Coleman, Kaleb},
    year = {2026},
    url = {https://github.com/kalebcoleman/contact-assembly-lab}
}
```

```bibtex
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
