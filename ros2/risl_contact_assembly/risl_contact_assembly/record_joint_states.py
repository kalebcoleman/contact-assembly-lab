"""Record timestamped /joint_states samples as JSON Lines.

The trace is raw joint feedback and is not physical force or contact evidence.
"""

from json import dumps
from pathlib import Path

import rclpy
from rclpy.node import Node
from sensor_msgs.msg import JointState


class JointStateRecorder(Node):
    """Write every /joint_states sample with receive and header timestamps."""

    def __init__(self) -> None:
        """Open the output file and subscribe to /joint_states."""
        super().__init__("record_joint_states")
        self.declare_parameter(
            "joint_states_file", "/tmp/risl_contact_assembly_joint_states.jsonl"
        )
        path = Path(self.get_parameter("joint_states_file").value)
        self.samples_file = path.open("w", encoding="utf-8")
        self.create_subscription(JointState, "/joint_states", self.record, 10)
        self.get_logger().info(f"Recording joint states to {path}")

    def record(self, msg: JointState) -> None:
        """Append one sample in ROS units: radians, rad/s, and newton-metres."""
        stamp = msg.header.stamp
        sample = {
            "receive_time_ns": self.get_clock().now().nanoseconds,
            "header_stamp_ns": stamp.sec * 1_000_000_000 + stamp.nanosec,
            "name": list(msg.name),
            "position": [float(value) for value in msg.position],
            "velocity": [float(value) for value in msg.velocity],
            "effort": [float(value) for value in msg.effort],
        }
        self.samples_file.write(dumps(sample) + "\n")
        self.samples_file.flush()


def main(args: list[str] | None = None) -> None:
    """Record joint states until the process stops."""
    rclpy.init(args=args)
    node = JointStateRecorder()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.samples_file.close()
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
