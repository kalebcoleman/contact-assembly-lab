# isaac-mcp on Isaac Sim 5.1.0: tool report

Notes for the planned 5.1.0 support PR (expected #71) in `kalebcoleman/isaac-mcp`.
No PR #71 existed when this was written; the latest was #70. Nothing here was posted
to that repository and no isaac-mcp file was changed.

## What was tested

| Item | Value |
|---|---|
| Date | 2026-11-03 |
| Simulator | Isaac Sim 5.1.0.0, build `5.1.0-rc.19+release.26219.9c81211b.gl`, Kit 107.3.3, USD 24.05 |
| Bridge and sim-tools | Commit `af85e6b`, exported read-only with `git archive` |
| Gateway | Installed tool, editable from the live `~/Desktop/isaac-mcp` checkout (uncommitted changes) |
| Scene | This project's UR5e baseplate experiment, launched from a shell, not `sim__launch` |
| Physics | PhysX, CPU device, 120 Hz |

Line numbers refer to `af85e6b`. The live checkout has uncommitted edits to these
files (22 modified files at last check), so confirm the lines before patching.

The gateway and bridge were different versions during testing. Where that may explain
a result, the entry says so.

## Summary

111 tools are listed: 24 built-in and host, 40 `sim__*`, 8 `assets__*`, 4 managed-session,
12 `isaaclab__*` and 23 `ur5e_dt__*`. 62 were called (`status` only through `use_bridge`);
49 were not, mostly because they were out of scope or unsafe here.

- **Authored USD work is solid on 5.1.** Inspection, edits, graphs, ROS 2 setup, UI
  driving, screen capture and file tools all worked.
- **Nearly all runtime physics tools fail**, from one missing API.
- **Temporary shims unblocked most of them.** Two in-memory patches fixed 6 of the 7
  affected tools. `sim__simulation__step` needs a further code change.
- **Sensors are blocked on purpose** because 5.1 is not a qualified build.

## Root causes, in fix order

| # | Problem | 5.1 reality | Locations | Tools affected | Shim tested? |
|---|---|---|---|---|---|
| 1 | `SimulationManager.get_active_physics_engine()` | Does not exist | `sim_tools/physics.py:28,82,138,219,243,263`; `advanced.py:147,159,160,435,596`; `ur5e_dt/physics_compat.py:69`. `runtime.py:81` already handles it | timeline control, physics configure, body state, joints state, joints command, simulation step, occupancy map | Yes: `physx` fallback worked |
| 2 | `SimulationManager.get_physics_simulation_view()` | Named `get_physics_sim_view()` | `physics.py:113` | body state, joints state, joints command | Yes: alias worked |
| 3 | `sm.step(steps=steps)` | Signature is `step(render=False)`, with no step count | `physics.py:220,233` | simulation step | No: gives `STEP_FAILED` after shims 1 and 2 |
| 4 | `Stage.GetCompositionErrors()` | Absent in USD 24.05 | `stage_open.py:76`, `core.py:555,970`, `urdf.py:50`, `render_export.py:178` | stage open (confirmed); import tools (predicted, not run) | No |
| 5 | Sensor build gate | `qualified_build` is false, so sensors refuse | `runtime.py` `require_sensor_api` near line 143, `sensor_stack_issues`; `physics.py:88` | camera create, lidar create | No: deliberate gate |

The shims used, in-memory on a throwaway process only:

```python
from isaacsim.core.simulation_manager import SimulationManager as sm
sm.get_active_physics_engine = staticmethod(lambda: "physx")
sm.get_physics_simulation_view = sm.get_physics_sim_view
```

These prove the path, not a finished fix. A real patch should be version-aware and
should not assume PhysX on a build that might run something else. For #3, looping
`sm.step()` is the obvious candidate but is untested, and `physics.py:220` may be in a
Newton-only branch. Qualify sensors (#5) with the live suite rather than bypassing the gate.

## Every tool

**Status key:** Works = worked as called. Shim = failed on 5.1, worked with the shims
above. Fails = failed on 5.1. Refused = clean refusal by design or setup. Not run = not called.

### Bridge built-ins and host tools

| Tool | Status | Notes |
|---|---|---|
| `run_python` | Works | Most useful tool. Also the workaround for every runtime failure |
| `status` | Works | Used through `use_bridge`, which returns it. Confirmed PID, port and 5.1.0 |
| `use_bridge` | Works | Essential: two other Kits were advertising |
| `list_bridges` | Works | Reports only running bridges |
| `refresh_tools` | Works | Registered 42 tools after switching to the pinned bridge |
| `reload_tools` | Fails | `reload_tools(module="sim_tools")`: "declares no public functions to serve". May need a different module name; not explored |
| `stat_file`, `put_file`, `get_file` | Works | `stat_file` returned the expected asset hash |
| `screenshot` | Works | Auto-targets the Kit window |
| `list_windows`, `screen_info` | Works | |
| `raise_window` | Works | |
| `start_screen_recording`, `stop_screen_recording` | Works | Recorded the three demo videos, window-only |
| `screen_recording_status` | Works | |
| `join_videos` | Works | Concat test only |
| `move_window`, `tile_windows` | Not run | No RViz window to arrange |
| `window_click`, `window_drag`, `window_key`, `window_scroll`, `window_type` | Not run | Avoided desktop input on a shared X11 session |

### Generic scene tools (`sim__*`)

| Tool | Status | Notes |
|---|---|---|
| `sim__stage__info` | Works | Also gives the exact ROS shell line. Reports `physics_engine: null`, `qualified_build: false` |
| `sim__stage__tree`, `sim__prim__get`, `sim__prim__find` | Works | |
| `sim__physics__inspect`, `sim__joints__inspect` | Works | Found both articulations and the authored joints |
| `sim__prim__create`, `set_transform`, `clone`, `delete` | Works | Stopped timeline only |
| `sim__stage__clear_owned` | Works | |
| `sim__light__create`, `sim__light__modify` | Works | |
| `sim__material__create`, `sim__material__apply` | Works | |
| `sim__joints__drive` | Works | Target 0.5 worked. Target 1.0 returned `JOINT_LIMIT`, though the experiment drives this joint to 1.0 rad at runtime. Worth checking the limit comparison |
| `sim__stage__save` | Works | The flattened scene was 359 MB |
| `sim__viewport__frame` | Works | |
| `sim__graph__node_types`, `build`, `inspect`, `show` | Works | Graph built with a 5.1 ROS node. Publication from this probe graph was not checked |
| `sim__ui__find` | Works | |
| `sim__ui__act` | Works | `tab` action only |
| `sim__logs__tail` | Works | Its scene events helped diagnose the hot reload |
| `sim__ros2__tf_setup` | Works | Arm and gripper graphs. See below |
| `sim__timeline__control` | Shim | Needs #1 |
| `sim__physics__configure` | Shim | Needs #1 |
| `sim__map__occupancy` | Shim | Needs #1, and #2 is untested in isolation; wrote PGM and YAML with both |
| `sim__body__state` | Shim | Needs #1 and #2. Values looked right; mass 0.1879 kg |
| `sim__joints__state` | Shim | Needs #1 and #2 |
| `sim__joints__command` | Shim | Target acknowledged. Achieved motion was not checked through this tool |
| `sim__simulation__step` | Fails | Needs #3. Also `EDIT_TARGET_CHANGED` if Play came from anywhere but `sim__timeline__control` |
| `sim__stage__open` | Fails | **Misleading:** the stage opened, then the tool returned an error (#4). The result gives no new IDs |
| `sim__camera__create`, `sim__lidar__create` | Refused | `SENSOR_BUILD_UNVERIFIED` (#5) |
| `sim__camera__capture` | Refused | `NOT_OWNED` on an existing scene camera. The description mentions `adopt=true`, but the loaded schema has no `adopt` field |
| `sim__controller__create` | Refused | `SCRIPT_DISABLED`; needs `ISAAC_MCP_ENABLE_SCENE_SCRIPTS=1` |
| `sim__controller__update`, `sim__lidar__read` | Not run | No controller or LiDAR could be created |

### Project assets (`assets__*`)

| Tool | Status | Notes |
|---|---|---|
| `assets__roots`, `assets__search` | Works | Empty: no root is approved in this setup |
| `assets__scan` | Refused | `ROOT_NOT_APPROVED` |
| `assets__info`, `import_usd`, `import_path`, `import_urdf`, `prepare_workstation` | Not run | Need an approved root. Expect #4 to affect imports; `import_urdf` also states it needs the 6.x importer |

### Managed simulator sessions

| Tool | Status | Notes |
|---|---|---|
| `sim__list` | Works | Lists managed sessions only, so never showed the 5.1 session |
| `sim__launch`, `sim__status`, `sim__stop` | Not run | They manage isaac-mcp 6.x sessions, and this project needs its own launcher. **Gap:** no managed way to launch this setup |

### Isaac Lab (`isaaclab__*`)

| Tool | Status | Notes |
|---|---|---|
| `isaaclab__install_info` | Works | **Reports the wrong stack for this project:** Lab 3.0.0 / Sim 6.2 in another venv, not Lab 2.3.2 / Sim 5.1 |
| `isaaclab__runs_list` | Works | Long output, mostly old runs |
| `envs_list`, `train`, `eval`, `play`, `runs_status`, `runs_tail`, `runs_cancel`, `metrics_summary`, `checkpoints_list`, `tensorboard_tail` | Not run | Out of scope, and would target the 6.2 environment |

### UR5e twin (`ur5e_dt__*`, 23 tools)

| Tool | Status | Notes |
|---|---|---|
| `ur5e_dt__stop_scene` | Refused | Clear error: the extension is not loaded. Used only to observe that message |
| `start_ros_driver`, `sync_real_poses` | Not run | **Deliberately never called:** real-robot paths |
| `add_objects`, `assemble_objects`, `delete_objects`, `get_recording_status`, `load_simple_room`, `load_workstation`, `new_stage`, `play_scene`, `quick_start`, `quick_start_with_workstation`, `quick_start_with_workstation_and_simple_room`, `randomize_object_poses`, `randomize_single_object`, `restore_scene_state`, `save_scene_state`, `set_object_pose`, `setup_camera_tf_graph`, `setup_pose_publisher`, `start_recording`, `stop_recording` | Not run | `ur5e-dt` was not enabled, and these experiments build their own scene. `physics_compat.py:69` shows it shares #1 |

## ROS 2 verified on 5.1

`sim__ros2__tf_setup` worked unchanged. A separate `rclpy` process
(`scripts/verify_ros_graph.py`), plus `ros2 topic hz` and `ros2_tf_doctor.py`, showed:

| Check | Result |
|---|---|
| `/clock` | One publisher, 59.98 Hz, monotonic simulation time |
| `/joint_states` | Six arm joints, about 60 Hz. A commanded 0.25 rad `shoulder_pan` move appeared |
| `/rg2/joint_states` | Six gripper joints, about 60 Hz, including `rg2_gripper_joint` |
| `/tf_static` | `world -> base_link` |
| `world -> wrist_3_link` | Matched USD to under 1 µm, rotation agreed |
| TF doctor | **One error:** eight `rg2_*` frames do not connect to `world` |

The gripper error is real and expected. The RG2 is a separate articulation joined by
fixed joints with `excludeFromArticulation`, so neither graph publishes wrist to gripper.
A static transform at setup time would go wrong as soon as the arm moves.

Limits: this was with no assembly running, only a commanded test move. Publishing during
an assembly was not tested. `tool0` is not in TF.

Environment needed for Kit:

```bash
export LD_LIBRARY_PATH="$PWD/.venv/lib/python3.11/site-packages/isaacsim/exts/isaacsim.ros2.bridge/jazzy/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export ROS_DISTRO=jazzy ROS_DOMAIN_ID=42 ROS_LOCALHOST_ONLY=1 RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
export CYCLONEDDS_URI="file://<isaac-mcp>/config/cyclonedds.xml"
```

## What gave trouble, and the workaround

| Problem | Effect | Workaround |
|---|---|---|
| **Extension hot reload.** Editing the live checkout reloaded `sim-tools` inside running Kit | Session ID changed under the same PID (`STALE_TARGET`); unsafe for recorded runs | Ran from a `git archive` export of a pinned commit |
| Export needed `mcp/` too | `No module named 'isaac_mcp'`: sim-tools imports the host package | Exported `exts config scripts mcp` |
| Gateway and bridge schemas differ | `sim__graph__node_types` and `sim__logs__tail` demanded IDs that their descriptions call unneeded | Passed IDs |
| Runtime tools fail on 5.1 | No timeline or physics reads through tools | `run_python` with `omni.timeline` and `SingleArticulation` |
| Experiment's Stop callback rebuilds the stage, while tools need a stopped timeline | Stop wiped the session layer | `World.instance().remove_timeline_callback(...)` before stopping |
| Stale articulation handle after Stop and Play | `get_joint_positions()` returned `None` | Created a new `SingleArticulation` and called `initialize()` |
| Timeline started outside the tools | `sim__simulation__step` returned `EDIT_TARGET_CHANGED` | Use `sim__timeline__control`, which needs shim #1 on 5.1 |
| `tf_setup` `extra_frames` typed as array of numbers | Prim paths would be rejected by the schema. Not called this session | Left unused; `tool0` is not published |
| `pgrep -f` matched my own shell | Exit 144 killed the command | Record the PID and kill exactly that |
| `setsid` forked | Recorded PID was wrong | Looked up the real process afterward |
| Other Kits on the machine | Risk of acting on someone else's session | Unique port and domain; checked PID and version with `status` every time |
| `robot/ur5e.usd` references missing `SubUSDs/Robotiq_2F_85_edit.usd` | Warning only; the prim is unused here | Reported, not changed |

## Most helpful tools

1. `run_python`: the fallback for everything, and it has full API access.
2. `use_bridge` and `status`: made it safe to work alongside other simulators.
3. `sim__ros2__tf_setup`: the best surprise, it worked on 5.1 unchanged.
4. `start_screen_recording` and `stop_screen_recording`: window-only video with almost no effort.
5. `sim__stage__info`, `sim__physics__inspect`, `sim__joints__inspect`: real schemas instead of guessed transforms.
6. `sim__logs__tail`: its scene events made the hot reload diagnosable.

## Suggested order for the 5.1 PR

1. Add one version-aware physics helper covering #1 to #3, and use it at every listed site.
2. Replace `GetCompositionErrors` with something that works on USD 24.05 (#4). Fix `sim__stage__open` so it never reports failure after switching stage.
3. Add a launch path for an external 5.1 app, or document this one. Include the ROS library path.
4. Guard against hot reload in running sessions, at least with a clear warning.
5. Fix the `extra_frames` item type and the `adopt` schema mismatch.
6. Check `sim__joints__drive` at the exact joint limit.
7. Decide how ROS should connect the gripper to the arm (a dynamic wrist-to-gripper transform).
8. Run the sensor qualification suite on 5.1 before enabling sensors (#5).
9. Make `isaaclab__install_info` able to target a project's own environment.
10. Run tool tests against 5.1 in addition to 6.x, then update `docs/COMPATIBILITY.md`.
