# Isaac Sim 6.2 port

This checkout targets Isaac Sim 6.2.0.0 and Python 3.12. It started from the
`isaacsim-6.0` branch of
[BrickSim](https://github.com/intelligent-control-lab/BrickSim) (commits
`03e1a5a`, `0b577ea`, `2dccda1`, by the BrickSim authors) and was then retargeted
to the 6.2 builds. The code before the move is BrickSim at
`kalebcoleman/BrickSim@4d7d629` (`feat/ur5e-dog-assembly`), on Isaac Sim 5.1.

> The commands below are as run during the port. The controller has since moved
> from `experiments/ur5e_dog/` to
> [experiments/ur5e_assembly/](../experiments/ur5e_assembly/README.md), and its
> settings are now `ASSEMBLY_*` (`DOG_*` is still accepted).

## Versions

| Component | Before (5.1) | Now (6.2) |
|---|---|---|
| Isaac Sim | 5.1.0 | 6.2.0.0 |
| Python | 3.11 | 3.12 (`.venv`: 3.12.16; Kit SDK: 3.12.14) |
| Kit kernel | 107.3 | 110.4.0 |
| omni.physx | 107.3.26 | 110.4.4 (`fb296f7d`) |
| PhysX SDK | 5.6.1 | 5.9.2.94859732 (`release-omni-110.4`) |
| OpenUSD | 24.05 | 25.11 (`0.25.11.kit.5`) |
| carb | 107.x | 210.4.11 |
| torch | 2.7.0+cu128 | 2.11.0+cu130 (pinned by Isaac Sim 6.2) |
| numpy | 1.26.4 | 2.3.1 |
| Isaac Lab | 2.3.2.post1 | not installed (`isaaclab` extra: 3.0.0) |

## Build

```bash
# Repo-local pixi and caches (kept in the gitignored _toolchain/ and .cache/).
source _toolchain/env.sh
pixi run build-native
pixi run test-native-release
uv sync --locked
```

`_toolchain/env.sh` sets the following:
- `PIXI`, `PIXI_CACHE_DIR`, `RATTLER_CACHE_DIR` and `XDG_CACHE_HOME` to point
  inside the checkout.
- `UV_CACHE_DIR=~/.cache/uv`, the shared cache.
- `CONDA_OVERRIDE_GLIBC=2.39`.

The override is needed on Ubuntu 22.04 (glibc 2.35). conda-forge ships no 2.35
sysroot, and Isaac Sim's `libpython3.12.so` needs `hypot@GLIBC_2.35`, so pixi
builds against the 2.39 sysroot. `AbiCheck.cmake` still rejects any symbol newer
than GLIBC 2.35, so the outputs run on 22.04.

The native module NEEDs `libpython3.12.so.1.0`. Kit preloads its own copy with
`RTLD_GLOBAL` before any extension loads, and Isaac Sim's own `libusd_python.so`
uses the same library.

### Regenerating `native/isaac_deps.toml`

`scripts/resolve_isaacsim_deps.py` reads pins from an installed Isaac Sim. A pip
install lacks two of its inputs, so supply them from the Isaac Sim source tag
first:

1. `deps/kit-sdk.packman.xml`: pass it as `--kit-sdk-manifest`.
2. The `omni_physics` package named in `deps/omni-physics.packman.xml`:
   extract it into `<packman-cache-root>/omni_physics/<version>/`.

```bash
.pixi/envs/default/bin/python3.12 scripts/resolve_isaacsim_deps.py \
  --python .venv/bin/python --output native/isaac_deps.toml \
  --cache-root .cache/bricksim/isaac-deps --packman-cache-root .cache/packman/chk \
  --kit-sdk-manifest .cache/kit-sdk.v6.2.0.packman.xml
```

The downloaded Kit is byte-identical to the installed one. USD matches the
version Kit's `all-deps.packman.xml` pins; the installed copy is stripped.

## Native changes

- `physx/patcher.cppm` holds the PhysX 5.9.2 `NpScene` offsets:
  - `mScene`: 1488.
  - `Sc::Scene::mFilterCallback`: +1016, so 2504 in total.
  - `mElapsedTime`: 968.

  They were read from the disassembly of the SDK's checked
  `libPhysX_static_64.a` and of Kit's release `libomni.physx.plugin.so`, which
  share this layout. The patch now throws if the located callback differs from
  `PxScene::getFilterCallback()`. Re-derive the offsets after any omni.physx
  update:
  - `NpScene::getFilterCallback()` loads `[this+0x9c8]`.
  - `NpScene::simulateOrCollide()` stores `elapsedTime` to `[this+0x3c8]`.
- Weld torque on CPU TGS scenes: PhysX's CPU TGS writeback reports a weld's
  torque about the weld point short by 2 rA x F (PGS and GPU are correct; PhysX
  5.6.1 and 5.9.x alike). `populate_rigid_info_map` adds it back so breakage sees
  the real joint load; `TestWeldConstraintForce` pins the PhysX behaviour. See
  [RESULTS.md](../experiments/ur5e_assembly/RESULTS.md).
- The omni.physx 107 `PrimIteratorMapRange` vtable patch is removed. 110.x
  traverses instance proxies in both `reset()` and `next()`.

## Python changes

- Kit starts through `SimulationApp` (from upstream).
- The 5.1 Vulkan profile shim (`isaacsim_rtx_compat`) is removed. Isaac Sim 6.2
  starts on driver 595.99.02 without it.
- `opencv-python-headless-noffmpeg` (Isaac Sim 6.2) is excluded because it
  conflicts with `opencv-python` over `cv2`.
- The step-one-frame toolbar patch stays disabled, as upstream reports it
  broken on 6.x.
- The UR5e experiments use `isaacsim.core.api`, `isaacsim.core.prims`,
  `isaacsim.core.utils` and `isaacsim.robot_motion.motion_generation`. In 6.2
  these live in `extsDeprecated/` but load unchanged.

## Results on 2026-11-07

All results come from simulation, judged by simulator ground truth.

Machine: RTX PRO 6000 Blackwell Max-Q, driver 595.99.02, Ubuntu 22.04.5.
Commands were run with `DISPLAY=:1` and the run (a)/(b) settings below.

| Run | Config | Breakage | Outcome | Peak press force per brick (N) |
|---|---|---|---|---|
| a | `ur5e_structures/single.json` | off | completed, 1/1 connected | 1.27 |
| b | `ur5e_structures/tower.json` | off | completed, 6/6 connected | 1.48, 1.16, 1.57, 1.29, 4.69, 1.23 |
| c | `ur5e_structures/column.json` | on | completed, 4/4 connected | 1.48, 1.13, 1.18, 1.02 |

Each run used `bash experiments/ur5e_dog/run_loop.sh --attempts 1 --config <config>`,
with `DOG_BREAKAGE=0` for (a) and (b). Every run executed once.

- The first launch took about 55 s to `app ready` (cold shader cache); later
  launches took about 18 s.
- Breakage-off results do not exercise the full model.
- The 5.1 tuning (press force, tolerances) was used unchanged; run (c) matches
  the 5.1 column result in [RESULTS.md](../experiments/ur5e_assembly/RESULTS.md).
- The `mElapsedTime` value the breakage solver reads was verified statically,
  not by a runtime readout.

Native tests: `pixi run test-native-release` and `pixi run test-native-debug`
both pass 17/17.
