"""In-process mock gripper exposing the OnRobot command and feedback topics.

It never opens a serial port, starts socat, or contacts the real gripper. Emulated width
is not force or contact evidence.
"""

import rclpy
from rclpy.node import Node
from std_msgs.msg import Float64, String

MAX_WIDTH_TENTHS_MM = 1100
INITIAL_WIDTH_MM = MAX_WIDTH_TENTHS_MM / 10.0


class FakeGripper(Node):
    """Mock OnRobot RG2 with tenths-millimetre commands and millimetre feedback."""

    def __init__(self) -> None:
        """Start at the open width and listen on /gripper_command."""
        super().__init__('fake_gripper')
        self.width_mm = INITIAL_WIDTH_MM
        self.create_subscription(String, '/gripper_command', self.handle_command, 10)
        self.width_publisher = self.create_publisher(
            Float64, '/gripper_queried_width', 10)

    def handle_command(self, msg: String) -> None:
        """Apply open, close, query, or an integer 0..1100 tenths-millimetre width."""
        command = msg.data.lower()
        if command == 'open':
            self.width_mm = MAX_WIDTH_TENTHS_MM / 10.0
        elif command == 'close':
            self.width_mm = 0.0
        elif command == 'query':
            pass
        elif command.isdigit() and int(command) <= MAX_WIDTH_TENTHS_MM:
            self.width_mm = int(command) / 10.0
        else:
            self.get_logger().warning(f'Ignoring invalid gripper command: {msg.data!r}')
            return
        self.width_publisher.publish(Float64(data=self.width_mm))


def main(args: list[str] | None = None) -> None:
    """Run the fake gripper until the process stops."""
    rclpy.init(args=args)
    node = FakeGripper()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
