# RISE digital twin research

The workspace-wide [post-clone change inventory](../../POST_CLONE_CHANGES.md)
separates supplied lab features from local setup, source patches, experiment
scaffolding, collision/grasp checks, and coordinated two-arm bar motion. Its validation
section and linked measurements supersede earlier untested scene-audit claims.

This workspace supports Kaleb's research with the ASU RISE lab. The user selected
**two robot arms manipulating a shared object** as the first target. The existing
brick demonstration is an installation reference, not the research objective.

## Start here

Run the first scene from the repository root after closing any scene you want
to preserve:

```bash
./scripts/run_desktop.sh experiments/rise_dual_ur5e.py
```

This loads two provisional NVIDIA UR5e models, a table, and a shared rigid object.
It holds configured joint targets, records two seconds of simulation, then
pauses. It does **not** attach grippers, grasp the object, coordinate arm motion,
or connect to physical robots. Press Play to resume the scene after recording.

Settings live in [configs/dual_ur5e.json](configs/dual_ur5e.json). To check a
configuration without launching the simulator:

```bash
.venv/bin/python experiments/rise_dual_ur5e.py --check
```

Run artifacts appear in `outputs/rise/<UTC timestamp>/`: `config.json`,
`manifest.json`, `states.jsonl`, and `scene.usda`. The trace records simulation
time, joint positions in radians, and object pose in meters / wxyz quaternions.
The manifest includes the source commit, dirty working-tree listing, dependency
versions, source asset URLs, and configuration hash. It does not snapshot all
uncommitted source files or remote asset contents; preserve those separately
before treating a result as fully reproducible. The saved scene references its
dependencies and is not a self-contained USD bundle.

Use [PROTOCOL.md](PROTOCOL.md) to design trials, [NOTEBOOK.md](NOTEBOOK.md) for
dated evidence and decisions, and [MCP_SETUP.md](MCP_SETUP.md) for simulator control.

## What is established

The workstation runs Ubuntu 24.04, Isaac Sim 5.1, Isaac Lab 2.3.2.post1, and
PyTorch 2.7.0+cu128 on an RTX 5080. The desktop assembly installation test passed.
The corrected two-arm scene passed a separate headless smoke test on
2026-10-26 (America/Phoenix), initializing two six-DOF articulations and recording
two seconds / 120 state samples. Joint hold error stayed below 0.25 rad and the
object stayed inside the 5 m workspace bound. Measured maximum joint error was
about 4.4e-8 rad; the object settled to z=0.425 m on the table. Evidence:
`outputs/rise/20261027T061121.266491Z/summary.json`. These are scene-integration
checks, not manipulation or physical-twin validation.

An earlier finite-only check missed severe divergence. That run is retained
and explicitly rejected in the notebook. Parent-Xform placement is essential:
the articulation API resolves this asset to a root-joint prim, so assigning
position through that API alone left the actual robot models overlapping.

The generic NVIDIA asset is
`Isaac/Robots/UniversalRobots/ur5e/ur5e.usd` relative to the asset root.
It is a provisional model. Lab calibration, tool-center-point geometry,
payloads, gripper configuration, controller gains, compliance, and friction are
not validated. Asset reference:
[NVIDIA robot catalog](https://docs.isaacsim.omniverse.nvidia.com/5.1.0/assets/usd_assets_robots.html).

## Lab assets received

The user supplied an email identifying Aldrin's repositories as the lab's asset
and control starting point. Both are now adjacent to this checkout:

| Repository | Role | Inspected upstream commit |
| --- | --- | --- |
| `../omni-kit-mcp` | Kit bridge, gateway, client, control panel | `68f738f60056a02701f449bfe043f676df35210e` |
| `../isaac-sim-mcp` | Lab UR5e tools and rigged assets | `27f610056017d7bffc2ff56fac6d219702b781a0` |

Key local assets, relative to `../isaac-sim-mcp/exts/ur5e-dt/assets/`, are:

- `robot/ur5e.usd` and its `SubUSDs/` dependencies.
- `gripper/RG2.usd`, quick-changer, and associated configuration layers.
- `sensors/rsd455.usd`.
- `workstation/vention.usd`.
- `objects/` and `fmb_assembly*.json` task assets.

Keep the asset directory structure intact so relative USD references resolve.
These are lab-provided models, not yet proof of a calibrated current lab cell.
Confirm dimensions, frames, mass properties, collision geometry, and model
revision with Aldrin before substituting them for physical measurements. The
generic two-arm scene remains a separate baseline; it has not silently switched
to a differently rigged model.

## Research milestones

1. **Import and audit the lab cell.** Reproduce the supplied robot, gripper,
   and workstation. Record articulation roots, joint names and limits, base and
   tool frames, units, and missing references. Verify FK against measured poses.
2. **Establish a contact baseline.** Measure sliding, grasp retention, and
   contact settling with native PhysX. Separate object/material parameters from
   timestep, contact offsets, solver settings, and controller effects. The
   current friction values are placeholders, not measurements.
3. **Build one-arm manipulation.** Validate the actual gripper and tool frame,
   then grasp, lift, and hold the shared object with independent success checks.
4. **Add the second arm.** Share a world/object coordinate frame; coordinate
   end-effector trajectories while monitoring relative pose, object slip,
   contact load, and controller conflict. Begin with a stationary two-arm hold,
   then a short coordinated translation and rotation.
5. **Evaluate a custom physics contribution.** Identify a measured behavior
   native PhysX fails to reproduce, define the proposed model and calibration
   parameters, and compare it against the unchanged baseline and held-out data.
6. **Validate the physical twin.** Replay matched simulated and measured
   experiments with synchronized timestamps and explicit error metrics. Model
   appearance alone is insufficient evidence.

Milestones 1–6 are research work still to do; the initial scene is scaffolding.
No first-task success thresholds have been agreed with the supervisor yet.

## Where custom physics belongs

General rigid-body dynamics, friction, and standard contacts come from
Isaac Sim / PhysX. Upstream custom C++ specializes in brick connectivity,
assembly, internal loads, and breakage; it is not a universal contact solver.
Relevant integration points are:

| Source | What to study |
| --- | --- |
| `native/modules/bricksim/omni/lego_runtime.cppm` | Stage lifecycle and runtime ownership |
| `native/modules/bricksim/omni/lego_world.cppm` | PhysX pre-step and completion callbacks |
| `native/modules/bricksim/omni/usd_physics_bridge.cppm` | Synchronization between USD and physics graphs |
| `native/modules/bricksim/physx/` | Existing assembly, breakage, and graph logic |
| `native/py/pybind11.cpp` | Python-to-C++ bindings |

Start with a separate, narrowly scoped model and documented equations, units,
and validation data. Do not change the upstream solver merely to make a task
look successful. Apply each physical effect exactly once; adding a contact
force on top of a native PhysX contact can double-count it. Callback ownership,
thread safety, passivity/energy behavior, and timestep convergence need explicit
tests before relying on a new model in multi-arm contact.

The current native extension is prebuilt. Pixi is not installed, and the C++
toolchain has not been validated here. **An active `.prebuilt-native/manifest.env`
causes the build script to copy the cached binary and skip compilation.** Before
native development, preserve/disable that cache deliberately, install Pixi's
pinned toolchain, run the release/debug native tests, and record the compiler,
SDK versions, build configuration, and resulting extension checksum.

Ruff and four configuration tests pass for the added experiment. Generated
type-checker extension paths resolve runtime imports, but `ty` still reports
vendor Scene.add annotation and pxr schema-stub limitations. No Any/cast/ignore
bypasses were added to hide those diagnostics.

## Documentation routine

Before an experiment, write the question, hypothesis, independent variables,
controlled conditions, and success criteria. Afterward, link the run directory
and record the actual result, failure cases, interpretation, and next test.
Keep measured facts, hypotheses, and proposals distinct. Preserve null results.
Use the notebook as the basis for short supervisor updates rather than relying
on chat history. Automation of ongoing notes or scheduled reports is not enabled.
