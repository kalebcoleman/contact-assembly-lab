# ROS 2 Humble brick assembly for the UR5e

`risl_contact_assembly` builds a LEGO structure from known positions on a UR5e
with an OnRobot RG2: it grasps each brick at a taught pickup pose and seats it
on the baseplate at the position the structure file gives. It runs on the
official `ur_robot_driver` and Max Gao's `risl_ur` (kinematics) and
`risl_onrobot_ros` (gripper).

**Validated on fake hardware only; not tested on the robot.** Lab steps are in
[LAB_QUICKSTART.md](LAB_QUICKSTART.md), mock results in [evidence](evidence/README.md).

## Use

```bash
ros2 launch risl_contact_assembly assembly.launch.py robot_ip:=<ip>   # dry run
```

| Argument | Default | Effect |
|---|---|---|
| `robot_ip` | required | Robot address; the only place it is set |
| `execute` | `false` | Move the robot; without it nothing is commanded |
| `record` | `false` | Record taught poses instead |
| `auto_continue` | `false` | Offer repeat runs after one fully confirmed run |
| `positions_file` | `config/demo_positions.yaml` | Taught poses, speeds, limits |
| `structure_file` | `structures/three_bricks.json` | Any `experiments/ur5e_structures/*.json` |
| `use_fake_hardware` | `false` | Driver mock hardware and `fake_gripper` |
| `camera` | `false` | Pickup XY from `risl_camera_localizer` |
| `step_log` | none | JSON Lines record of each executed step |
| `viewer` | `false` | Read-only MuJoCo cell viewer with contact warnings |

## Conventions

- Poses are `tool0` (flange) in the UR `base` frame, metres and degrees
  (`rpy_deg` extrinsic XYZ). `base` is `base_link` turned pi about Z;
  `base_link` is never used.
- Poses are taught with the brick in the gripper and replayed through the same
  `risl_ur` kinematics, so no TCP offset or brick-to-tool calibration is
  involved and the pendant TCP stays zero.
- The baseplate is three taught poses (corner, +X, +Y). Brick targets are
  interpolated between them on the stud grid, which absorbs plate position,
  yaw and tilt.
- Gripper widths are millimetres in files and feedback, tenths of a millimetre
  on `/gripper_command`.

## Motion and safety

- Every move is a straight tool line with a trapezoidal speed profile, sent to
  `scaled_joint_trajectory_controller`. Sideways moves happen at one travel
  height; approaches and retreats are vertical.
- Speed, acceleration, press force and overtravel are capped in code
  (50 mm/s, 10 mm/s near contact, 0.25 m/s², 40 N, 2 mm). A positions file
  exceeding a cap is rejected. Joint speed above 0.5 rad/s rejects a move.
- Every target must lie in the workspace box with the tool within
  `max_tilt_deg` of straight down, checked before anything moves.
- Execution needs `execute:=true` and Enter before every step.
- A run aborts and cancels motion on Ctrl-C, a gripper width that does not
  match the brick (missed or dropped), a timeout, lost feedback, a tool outside
  the box, or contact force while descending to a pick.
- Placing descends at contact speed until the taught height or until the tool
  force changes by `press_force_n`, whichever comes first.

## Camera hook

`camera:=true` starts Max's localizer and replaces each taught pickup XY with
the pose on `/vision/object_poses/<brick name>` (frame `base`), refusing shifts
over 30 mm. Height and orientation stay as taught. The localizer has no LEGO
brick model yet, so this path is untested.

## Cell viewer

`viewer:=true`, or `mock_viewer.launch.py` for fake hardware, runs Max's
`risl_simulation` viewer with the Vention bench from `scene/cell.xml` and
reports contacts between the arm and the cell. `scene/convert_cell.py`
regenerates the cell from the lab's `vention.usd` (one box per part; the USD
and its meshes are not redistributable and are not in this repository).
The bench pose is taken from the Isaac twin and has not been measured.

## Build and test

Needs `ur_robot_driver`, `risl_ur`, NumPy, SciPy and PyYAML on Python 3.10.
The viewer and its tests also need `risl_simulation`, `mujoco` and `trimesh`.

```bash
colcon build --base-paths ros2
colcon test --base-paths ros2 && colcon test-result --verbose
```
