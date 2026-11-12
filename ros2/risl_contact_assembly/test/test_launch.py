"""Tests for the launch file, the fake gripper and the no-hardcoded-address rule."""

import re
from pathlib import Path
from runpy import run_path

import pytest
import rclpy
from launch import LaunchContext
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.utilities import normalize_to_list_of_substitutions, perform_substitutions
from risl_contact_assembly.fake_gripper import FakeGripper
from std_msgs.msg import Float64, String

PACKAGE = Path(__file__).resolve().parents[1]


def launch_entities() -> list:
    """Load the launch description.

    Returns:
        Top-level launch entities.
    """
    launch_file = run_path(str(PACKAGE / "launch" / "assembly.launch.py"))
    return launch_file["generate_launch_description"]().entities


def test_robot_address_is_only_a_launch_argument() -> None:
    """``robot_ip`` has no default and no source file contains an IPv4 address."""
    arguments = {
        entity.name: entity
        for entity in launch_entities()
        if isinstance(entity, DeclareLaunchArgument)
    }
    assert arguments["robot_ip"].default_value is None
    context = LaunchContext()
    assert perform_substitutions(context, arguments["execute"].default_value) == "false"
    assert (
        perform_substitutions(context, arguments["use_fake_hardware"].default_value)
        == "false"
    )
    address = re.compile(r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b")
    for path in PACKAGE.rglob("*"):
        if (
            path.suffix in (".py", ".yaml", ".json", ".xml")
            and "test" not in path.parts
        ):
            assert not address.search(path.read_text(encoding="utf-8")), path


@pytest.mark.parametrize(
    ("fake", "tool_communication"), [("true", "false"), ("false", "true")]
)
def test_tool_socket_is_off_on_fake_hardware(
    fake: str, tool_communication: str
) -> None:
    """The driver's tool forwarder, which dials the robot, follows real hardware."""
    (driver,) = (
        entity
        for entity in launch_entities()
        if isinstance(entity, IncludeLaunchDescription)
    )
    context = LaunchContext()
    context.launch_configurations["use_fake_hardware"] = fake
    context.launch_configurations["robot_ip"] = "unused"
    arguments = {
        name: perform_substitutions(context, normalize_to_list_of_substitutions(value))
        for name, value in driver.launch_arguments
    }
    assert arguments["use_fake_hardware"] == fake
    assert arguments["use_tool_communication"] == tool_communication
    assert arguments["ur_type"] == "ur5e"


@pytest.mark.parametrize(
    ("object_width_mm", "command", "expected_mm"),
    [
        (0.0, "open", 110.0),
        (0.0, "close", 0.0),
        (0.0, "238", 23.8),
        (15.8, "118", 15.8),
        (15.8, "close", 15.8),
        (15.8, "238", 23.8),
        (0.0, "2000", 110.0),
    ],
)
def test_fake_gripper_reports_millimetres_for_tenths(
    monkeypatch: pytest.MonkeyPatch,
    object_width_mm: float,
    command: str,
    expected_mm: float,
) -> None:
    """Commands are tenths of a millimetre, reports millimetres, bricks block."""
    rclpy.init(args=["--ros-args", "-p", f"object_width_mm:={object_width_mm}"])
    try:
        gripper = FakeGripper()
        reports: list[Float64] = []
        monkeypatch.setattr(gripper.width_publisher, "publish", reports.append)
        gripper.on_command(String(data=command))
        gripper.on_command(String(data="query"))
        assert [report.data for report in reports] == [expected_mm, expected_mm]
    finally:
        rclpy.shutdown()
