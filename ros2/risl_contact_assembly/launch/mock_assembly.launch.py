"""Launch an isolated UR5e mock driver with the fake gripper and joint-state recorder.

The arm is the official ur_robot_driver GenericSystem selected by use_fake_hardware
(Humble 2.15), so joint states and FollowJointTrajectory come from ros2_control.
fake_gripper replaces only the serial OnRobot gripper. Never launch cell.launch.py,
rg_gripper, or any serial or network gripper. Controller poses use base, not base_link
(a pi rotation about Z), and this launch adds no frame conversion. With fake hardware
the driver omits tcp_pose_broadcaster; any mock TCP pose must be FK-derived and labeled
derived, not sensor evidence. Emulated widths and joint traces are not physical force or
contact evidence. Physical seating stays blocked until sensing and limits are validated
and an operator approves force and pass/fail values.
"""

from launch import LaunchDescription
from launch.actions import (
    DeclareLaunchArgument,
    IncludeLaunchDescription,
    SetEnvironmentVariable,
)
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch_ros.actions import Node
from launch_ros.substitutions import FindPackageShare

MOCK_DRIVER_ARGUMENTS = {
    'ur_type': 'ur5e',
    'robot_ip': '127.0.0.1',
    'use_fake_hardware': 'true',
    'use_tool_communication': 'false',
    'launch_dashboard_client': 'false',
    'launch_rviz': 'false',
}


def generate_launch_description() -> LaunchDescription:
    """Build the mock-only arm, fake gripper, and recorder launch description."""
    return LaunchDescription([
        SetEnvironmentVariable('ROS_LOCALHOST_ONLY', '1'),
        SetEnvironmentVariable('ROS_DOMAIN_ID', '83'),
        DeclareLaunchArgument(
            'joint_states_file',
            default_value='/tmp/risl_contact_assembly_joint_states.jsonl',
            description='JSON Lines destination for recorded /joint_states samples.',
        ),
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(
                PathJoinSubstitution([
                    FindPackageShare('ur_robot_driver'),
                    'launch',
                    'ur_control.launch.py',
                ])
            ),
            launch_arguments=tuple(MOCK_DRIVER_ARGUMENTS.items()),
        ),
        Node(
            package='risl_contact_assembly',
            executable='record_joint_states',
            name='record_joint_states',
            output='screen',
            parameters=[{
                'joint_states_file': LaunchConfiguration('joint_states_file'),
            }],
        ),
        Node(
            package='risl_contact_assembly',
            executable='fake_gripper',
            name='fake_gripper',
            output='screen',
        ),
    ])
