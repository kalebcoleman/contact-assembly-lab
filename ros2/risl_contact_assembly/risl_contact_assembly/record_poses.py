"""Record taught tool poses for a positions file.

Each pose is ``tool0`` in ``base``, computed from ``/joint_states`` with the
same ``risl_ur`` kinematics the executor uses, so a recorded pose replays to
the same joint angles. The pendant TCP setting does not affect it.
"""

from pathlib import Path
from time import sleep

import rclpy
from rclpy.node import Node
from rclpy.signals import SignalHandlerOptions
from risl_ur.custom_libraries.ik_solver import dh_params, forward_kinematics
from scipy.spatial.transform import Rotation
from std_msgs.msg import String

from risl_contact_assembly.robot import RosRobot

GRIPPER_MOVE_S = 2.0


def main(args: list[str] | None = None) -> None:
    """Prompt for pose names and append each recorded pose to a YAML file.

    At the prompt, a name records the current pose as
    ``name: {xyz_m: [x, y, z], rpy_deg: [roll, pitch, yaw]}`` (metres,
    extrinsic XYZ degrees), ``open`` and ``close`` drive the gripper and print
    the width it then reports (millimetres), and ``q`` quits. The ``output``
    parameter is the file, ``recorded_poses.yaml`` by default. The terminal is
    read through ``/dev/tty`` because ``ros2 launch`` does not forward stdin.

    Args:
        args: ROS arguments.
    """
    rclpy.init(args=args, signal_handler_options=SignalHandlerOptions.NO)
    node = Node("record_poses")
    output = Path(node.declare_parameter("output", "recorded_poses.yaml").value)
    gripper = node.create_publisher(String, "/gripper_command", 10)
    robot = RosRobot(node, commands=False)
    try:
        with open("/dev/tty", "rb+", buffering=0) as terminal:
            terminal.write(
                b"\nType a pose name to record it, 'open' or 'close' for the "
                b"gripper, 'q' to quit.\n"
            )
            while True:
                terminal.write(b"pose name> ")
                name = terminal.readline().decode().strip()
                if name in ("open", "close"):
                    gripper.publish(String(data=name))
                    sleep(GRIPPER_MOVE_S)
                    gripper.publish(String(data="query"))
                    sleep(0.5)
                    terminal.write(
                        f"gripper reports {robot.gripper_width()} mm\n".encode()
                    )
                elif name == "q":
                    break
                elif name:
                    joints = robot.joints()
                    if joints is None:
                        terminal.write(b"no fresh /joint_states; not recorded\n")
                        continue
                    pose = forward_kinematics(dh_params, joints)
                    xyz_m = pose[:3, 3].round(5).tolist()
                    rpy_deg = (
                        Rotation.from_matrix(pose[:3, :3])
                        .as_euler("xyz", degrees=True)
                        .round(3)
                        .tolist()
                    )
                    entry = f"{name}: {{xyz_m: {xyz_m}, rpy_deg: {rpy_deg}}}\n"
                    with output.open("a", encoding="utf-8") as recorded:
                        recorded.write(entry)
                    terminal.write(f"saved to {output}: {entry}".encode())
    except KeyboardInterrupt:
        pass
    robot.close()
    rclpy.shutdown()
