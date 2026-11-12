"""Stand-in for the ``risl_onrobot_ros`` RG2 node on fake hardware.

It opens no serial port or socket. ``/gripper_command`` takes ``open``,
``close``, ``query`` or a width in tenths of a millimetre;
``/gripper_queried_width`` reports millimetres.
"""

import rclpy
from rclpy.node import Node
from std_msgs.msg import Float64, String

MAX_WIDTH_MM = 110.0


class FakeGripper(Node):
    """Gripper that reaches every commanded width instantly.

    The ``object_width_mm`` parameter emulates a held brick: the fingers stop
    there when commanded narrower. Zero emulates an empty grasp.
    """

    def __init__(self) -> None:
        """Start fully open and listen for commands."""
        super().__init__("fake_gripper")
        self.object_width_mm = self.declare_parameter("object_width_mm", 0.0).value
        self.width_mm = MAX_WIDTH_MM
        self.create_subscription(String, "/gripper_command", self.on_command, 10)
        self.width_publisher = self.create_publisher(
            Float64, "/gripper_queried_width", 10
        )

    def on_command(self, message: String) -> None:
        """Apply a command and publish the resulting width.

        Args:
            message: ``open``, ``close``, ``query`` or tenths of a millimetre.
        """
        command = message.data.lower()
        if command == "open":
            self.width_mm = MAX_WIDTH_MM
        elif command == "close":
            self.width_mm = self.object_width_mm
        elif command.isdigit():
            self.width_mm = min(
                max(int(command) / 10.0, self.object_width_mm), MAX_WIDTH_MM
            )
        self.width_publisher.publish(Float64(data=self.width_mm))


def main(args: list[str] | None = None) -> None:
    """Run the fake gripper until interrupted.

    Args:
        args: ROS arguments.
    """
    rclpy.init(args=args)
    try:
        rclpy.spin(FakeGripper())
    except KeyboardInterrupt:
        pass
