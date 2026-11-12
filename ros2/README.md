# ROS 2 Humble mock assembly

`risl_contact_assembly` converts the existing structure JSON files into TCP
steps in UR `base`. It defaults to a dry run that validates and logs the plan
without constructing control endpoints. Physical execution is disabled.

The standalone launch runs the official UR5e driver with
`use_fake_hardware:=true`, `robot_ip:=127.0.0.1`, tool communication and dashboard
disabled, `ROS_LOCALHOST_ONLY=1`, and `ROS_DOMAIN_ID=83`. Driver 2.15.0 uses
**`use_fake_hardware`**, not `use_mock_hardware`. Never launch the Max cell,
real RG2 or Vention nodes for this task. The real RG2 constructor starts socat.

## Build and test

Use system Python 3.10 with Humble, not the simulator's Python 3.12 environment.
Source your Humble installation, official UR dependencies and `risl_ur` overlay.
This machine uses an extracted-deb overlay and a private build of the unchanged
Max Python package; no system installation or Max repository patch was needed:

```bash
source .agents/private-plans/ros-overlay/env.sh
source .agents/private-plans/max-install/local_setup.bash
colcon --log-base .agents/private-plans/ros-log build --base-paths ros2 \
  --build-base .agents/private-plans/ros-build \
  --install-base .agents/private-plans/ros-install
source .agents/private-plans/ros-install/local_setup.bash
python3 -m pytest ros2/risl_contact_assembly/test -q
colcon --log-base .agents/private-plans/ros-log test --base-paths ros2 \
  --build-base .agents/private-plans/ros-build \
  --install-base .agents/private-plans/ros-install
colcon --log-base .agents/private-plans/ros-log test-result --verbose \
  --test-result-base .agents/private-plans/ros-build
```

Private overlay paths are local validation artifacts, not distributed dependencies.
On another Humble host, source installed `ur_robot_driver`, `ur_description`,
`controller_manager`, `control_msgs`, `ur_msgs`, `xacro` and `risl_ur` instead.
The package also requires PyYAML, NumPy and SciPy. `--log-base` precedes the
colcon verb; build/install/test-result bases follow it where supported.

## Rehearse the fixtures

The launch defaults to the installed single-brick fixture and config:

```bash
export ROS_LOCALHOST_ONLY=1 ROS_DOMAIN_ID=83
ros2 launch risl_contact_assembly mock_assembly.launch.py \
  dry_run:=true step_log:=/tmp/single-steps.jsonl \
  joint_states_file:=/tmp/single-joints.jsonl
```

For three bricks, additionally pass an absolute path:

```bash
ros2 launch risl_contact_assembly mock_assembly.launch.py \
  structure_file:="$PWD/ros2/risl_contact_assembly/fixtures/three_bricks.json" \
  dry_run:=true step_log:=/tmp/three-steps.jsonl \
  joint_states_file:=/tmp/three-joints.jsonl
```

The executor exits after writing 10 or 30 `planned` records. Stop the remaining
mock launch with Ctrl-C. Logs append, so use a fresh step-log path per run.
`run_executor:=false` starts only the mock driver, fake gripper and recorder.
The executor can also run separately with `ros2 run risl_contact_assembly
assembly_executor --ros-args -p config_file:=... -p structure_file:=...`.

Optional `dry_run:=false mock_execution:=true` enables mock trajectory attempts.
Before constructing control endpoints, the executor requires localhost domain 83,
queries the live hardware class and robot description for `GenericSystem`, and
checks that gripper subscribers belong to `fake_gripper`. An arbitrary proof file
cannot authorize live ROS execution. `confirm_each_step` defaults to true;
interactive execution should use a separate terminal (`ros2 run`), while automated
mock tests must explicitly set it false. A non-dry run without mock mode is refused.

The supplied geometry is an uncalibrated rehearsal fixture, **not a demonstrated
reachable motion setup**. Moving trajectories have not been validated by the
committed dry-run evidence. Workspace, IK, feedback and deadline failures abort;
no force-mode start request is issued. Mock seating is labelled emulated and
never interpreted as contact or successful physical insertion.

## Poses and planning

`load_config`, `load_structure`, and `plan_structure` are exported by the package.
The planner emits ten actions per brick: approach, descend, close, lift,
transfer, approach_target, slow_descend, seat, open, retreat. Each step contains
`brick_id`, `xyz_m`, `rpy_deg`, `speed_m_s`, and optional `gripper_width_mm`.

- Positions: TCP in `base`, metres. `base_link` differs by pi about Z.
- Rotation: extrinsic XYZ Euler angles in degrees, `Rz(yaw) Ry(pitch) Rx(roll)`.
- Gripper width: millimetres in config; integer tenths of a millimetre on the wire.
- Brick dimensions: `[L,W,H]`, stud units for L/W, plate units for H; H must be 3.
- Plate: 20×20×1, stud pitch 0.008 m, plate height 0.0032 m, brick height 0.0096 m.

`baseplate.origin_xyz_m` is its bottom-face centre in `base`; `yaw_deg` rotates
the plate grid. Support indices refer only to earlier bricks. Placement offsets
are in the support grid, while local quarter-turn yaws accumulate along supports.
For support/child sizes Ls,Ws/Lb,Wb and stud pitch U:

    p_child = p_support + R_support * (
        [-Ls*U/2 + ox*U, -Ws*U/2 + oy*U, support_height]
        + R_local * [Lb*U/2, Wb*U/2, 0])

`pickup.xyz_m/rpy_deg` is an **absolute fixture TCP pose**. Target TCP is
`T_base_brick @ T_brick_tcp`; the mandatory calibration fields are
`calibration.brick_to_tcp_xyz_m` (translation in brick axes from bottom centre)
and `calibration.brick_to_tcp_rpy_deg`. Zero pendant TCP offset is assumed.
Simulation `baseplate_xy_m` and `brick_positions_xy_m` are stage coordinates and
are ignored. Simulation grasp offsets, press depths and release settings are
not applied as hardware calibration. The single fixture copies `single.json`;
the three-brick fixture takes the first three bricks of `tower.json`.

Every planned pose, including hover, is checked against the workspace AABB.
Configured speeds are multiplied by `max_speed_scale` once and rejected if over
the cap. Runtime `speed_scale` is an additional explicit derating. `seating.force_n`
is a requested force, **not a measured force limit**; no force is applied here.
`max_travel_m` is a hard cap with no extra allowance. Watchdogs use monotonic time.

## Interfaces and limitations

| Interface | Type / meaning |
|---|---|
| `/gripper_command` | String: `open`, `close`, `query`, or 0–1100 tenths mm |
| `/gripper_queried_width` | Float64: fake width in mm |
| `/joint_states` | JointState: official mock feedback |
| `/scaled_joint_trajectory_controller/follow_joint_trajectory` | Standard FollowJointTrajectory action |

The driver omits `tcp_pose_broadcaster` in fake mode. The executor derives nominal
`base → tool0` from joint feedback and Max FK; this is not measured contact data.
IK candidates are warm-started and checked with FK before sending a goal. Motion
uses position-only joint interpolation, a conservative TCP speed-duration bound,
sampled workspace checks and live feedback guards. These checks do not establish
continuous collision avoidance, physical stopping distance or hardware safety.

Nominal FK matched the official URDF at two independently checked joint poses.
The optimizer limits shoulder pan to 0..pi and may return inaccurate candidates;
its return value alone is not a success signal. No upstream IK changes were made.

## Validation evidence

See [evidence/README.md](evidence/README.md) for commands, outcomes and limits.
Dry-run logs demonstrate plan rehearsal, not moving trajectory execution or
physical insertion. Mock gripper width is not grasp or force evidence.
The [research launch incident](evidence/research-launch-incident.md) records the
unauthorized attempt, the wrong mock flag and the recovered validation-error log.

## Unverified lab calibration and future operator gates

These stages are not authorized by this package. A named operator must be
physically at the e-stop for each stage, approve limits and stop criteria, and
inspect the result before advancing. No numeric mock defaults are validated limits.

| Stage | Pass criterion | Stop criterion |
|---|---|---|
| Reduced-speed motion without bricks | Calibrated TCP follows approved clear path | Unexpected motion, error beyond approved tolerance, contact |
| Gripper only with arm parked | Width feedback matches approved commands | Missing feedback, uncommanded motion or contact |
| One brick | Validated grasp, sensed seat and clean release | Slip, force/travel limit, timeout or failed seating |
| Small structure | Every placement passes the one-brick criteria | Any joint loss, collapse or force excursion |

Hardware seating remains blocked until sensing, limits and stop behavior are validated.
Unverified calibration and configuration:

- Pendant TCP, RG2 mounting transform, payload mass and centre of gravity.
- Bota driver, wrench frame, calibration and measured force limits; Bota USB 460800
  baud is distinct from UR tool-port 1000000 and RG2 Modbus 115200.
- Camera offset z: localizer −0.005 m versus simulation −0.010 m.
- Physical baseplate datum, yaw, stud phase, tilt, and fixture-to-TCP calibration.
- Permitted seating force, travel, timeout, contact detection and release clearance.
- Width-dependent fingertip reach: protocol allows 110 mm, geometry table ends at 100 mm.

Local compatibility findings: `risl_bringup` installs a nonexistent config directory;
Vention and two `risl_ur` entry points are mismatched. Those nodes are unused here.
The imported Max packages and their repositories remain unchanged.
