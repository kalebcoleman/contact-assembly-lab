"""Verify the mock-only launch, in-process fake gripper, and joint-state recorder."""

from importlib.util import module_from_spec, spec_from_file_location
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from launch.actions import (
    DeclareLaunchArgument,
    IncludeLaunchDescription,
    SetEnvironmentVariable,
)
from launch_ros.actions import Node
import pytest
from sensor_msgs.msg import JointState
from std_msgs.msg import Float64, String

from risl_contact_assembly.fake_gripper import FakeGripper
from risl_contact_assembly.record_joint_states import JointStateRecorder

LAUNCH_PATH = Path(__file__).parents[1] / 'launch' / 'mock_assembly.launch.py'
LAUNCH_SPEC = spec_from_file_location('mock_assembly_launch', LAUNCH_PATH)
assert LAUNCH_SPEC is not None and LAUNCH_SPEC.loader is not None
MOCK_LAUNCH = module_from_spec(LAUNCH_SPEC)
LAUNCH_SPEC.loader.exec_module(MOCK_LAUNCH)


def test_launch_pins_mock_hardware_loopback_and_isolated_domain():
    """The driver include is mock-only and cannot be overridden by launch arguments."""
    description = MOCK_LAUNCH.generate_launch_description()
    declared = {
        action.name for action in description.entities
        if isinstance(action, DeclareLaunchArgument)
    }
    assert declared == {'joint_states_file'}
    environment = {
        action.name[0].text: action.value[0].text
        for action in description.entities
        if isinstance(action, SetEnvironmentVariable)
    }
    assert environment == {'ROS_LOCALHOST_ONLY': '1', 'ROS_DOMAIN_ID': '83'}
    includes = [
        action for action in description.entities
        if isinstance(action, IncludeLaunchDescription)
    ]
    assert len(includes) == 1
    assert dict(includes[0].launch_arguments) == {
        'ur_type': 'ur5e',
        'robot_ip': '127.0.0.1',
        'use_fake_hardware': 'true',
        'use_tool_communication': 'false',
        'launch_dashboard_client': 'false',
        'launch_rviz': 'false',
    }
    assert 'use_mock_hardware' not in dict(includes[0].launch_arguments)
    assert 'ur_control.launch.py' in str(includes[0].launch_description_source.location)


def test_launch_starts_only_fake_gripper_and_recorder_nodes():
    """No real gripper, socat wrapper, or cell launch is instantiated."""
    description = MOCK_LAUNCH.generate_launch_description()
    nodes = {
        (node.node_package, node.node_executable) for node in description.entities
        if isinstance(node, Node)
    }
    assert nodes == {
        ('risl_contact_assembly', 'fake_gripper'),
        ('risl_contact_assembly', 'record_joint_states'),
    }


@pytest.mark.parametrize(
    ('command', 'expected_mm'),
    [('open', 110.0), ('close', 0.0), ('0', 0.0), ('550', 55.0), ('1100', 110.0)],
)
def test_fake_gripper_applies_width_commands(command, expected_mm):
    """Commands in tenths of millimetres produce millimetre feedback."""
    node = SimpleNamespace(width_mm=35.0, width_publisher=Mock(), get_logger=Mock())
    FakeGripper.handle_command(node, String(data=command))
    assert node.width_mm == expected_mm
    message = node.width_publisher.publish.call_args.args[0]
    assert isinstance(message, Float64)
    assert message.data == expected_mm


def test_fake_gripper_query_republishes_current_width():
    """Query feedback does not change the mock width."""
    node = SimpleNamespace(width_mm=35.0, width_publisher=Mock(), get_logger=Mock())
    FakeGripper.handle_command(node, String(data='query'))
    assert node.width_mm == 35.0
    assert node.width_publisher.publish.call_args.args[0].data == 35.0


@pytest.mark.parametrize('command', ['1101', '-1', '12.5', 'open now', ''])
def test_fake_gripper_rejects_invalid_commands(command):
    """Invalid commands leave the width unchanged and publish no feedback."""
    node = SimpleNamespace(width_mm=35.0, width_publisher=Mock(), get_logger=Mock())
    FakeGripper.handle_command(node, String(data=command))
    assert node.width_mm == 35.0
    node.width_publisher.publish.assert_not_called()
    node.get_logger.return_value.warning.assert_called_once()


def test_recorder_writes_timestamped_json_lines(tmp_path):
    """Each sample preserves receive time, header stamp, and joint arrays."""
    output = tmp_path / 'joint_states.jsonl'
    clock = Mock()
    clock.now.return_value.nanoseconds = 123456789
    node = SimpleNamespace(
        samples_file=output.open('w', encoding='utf-8'),
        get_clock=Mock(return_value=clock),
    )
    message = JointState()
    message.header.stamp.sec = 7
    message.header.stamp.nanosec = 250
    message.name = ['shoulder_pan_joint']
    message.position = [0.5]
    message.velocity = [0.01]
    message.effort = [1.5]

    JointStateRecorder.record(node, message)
    JointStateRecorder.record(node, message)
    node.samples_file.close()

    lines = output.read_text(encoding='utf-8').splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0]) == {
        'receive_time_ns': 123456789,
        'header_stamp_ns': 7_000_000_250,
        'name': ['shoulder_pan_joint'],
        'position': [0.5],
        'velocity': [0.01],
        'effort': [1.5],
    }
    assert json.loads(lines[1]) == json.loads(lines[0])
