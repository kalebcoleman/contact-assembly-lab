# ROS 2 Humble mock assembly controller

`ros2/risl_contact_assembly` is a Python 3.10 ament_python package that turns a
known brick structure into a pose plan and rehearses that plan without touching
the robot. It reuses the Max stack conventions (`risl_ur` custom IK, RG2 gripper
protocol, UR force-mode services) but adds no MoveIt dependency.

This laptop is the robot-side machine, so "no hardware" is a hard constraint
here, not a topology statement. Nothing in this directory may launch the UR
driver, the RG2 node, the Vention controller or `cell.launch.py`. See
[Compatibility inventory](#compatibility-inventory) and
[Staged commissioning](#staged-commissioning-future).

## Evidence levels

Keep these three levels separate in every log and report.

| Level | What runs | What it proves |
|---|---|---|
| Plan rehearsal (`dry_run:=true`, default) | Planner only; step records written to JSONL | Poses, ordering and limits are internally consistent. No control topic is published. |
| Mock trajectory execution (`dry_run:=false`, `mock_execution:=true`) | Official UR driver fake-hardware GenericSystem plus the package's fake gripper, all on loopback | Commands are well formed and the state machine completes against simulated feedback. Still no physical motion. |
| Physical insertion | Real driver, force mode, operator | Nothing yet. Blocked, see below. |

Simulation results (known poses, RMPflow, timed release, snap-weld contact
models) do not transfer automatically. They do not validate real insertion,
real stud engagement or real release timing, and mock execution must never be
cited as if they did.

## Package layout

Expected integration target from the shared contract. Sibling files land in
separate commits and the parent may rename launch arguments or fixture paths.

```
ros2/
├── README.md
└── risl_contact_assembly/
    ├── package.xml, setup.py, setup.cfg, resource/
    ├── config/assembly.yaml
    ├── fixtures/single_brick.json, fixtures/three_bricks.json
    ├── launch/mock_assembly.launch.py
    ├── risl_contact_assembly/
    │   ├── __init__.py
    │   ├── planner.py
    │   ├── executor.py
    │   ├── fake_gripper.py
    │   └── record_joint_states.py
    └── test/
```

Entry points: `assembly_executor`, `fake_gripper`, `record_joint_states`.

## Planning contract

`planner.py` exports `load_config(path) -> dict`,
`load_structure(path) -> dict` and
`plan_structure(structure: dict, config: dict) -> list[dict]`.

Each step is TCP pose in the `base` frame, metres and degrees:

```
{"action": "approach" | "descend" | "close" | "lift" | "transfer" |
           "approach_target" | "slow_descend" | "seat" | "open" | "retreat",
 "brick_id": str, "xyz_m": [x, y, z], "rpy_deg": [r, p, y],
 "speed_m_s": positive float, "gripper_width_mm": optional int}
```

Brick frames are bottom-centre: +x along length `L`, +y along width `W`, +z up,
with `[L, W, H]` in studs and plate units. For stud pitch `U`, plate height
`P`, support frame `(p_sup, R_sup)` in `base`, support dimensions `Ls, Ws, Hs`,
child dimensions `Lb, Wb`, corner offset `ox, oy` in studs and child local yaw
`R_local`:

```
p_child = p_sup + R_sup * ([-Ls*U/2 + ox*U, -Ws*U/2 + oy*U, Hs*P]
                           + R_local * [Lb*U/2, Wb*U/2, 0])
```

The child yaw accumulates support yaw and local quarter turns. This matches
`python/bricksim/utils/connection_geometry.py` (`connection_brick_transforms`)
and `python/bricksim/units.py`: `U = 0.008`, `P = 0.0032`, so a 20x20x1
baseplate is the root support with `Ls = Ws = 20`, `Hs = 1`. A step TCP pose is
`T_base_brick @ T_brick_tcp`, where `T_brick_tcp` is the calibrated
`brick_to_tcp` transform, never a simulation grasp offset.

`config/assembly.yaml` schema sketch; values in `<...>` must be calibrated,
measured or operator-approved before use:

```yaml
baseplate:
  origin_xyz_m: [x, y, z]      # calibrated plate bottom centre in base
  yaw_deg: <deg>               # plate +x in base
  stud_pitch_m: 0.008          # fixed by the brick system
  plate_height_m: 0.0032       # 20x20x1 baseplate
  brick_height_m: 0.0096       # H3 brick, 3 plate units
pickup:
  xyz_m: [x, y, z]             # absolute fixture TCP pose in base, not an offset
  rpy_deg: [r, p, y]
  gripper_width_mm: <opening>
  brick_to_tcp:                # calibrated brick frame to TCP transform
    translation_m: [tx, ty, tz]  # brick origin to TCP, in brick axes
    rpy_deg: [r, p, y]           # brick axes to TCP axes, extrinsic xyz
limits:
  workspace_min_m: [x, y, z]   # measured workspace AABB
  workspace_max_m: [x, y, z]
  max_speed_m_s: <cap>
  max_speed_scale: <cap>
motion:
  hover_m: <height>
  travel_speed_m_s: <speed>
  descend_speed_m_s: <speed>
seating:
  force_n: <commanded force>   # commanded wrench, not a measured limit
  max_travel_m: <cap>          # hard cap, no added tolerance
  timeout_s: <timeout>
```

`brick_to_tcp` is an authorized package field; the planner fixtures own the
exact schema. `rpy_deg` follows `risl_ur`'s `rpy_to_matrix` (SciPy extrinsic
`xyz`, degrees). `seating.force_n` is the commanded wrench, not a measured force
limit; `max_travel_m` is a hard cap and exceeding it stops the step.

Structure inputs list bricks in build order with dimensions `[L, W, H]`, support
index or null, offset studs and quarter-turn yaw, the vocabulary of
`experiments/ur5e_structures/specs.py`. Do not feed `brick_positions_xy_m` from
those files to this package: they are stage coordinates, not `base` poses.
Simulation `grasp_offsets_m`, press depth, release lift and release ramp are
unvalidated hints; do not copy them into config or fixtures.

Executor parameters: `config_file`, `structure_file`, `dry_run` (default
`true`), `confirm_each_step` (default `true`), `pose_source` (default
`known_poses`), `step_log`, `mock_execution` (default `false`). Dry run
constructs no `MotionExecutor`, because that constructor switches controllers
and talks to the gripper, and publishes no control commands. `confirm_each_step`
blocks before every step until the operator confirms in the executor's terminal;
the prompt text is executor-owned.

Validate limits per step, including the interpolated joint-space path between
endpoints: endpoint speeds do not bound the TCP path, which can leave the
workspace or exceed the speed cap between waypoints. Reject violations as
errors; never clamp silently. Watchdogs use `time.monotonic`, not ROS time.
Stops are bounded to one attempt per fault with the result logged, never an
unlimited retry. Force-mode `deviation_limits` are not a compliant-axis travel
cap, and travel is never evidence of contact or a seated brick. Every threshold
in fixtures and tests is a mock value, not a validated hardware limit.

## Interfaces

| Name | Type | Direction |
|---|---|---|
| `/gripper_command` | `std_msgs/String` | command: `open`, `close`, `query`, or `0`–`1100` (tenths of a mm) |
| `/gripper_width` | `std_msgs/Float64` | measured opening, mm (mock and package contract) |
| `/joint_states` | `sensor_msgs/JointState` | measured joints, six UR5e names |
| `/tcp_pose_broadcaster/pose` | `geometry_msgs/PoseStamped` | measured TCP |
| `/force_mode_controller/start_force_mode` | `ur_msgs/SetForceMode` | force mode start |
| `/force_mode_controller/stop_force_mode` | `std_srvs/Trigger` | force mode stop |

Controllers used by the Max stack: `scaled_joint_trajectory_controller`,
`forward_velocity_controller`, `force_mode_controller`,
`passthrough_trajectory_controller`; trajectory action
`/scaled_joint_trajectory_controller/follow_joint_trajectory`.

The real RG2 node publishes `/gripper_queried_width`, not `/gripper_width`;
`/gripper_command` accepts up to `1100` but the geometry table only covers
`0`–`1000` tenths of a mm. Reconcile before hardware use.

## Frames and kinematics

`base` is the DH base used by `risl_ur/custom_libraries/ik_solver.py`; it is
`base_link` rotated by pi about Z, as `risl_simulation/robot_model.py` also
states. Converting between them negates x and y.

The executor uses `base` and never falls back to `base_link` silently. If the
installed driver only provides `base_link`, apply the explicit pi-Z rotation
and verify the actual driver transform at runtime instead of assuming it. A
pose derived from `/joint_states` is derived state, not sensor evidence.

Poses are `tool0` flange poses: zero TCP offset is assumed. The fingertip
reach in front of `tool0` depends on opening (`gripper_geometry.GRIPPER_TABLE`,
0.153 m at 0 to 0.114 m at 1000 tenths of a mm) and `GRIPPER_FINGER_OFFSET` is
0.010 m. Planners must account for that reach when choosing grasp and seating z;
the DH chain ends at `tool0`, not at the fingertips.

## Build

Requires the system Python 3.10 and ROS Humble, both present. Build into bases
outside the repository because root `.gitignore` matches `build/` but not
`install/` or `log/`.

```bash
source /opt/ros/humble/setup.bash
cd <repository root>
export ROS_LOCALHOST_ONLY=1 ROS_DOMAIN_ID=83
colcon --log-base /tmp/opencode/ros2_colcon/log \
  build --base-paths ros2 --packages-select risl_contact_assembly \
  --build-base /tmp/opencode/ros2_colcon/build \
  --install-base /tmp/opencode/ros2_colcon/install
source /tmp/opencode/ros2_colcon/install/setup.bash
```

`--log-base` is a colcon global argument and must come before the verb;
`--build-base` and `--install-base` stay after it.

The UR stack is not installed system-wide. The parent's repository-local
overlay (a prefix plus `env.sh`) supplies driver 2.15 and its dependencies for
mock work; source it before any launch. Without it, the mock launch cannot
start, which is an environment state, not a package defect.

The package must not import `ur_msgs`, `ur_robot_driver`, `ur_description`,
`pymodbus` or `serial` at module import time: the base environment does not
provide them.

## Tests

```bash
python3 -m pytest ros2/risl_contact_assembly/test -q
colcon --log-base /tmp/opencode/ros2_colcon/log \
  test --packages-select risl_contact_assembly \
  --build-base /tmp/opencode/ros2_colcon/build \
  --install-base /tmp/opencode/ros2_colcon/install \
  --test-result-base /tmp/opencode/ros2_colcon/build
colcon --log-base /tmp/opencode/ros2_colcon/log \
  test-result --verbose --test-result-base /tmp/opencode/ros2_colcon/build
```

`colcon test` and `test-result` accept `--build-base`/`--install-base` and
`--test-result-base` after the verb; `--log-base` only works before it. System
`pytest` is 6.2.5 (`python3-pytest` 6.2.5-1ubuntu2). Tests must cover planner
transforms, pitch, height, ordering, non-finite input, workspace limits, plus
executor dry-run silence, stale or missing feedback, timeout, overtravel and
bounded-stop behaviour.

## Dry run (default)

```bash
export ROS_LOCALHOST_ONLY=1 ROS_DOMAIN_ID=83
source /tmp/opencode/ros2_colcon/install/setup.bash
ros2 launch risl_contact_assembly mock_assembly.launch.py \
  structure_file:=fixtures/single_brick.json \
  config_file:=config/assembly.yaml \
  dry_run:=true confirm_each_step:=true
```

Expected: one JSONL record per planned step in `step_log`, and no publisher on
`/gripper_command`, the trajectory action, or the force-mode services. The
parent records whether this actually runs; this branch contains no execution
evidence.

## Mock execution

Standalone launch only: `mock_assembly.launch.py` never includes
`cell.launch.py` or any other launch file. Mock motion comes from the official
UR driver's fake-hardware GenericSystem, so the standard
`scaled_joint_trajectory_controller` `FollowJointTrajectory` action and
`/joint_states` exist, plus `fake_gripper` for the String/Float64 gripper
interface. A topic-only fake is not an acceptable substitute because it would
skip the real controller path.

In driver 2.15 the only fake-hardware switch is `use_fake_hardware:=true`; the
launch declares no `use_mock_hardware`, so do not pass that name.
`robot_ip` is required even with fake hardware, so pass `robot_ip:=127.0.0.1`.
Keep `use_tool_communication:=false` (its default), and set
`launch_dashboard_client:=false` and `launch_rviz:=false` explicitly: both
default to true, and the dashboard client is skipped only because fake hardware
gates it off. `initial_joint_controller` defaults to
`scaled_joint_trajectory_controller`, which is the action this package needs.
Inspect the installed `ur_control.launch.py` and xacro before changing any of
this; a launch that leaves fake hardware off or omits `robot_ip` is invalid and
its result is discarded.

Expected inside the package launch:

```
ur_type:=ur5e robot_ip:=127.0.0.1 use_fake_hardware:=true
use_tool_communication:=false launch_dashboard_client:=false launch_rviz:=false
```

```bash
ros2 launch risl_contact_assembly mock_assembly.launch.py \
  structure_file:=fixtures/three_bricks.json \
  config_file:=config/assembly.yaml \
  dry_run:=false mock_execution:=true confirm_each_step:=false
```

The launch log must state the fake-hardware configuration it selected. Verify
only fake hardware nodes run, no `/tmp/ttyUR` exists, and nothing connects to
`192.168.1.111` or `192.168.7.2`. Fake hardware starts
`controller_manager/ros2_control_node` instead of `ur_ros2_control_node`, and
`ur_control.launch.py` deliberately removes `tcp_pose_broadcaster` from the
active controllers in that mode. Derive the pose from `/joint_states` by
forward kinematics with the explicit pi-Z base convention and label it derived,
never sensor evidence. `fake_gripper` answers with `/gripper_width` and reports
commanded geometry, not grasp force or contact.

## Staged commissioning (future)

Nothing below may run from this package or this branch. Each stage starts with
an emergency-stop test, an operator-approved speed cap, an empty workspace
check and a dry run. Numbers are placeholders a qualified operator must set and
record; none are validated.

| Stage | Work | Pass | Stop |
|---|---|---|---|
| 0 | E-stop and protective stop with drives enabled, no motion | Stop halts motion and clears program state | Any motion after stop |
| 1 | Reduced speed, no bricks, TCP-only paths | Path matches plan within operator-set tolerance, no collision | Deviation, unexpected move, fixture contact |
| 2 | Gripper only, no bricks | `open`/`close`/`query` answer, feedback repeats | No feedback, uncommanded motion |
| 3 | One brick, pick and place at known pose | Grasp holds, placement within operator-set tolerance, release clean | Slip, tip, force spike, missed release |
| 4 | Small structure, three bricks | All three seated and released, structure stable at inspection | Any seat failure, collapse, force excursion |

Hardware seating is blocked. Do not ask the robot to press a brick down
open-loop. Seating needs validated force/torque (FT) sensing, a calibrated
force limit and a verified stop path; without FT feedback there is no
acceptable seating test. `seating.force_n` in `assembly.yaml` is a commanded
force, not a measured limit, and any proposed force or pass/fail number
requires operator approval before use. A seating stage also needs the hard
travel cap with no added tolerance, and travel never counts as contact or a
seated brick.

## Compatibility inventory

Recorded 2026-11-12 on the robot-side laptop with read-only inspection. No ROS
node, mock or driver was launched.

- Ubuntu 22.04.5, Python 3.10.12, ROS Humble `ros-humble-ros-base`
  0.10.0-1jammy (278 packages), `python3-colcon-common-extensions` 0.3.0,
  `vcs` 0.3.0. `rclpy`, `std_msgs`, `geometry_msgs`, `sensor_msgs`, `std_srvs`,
  `launch`, `launch_ros`, `ament_*`, `rosidl_default_generators`, `kdl_parser`
  and `tf2_*` are present.
- UR packages come from a repository-local deb overlay laid out as a prefix
  plus `env.sh`, which prepends `AMENT_PREFIX_PATH` and friends. It provides
  `ur_robot_driver` 2.15, `ur_description`, `ur_msgs`, `controller_manager`,
  `joint_trajectory_controller`, `forward_command_controller`, `ur_controllers`
  and `xacro`. Nothing is installed system-wide: `sudo` still fails with
  no-new-privileges. `pick_ik` and `kdl_parser_py` stay absent, which only
  affects `risl_ur` metadata. Source the overlay for any driver or mock work;
  the package build itself needs only base Humble.
- Verified in overlay `ur_control.launch.py`: `use_fake_hardware` exists and
  defaults to false, no `use_mock_hardware` is declared, `robot_ip` has no
  default, `use_tool_communication` defaults to false, `launch_dashboard_client`
  and `launch_rviz` default to true, and fake hardware removes
  `tcp_pose_broadcaster` from the active controllers.
- `pymodbus` and `pyserial` are absent; the RG2 library imports the 2.x
  `pymodbus.client.sync` API, so a 3.x install would break it.
- Imported repositories in `/home/kaleb/ros2_ws/src`, all `main`:
  `risl_ur` 011539ab, `risl_onrobot_ros` 7f86a05a, `risl_vention_ros`
  ac9c7da2, `risl_camera_localizer` 76b68e87, `risl_camera_msgs` 91cc701e,
  `risl_simulation` d659f7d4. Workspace repo
  `risl_assembly_workspace` 82b9a51 holds `risl_bringup` outside `src` and has
  no `.venv`; its committed `risl_ur` checkout also contains in-source
  `build/`, `install/` and `log/` artifacts.
- `risl_ur`: `compute_ik(position, rpy_deg)` returns joints or `None`;
  `MotionExecutor` owns `/joint_states`, `/tcp_pose_broadcaster/pose`, the
  controller switch, velocity and force calls. Its IK is a bounded optimizer
  (`shoulder_pan` limited to 0..pi), so candidates need FK verification and a
  warm start from the previous solution; unreachable poses are a known bound of
  this solver, not a reason to refactor upstream. Its `setup.py` entry points
  are broken: `risl_ur.testmove_ur5e` and `risl_ur.scripts.ik_solver` do not
  exist, `risl_ur/scripts` has no `__init__.py`, and `install_requires` names
  MoveIt. Only `risl_ur.custom_libraries` imports cleanly.
- `risl_onrobot_ros`: node entry `gripper_control`; `/gripper_command` plus
  `/gripper_queried_width`. Its constructor calls `ensure_socat`, which spawns
  `socat pty,link=/tmp/ttyUR ... tcp:192.168.1.111:54321`, so constructing it
  touches the robot network. Never import or instantiate it outside the robot.
- `risl_vention_ros`: entry point names
  `risl_vention_ros.vention_socket_control_node`, but the module is
  `vention_socket_control.py`; the node also hardcodes `192.168.7.2:9999`.
  Import fails and the node is out of scope.
- `risl_camera_localizer`: camera offset `[-0.012, -0.038, -0.005]` m in
  `localizer_bridge.py`; the allocation node defaults its `f_max` parameter
  (maximum allowed force) to 5.0 N.
- `risl_bringup` `cell.launch.py` hardcodes `use_mock_hardware:=false`, robot
  `192.168.1.111`, tool communication at 1000000 baud and an unconditional
  real gripper node. Driver 2.15 declares no `use_mock_hardware`, so that
  argument name is wrong for the installed launch. Never launch it here. Its
  `CMakeLists.txt` installs `launch config` while `config/` does not exist, so
  it also fails to build.
- Bota config `auxiliary/bota_socket.json` uses 460800 baud on `/dev/ttyUSB0`.
  That is a separate link from UR tool communication (1000000) and RG2 Modbus
  (115200); they are three links to reconcile, not one shared setting.

### Patch notes for the Max stack (do not apply here)

Minimal, build-only changes requested from the owners; no refactors, no
restored lock files, no geometry changes, no launcher safety changes, no
upstream writes from this branch.

- `risl_bringup`: create `config/` or drop it from `install(DIRECTORY ...)` so
  the package builds.
- `risl_vention_ros`: point the entry point at
  `risl_vention_ros.vention_socket_control:main`.
- `risl_ur`: drop the MoveIt `install_requires`, and add
  `risl_ur/scripts/__init__.py` or fix the entry-point modules.

`cell.launch.py` stays as it is and stays unused here: a real driver, an
unconditional real gripper and a hardcoded robot address are exactly why it
must not be launched on this laptop, and its `use_mock_hardware` name does not
match driver 2.15.

## Open questions

- TCP and payload: zero TCP at `tool0` is assumed; the real gripper mass,
  centre of mass, mounting offset and payload for force mode are unknown.
- Bota FT: confirm the 460800 USB setting, the driver that owns the port, and
  whether its wrench frame matches `base` before any seating work.
- Camera offset: `-0.005` m in `localizer_bridge.py` versus a previously used
  `-0.010`; which is calibrated for this cell is unknown.
- Baseplate calibration: `origin_xyz_m`, `yaw_deg` and height are config
  values, not measured against `base`.
- Force limits: the 5.0 N allocator cap is for planar pushing; a seating limit,
  deviation guard and timeout still need operator approval and FT validation.
- Gripper width: contract range 0–1100 tenths of a mm versus the 0–1000
  geometry table, and `/gripper_width` versus `/gripper_queried_width`.

## Current blockers

- Force-mode mock calls need the overlay's `ur_msgs`; without it the typed
  service cannot load. No force-mode evidence exists yet either way.
- UR driver, description and controllers exist only in the parent's overlay,
  not system-wide. The mock launch is parent-owned runtime work, not run from
  this branch.
- Fake hardware deliberately does not activate `tcp_pose_broadcaster`, so mock
  TCP feedback must be derived and labelled as derived.
- No RG2 runtime dependencies: the real gripper node cannot start, and must not
  be constructed because it spawns socat to the robot.
- Hardware seating remains blocked pending validated FT sensing and an
  operator-approved force limit.
- Root CI runs `ruff check` and `ty check` over `**.py`, which will include
  `ros2/**.py`; package code must satisfy `ruff.toml` (Google docstrings,
  annotations, no `typing.Any`/`cast`) or the parent must exclude `ros2`.
