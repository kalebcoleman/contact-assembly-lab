"""Rehearse an assembly on fake hardware inside the MuJoCo work cell.

Runs ``assembly.launch.py`` with fake hardware and the cell viewer. Nothing
connects to a robot. ``execute`` defaults to true here so the mock arm moves;
``execute:=false`` shows the start pose and the dry-run plan only. Every other
``assembly.launch.py`` argument passes through.
"""

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch_ros.substitutions import FindPackageShare


def generate_launch_description() -> LaunchDescription:
    """Build the fake-hardware rehearsal with the cell viewer.

    Returns:
        The included assembly launch with fake hardware and the viewer on.
    """
    return LaunchDescription(
        [
            DeclareLaunchArgument("execute", default_value="true"),
            IncludeLaunchDescription(
                PythonLaunchDescriptionSource(
                    PathJoinSubstitution(
                        [
                            FindPackageShare("risl_contact_assembly"),
                            "launch",
                            "assembly.launch.py",
                        ]
                    )
                ),
                launch_arguments={
                    "robot_ip": "unused",
                    "use_fake_hardware": "true",
                    "viewer": "true",
                    "execute": LaunchConfiguration("execute"),
                }.items(),
            ),
        ]
    )
