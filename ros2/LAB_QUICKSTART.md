# Lab quickstart: UR5e + RG2 brick assembly

Validated on fake hardware only. Nothing here has run on the real robot yet, so
keep a hand on the e-stop for every first.

## 0. Once, before the lab (this laptop)

The UR driver, `socat` and `pymodbus` are not installed system-wide yet.

```bash
sudo apt install ros-humble-ur-robot-driver socat
python3 -m pip install --user pymodbus==2.5.3   # risl_onrobot_ros needs exactly 2.5.3
ln -s <this repo>/ros2/risl_contact_assembly ~/ros2_ws/src/
cd ~/ros2_ws && source /opt/ros/humble/setup.bash
colcon build --packages-select risl_ur risl_onrobot_ros risl_contact_assembly
```

Use the system Python 3.10, not the simulator's virtual environment.

## 1. Network

The robot in Max's cell is at `192.168.1.111/24` (pendant: Settings > System >
Network). `risl_onrobot_ros` always reaches the gripper at that address, so the
robot must keep it. Give the laptop a static address on the same subnet:

```bash
nmcli device status                       # find the wired interface
sudo nmcli con add type ethernet ifname <iface> con-name ur-lab \
  ipv4.method manual ipv4.addresses 192.168.1.100/24 ipv6.method disabled
sudo nmcli con up ur-lab
ping -c 3 192.168.1.111
```

Netplan equivalent, in `/etc/netplan/01-ur-lab.yaml`, then `sudo netplan apply`:

```yaml
network:
  version: 2
  ethernets:
    <iface>:
      addresses: [192.168.1.100/24]
```

If `ufw` is on, let the robot call back:
`sudo ufw allow from 192.168.1.111 to any port 50001:50004 proto tcp`.

## 2. Pendant

- **External Control URCap** (Installation > URCaps > External Control): Host IP
  = the laptop address (`192.168.1.100`), Custom port = `50002`. The program is
  a single External Control node.
- **TCP** (Installation > General > TCP): leave X, Y, Z, RX, RY, RZ at zero.
  Every pose here is the flange (`tool0`) taught with the brick in the gripper,
  and Max's camera localizer also assumes a zero TCP.
- **Payload** (Installation > General > Payload): mass and centre of gravity of
  everything on the flange (RG2 plus camera and bracket). Use the pendant's
  payload measurement, or the RG2 datasheet values if only the RG2 is mounted.
  A wrong payload corrupts the force reading that limits pressing.
- **Tool I/O**: leave as the cell is configured (RS-485 forwarded on port 54321).
- **Speed slider**: 100 % runs the planned speeds (50 mm/s, 5 mm/s near
  contact). The code never goes faster; the slider only slows it. Use 50 % for
  the first run. Below 10 % the executor refuses to move.

## 3. Commands, in order

```bash
source /opt/ros/humble/setup.bash && source ~/ros2_ws/install/setup.bash
export ROS_LOCALHOST_ONLY=1
L="ros2 launch risl_contact_assembly assembly.launch.py robot_ip:=192.168.1.111"
P="positions_file:=$HOME/lab_positions.yaml"
S="structure_file:=<this repo>/experiments/ur5e_structures/tower.json"
```

Each command starts the driver and gripper, does one job, and exits.

1. `$L record:=true` records positions (section 4). The pendant program stays
   stopped so freedrive works.
2. Copy `config/demo_positions.yaml` to `~/lab_positions.yaml` and paste in the
   recorded poses.
3. `$L $P $S` is the **dry run**: it checks every limit, plans every move from
   where the arm is now, prints the steps and commands nothing. Jog the arm
   inside the workspace box with the tool pointing down first.
4. `$L $P $S execute:=true` runs it. When it prints "waiting for the External
   Control program", press Play on the pendant. Each step then waits for Enter;
   Ctrl-C stops the arm and exits.
5. `$L $P $S execute:=true auto_continue:=true` does the same and, after that
   fully confirmed run, offers repeat runs that need one Enter each.

Start with `single.json`. A run with no brick at the pickup is a safe first
motion test: it moves above the pickup, descends and aborts at the grasp.

## 4. Recording positions

At the `pose name>` prompt, a name saves the current flange pose to
`recorded_poses.yaml`; `open` and `close` drive the gripper and print the width
it reports; `q` quits.

1. Seat a 2x4 brick on the plate corner the structure counts studs from, long
   side along the plate's +X edge. `open`, freedrive the fingers around its
   short side just above the studs, `close` while holding freedrive so the arm
   centres itself, then record `origin`.
2. Move the brick 16 studs along +X and record `x_corner`; move it 18 studs
   along +Y from the corner and record `y_corner`. Other distances are fine if
   `x_corner_studs` and `y_corner_studs` match; farther is more accurate.
3. Put each brick where it will wait, grip it the same way (short side, same
   height on the brick) and record it under its name in the structure file,
   for example `tower_0`. A second baseplate as a pickup jig keeps this
   repeatable.
4. With the gripper closed on a 2-stud-wide brick, note the reported width and
   set `gripper.width_offset_mm` to that minus 15.8.

Keep the arm in one posture (elbow up, wrist not flipped) for every pose and
for the start of a run. Loading fails if the three plate poses disagree with
the stud grid by more than 1.5 mm or 1 degree: re-record them.

## 5. Set or measure before the first real move

- Every pose in the positions file; the shipped values are placeholders.
- `safety.workspace_min_m` / `workspace_max_m`: floor 2 mm below the lowest
  recorded pose, ceiling above the travel height the dry run prints.
- `gripper.width_offset_mm` (step 4 above).
- `safety.press_force_n` (20 N) and `press_overtravel_m` (0.5 mm) are
  untested guesses. Start low; the log reports how far above the taught height
  each place stopped.
- Payload, zero TCP, External Control host address and speed slider (section 2).
- Section 0 installs.

## Rehearse without the robot

```bash
ros2 launch risl_contact_assembly assembly.launch.py robot_ip:=0.0.0.0 \
  use_fake_hardware:=true                  # add execute:=true or record:=true
```

Nothing connects to `robot_ip` on fake hardware.

## Watch it in the work cell (MuJoCo)

Once: `python3 -m pip install --user mujoco 'trimesh<4'`, and add
`risl_camera_msgs risl_camera_localizer risl_simulation` to the `colcon build`
in section 0.

```bash
ros2 launch risl_contact_assembly mock_viewer.launch.py $P $S   # fake hardware, arm moves
$L $P $S viewer:=true                                           # real robot, read-only mirror
```

Max's viewer opens with the Vention bench around the arm. It warns `CONTACT`
whenever the arm or gripper body comes within 10 mm of the cell or a finger
touches it, prints a summary at the end and exits with status 1 if there was
any. `contact_report:=<file>` saves the summary.

The bench pose comes from the lab's Isaac twin CAD, not from a measurement.
Check two things before trusting a clean report:

- The green baseplate (drawn from your recorded poses) must rest on the
  tabletop. The CAD puts the tabletop 85.5 mm below the robot base. If the
  plate floats or sinks, correct it with `bench_offset_m:="[0.0, 0.0, <dz>]"`.
- The robot rides the Vention linear axis and the CAD has it mid-rail. With
  the carriage `d` metres along `base` +X from there, pass
  `bench_offset_m:="[<-d>, 0.0, 0.0]"`.

Each Vention part is a bounding box, the RG2 is schematic and the carried
brick is not drawn.
