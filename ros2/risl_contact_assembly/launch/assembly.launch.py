"""Bring up the UR5e driver and gripper, then dry-run, execute or record.

One command per task; the launch exits when the task ends:

- default: dry run, plans every move and commands nothing;
- ``execute:=true``: run the assembly with per-step confirmation;
- ``record:=true``: record taught tool poses.

``use_fake_hardware:=true`` replaces the robot with the driver's mock hardware
and the RG2 with ``fake_gripper``; nothing then connects to ``robot_ip``. The
mock arm starts straight up, so it is first driven to ``FAKE_START_JOINTS_RAD``,
standing in for the operator jogging the real arm over the table.
"""

from launch import LaunchDescription
from launch.actions import (
    DeclareLaunchArgument,
    EmitEvent,
    ExecuteProcess,
    GroupAction,
    IncludeLaunchDescription,
    RegisterEventHandler,
)
from launch.conditions import IfCondition, UnlessCondition
from launch.event_handlers import OnProcessExit
from launch.events import Shutdown
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import (
    LaunchConfiguration,
    NotSubstitution,
    PathJoinSubstitution,
)
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue
from launch_ros.substitutions import FindPackageShare

# Shoulder pan, shoulder lift, elbow, wrist 1, wrist 2, wrist 3.
FAKE_START_JOINTS_RAD = [1.5708, -1.3963, 1.5708, -1.7453, -1.5708, 0.0]
JOINT_NAMES = [
    "shoulder_pan_joint",
    "shoulder_lift_joint",
    "elbow_joint",
    "wrist_1_joint",
    "wrist_2_joint",
    "wrist_3_joint",
]


def generate_launch_description() -> LaunchDescription:
    """Build the bring-up for real or fake hardware.

    Returns:
        Driver, gripper, optional camera localizer and the task node.
    """
    share = FindPackageShare("risl_contact_assembly")
    fake = LaunchConfiguration("use_fake_hardware")
    record = LaunchConfiguration("record")
    executor = Node(
        package="risl_contact_assembly",
        executable="assembly_executor",
        output="screen",
        condition=UnlessCondition(record),
        parameters=[
            {
                "positions_file": LaunchConfiguration("positions_file"),
                "structure_file": LaunchConfiguration("structure_file"),
                "step_log": LaunchConfiguration("step_log"),
                "execute": ParameterValue(
                    LaunchConfiguration("execute"), value_type=bool
                ),
                "auto_continue": ParameterValue(
                    LaunchConfiguration("auto_continue"), value_type=bool
                ),
                "camera": ParameterValue(
                    LaunchConfiguration("camera"), value_type=bool
                ),
                "fake_hardware": ParameterValue(fake, value_type=bool),
            }
        ],
    )
    recorder = Node(
        package="risl_contact_assembly",
        executable="record_poses",
        output="screen",
        condition=IfCondition(record),
        parameters=[{"output": LaunchConfiguration("recorded_poses_file")}],
    )
    # Retried because the goal is rejected until the controller is active.
    fake_start = ExecuteProcess(
        cmd=[
            "until ros2 action send_goal"
            " /scaled_joint_trajectory_controller/follow_joint_trajectory"
            " control_msgs/action/FollowJointTrajectory"
            f" '{{trajectory: {{joint_names: {JOINT_NAMES}, points: [{{positions:"
            f" {FAKE_START_JOINTS_RAD}, time_from_start: {{sec: 8}}}}]}}}}'"
            " | grep -q SUCCEEDED; do sleep 1; done"
        ],
        shell=True,
        output="log",
        condition=IfCondition(fake),
    )
    return LaunchDescription(
        [
            DeclareLaunchArgument(
                "robot_ip", description="Robot address; unused with fake hardware."
            ),
            DeclareLaunchArgument("use_fake_hardware", default_value="false"),
            DeclareLaunchArgument(
                "execute",
                default_value="false",
                description="Command the robot. The default is a dry run.",
            ),
            DeclareLaunchArgument(
                "record",
                default_value="false",
                description="Record taught poses instead of running the assembly.",
            ),
            DeclareLaunchArgument(
                "auto_continue",
                default_value="false",
                description="Offer repeat runs after one fully confirmed run.",
            ),
            DeclareLaunchArgument(
                "camera",
                default_value="false",
                description="Take pickup XY from risl_camera_localizer.",
            ),
            DeclareLaunchArgument(
                "positions_file",
                default_value=PathJoinSubstitution(
                    [share, "config", "demo_positions.yaml"]
                ),
            ),
            DeclareLaunchArgument(
                "structure_file",
                default_value=PathJoinSubstitution(
                    [share, "structures", "three_bricks.json"]
                ),
            ),
            DeclareLaunchArgument("step_log", default_value=""),
            DeclareLaunchArgument(
                "recorded_poses_file", default_value="recorded_poses.yaml"
            ),
            DeclareLaunchArgument(
                "fake_object_width_mm",
                default_value="15.8",
                description="Brick width the fake gripper closes on; 0 is empty.",
            ),
            IncludeLaunchDescription(
                PythonLaunchDescriptionSource(
                    PathJoinSubstitution(
                        [
                            FindPackageShare("ur_robot_driver"),
                            "launch",
                            "ur_control.launch.py",
                        ]
                    )
                ),
                launch_arguments={
                    "ur_type": "ur5e",
                    "robot_ip": LaunchConfiguration("robot_ip"),
                    "use_fake_hardware": fake,
                    "launch_rviz": "false",
                    "launch_dashboard_client": "false",
                    # RG2 on the tool connector, as in risl_bringup cell.launch.py.
                    # The driver's tool forwarder opens a socket to the robot, so
                    # it stays off on fake hardware.
                    "use_tool_communication": NotSubstitution(fake),
                    "tool_voltage": "24",
                    "tool_baud_rate": "1000000",
                    "tool_parity": "2",
                    "tool_stop_bits": "1",
                    "tool_rx_idle_chars": "1.5",
                    "tool_tx_idle_chars": "3.5",
                }.items(),
            ),
            Node(
                package="risl_onrobot_ros",
                executable="gripper_control",
                output="screen",
                condition=UnlessCondition(fake),
                parameters=[{"feedback_rate": 5.0}],
            ),
            Node(
                package="risl_contact_assembly",
                executable="fake_gripper",
                output="screen",
                condition=IfCondition(fake),
                parameters=[
                    {
                        "object_width_mm": ParameterValue(
                            LaunchConfiguration("fake_object_width_mm"),
                            value_type=float,
                        )
                    }
                ],
            ),
            Node(
                package="risl_camera_localizer",
                executable="localize",
                output="screen",
                condition=IfCondition(LaunchConfiguration("camera")),
            ),
            GroupAction([executor, recorder], condition=UnlessCondition(fake)),
            fake_start,
            RegisterEventHandler(
                OnProcessExit(target_action=fake_start, on_exit=[executor, recorder])
            ),
            RegisterEventHandler(
                OnProcessExit(
                    target_action=executor, on_exit=[EmitEvent(event=Shutdown())]
                )
            ),
            RegisterEventHandler(
                OnProcessExit(
                    target_action=recorder, on_exit=[EmitEvent(event=Shutdown())]
                )
            ),
        ]
    )
