# ROS 2 Humble brick assembly for the UR5e

Builds a LEGO structure from known positions on a UR5e with an OnRobot RG2:
each brick is grasped at a taught pickup pose and seated on the baseplate where
the structure file puts it.

**Validated on fake hardware only; not tested on the robot.** For the real
robot follow [LAB_QUICKSTART.md](LAB_QUICKSTART.md).

## What is here

```text
ros2/
  README.md                  this file
  LAB_QUICKSTART.md          real-robot bring-up, step by step
  risl.repos                 Max Gao's repositories for `vcs import`
  evidence/                  results of the fake-hardware runs
  risl_contact_assembly/     the package
    config/demo_positions.yaml   example taught poses, speeds and limits
    structures/                  two small structures to build
    scene/                       MuJoCo work cell and the script that converts it
    launch/                      assembly.launch.py, mock_viewer.launch.py
    risl_contact_assembly/       planner, motion, executor, recorder, viewer
    test/
```

## Max's stack

None of Max Gao's code is copied here. `risl.repos` lists his repositories at
the commits these results were produced with, and `vcs import` clones them
next to this package.

| Repository | Used for |
|---|---|
| `risl_ur` | UR5e DH kinematics (forward kinematics, Jacobian) and the RG2 fingertip reach table |
| `risl_onrobot_ros` | RG2 driver node: `/gripper_command`, `/gripper_queried_width` |
| `risl_simulation` | MuJoCo viewer that mirrors joint states; `cell_viewer` extends it |
| `risl_camera_localizer`, `risl_camera_msgs` | optional camera poses on `/vision/object_poses/<name>`; object models the viewer loads |

The arm is driven through the official `ur_robot_driver`.

## Set up, build, test

Use the system Python 3.10.

```bash
sudo apt install ros-humble-ur-robot-driver python3-vcstool
python3 -m pip install --user mujoco 'trimesh<4'     # viewer only

mkdir -p ~/ros2_ws/src && cd ~/ros2_ws
ln -s <this repo>/ros2/risl_contact_assembly src/
vcs import src < <this repo>/ros2/risl.repos

source /opt/ros/humble/setup.bash
colcon build --packages-up-to risl_contact_assembly
source install/setup.bash
colcon test --packages-select risl_contact_assembly && colcon test-result --verbose
```

Without MuJoCo the four viewer tests are skipped and the rest still run.

## Mock run

Nothing connects to a robot with `use_fake_hardware:=true`; `robot_ip` is
required but unused.

```bash
L="ros2 launch risl_contact_assembly assembly.launch.py robot_ip:=0.0.0.0 use_fake_hardware:=true"
$L                   # dry run: plans every move, prints the steps, commands nothing
$L execute:=true     # mock arm moves; press Enter before each step
$L record:=true      # pose recorder
```

`positions_file:=` and `structure_file:=` choose the taught poses and the
structure (any `experiments/ur5e_structures/*.json`); the defaults are the
example poses and a three-brick tower.
Add `--show-args` to the launch command to list every argument.

## MuJoCo work-cell viewer

```bash
ros2 launch risl_contact_assembly mock_viewer.launch.py    # fake hardware, arm moves
```

Max's viewer opens with the lab's Vention bench around the arm. It only
subscribes, so `viewer:=true` on `assembly.launch.py` also mirrors the real
robot. It warns `CONTACT` when the arm or gripper body comes within 10 mm of
the cell or a finger touches it, prints a summary at the end and exits with
status 1 if there was any contact.

The bench is one box per Vention part, converted from the lab's `vention.usd`
by `scene/convert_cell.py`; the USD itself is not redistributable and is not
in this repository. Its pose comes from the Isaac twin and has not been
measured: see the checks in [LAB_QUICKSTART.md](LAB_QUICKSTART.md).

## How it behaves

- Poses are the flange (`tool0`) in the UR `base` frame, metres and degrees,
  taught with the brick in the gripper. No TCP offset is involved.
- Every move is a straight tool line; sideways moves happen at one travel
  height and approaches are vertical. Speed is capped in code at 50 mm/s, and
  10 mm/s near contact.
- Motion needs `execute:=true` and Enter before every step. A run aborts on
  Ctrl-C, an unexpected gripper width, a timeout, lost feedback, a target or
  tool outside the workspace box, or contact while picking.
