"""ROS interfaces of the UR driver and the gripper node.

Topics and types:

- ``/joint_states`` (JointState): joint angles, radians.
- ``/speed_scaling_state_broadcaster/speed_scaling`` (Float64): pendant speed
  slider times safety scaling, percent.
- ``/force_torque_sensor_broadcaster/wrench`` (WrenchStamped): tool force,
  newtons. Only the magnitude of force changes is used, so its frame is
  irrelevant.
- ``/io_and_status_controller/robot_program_running`` (Bool, latched).
- ``/gripper_command`` (String): ``open``, ``close``, ``query`` or a width in
  tenths of a millimetre.
- ``/gripper_queried_width`` (Float64): measured width, millimetres.
- ``/vision/object_poses/<name>`` (PoseStamped in ``base``): optional camera
  poses from ``risl_camera_localizer``.
- ``/scaled_joint_trajectory_controller/follow_joint_trajectory``
  (FollowJointTrajectory action): joint space, so no frame is involved.
"""

from threading import Thread
from time import monotonic, sleep

import numpy as np
from action_msgs.msg import GoalStatus
from builtin_interfaces.msg import Duration
from control_msgs.action import FollowJointTrajectory
from control_msgs.msg import JointTolerance
from geometry_msgs.msg import PoseStamped, WrenchStamped
from rclpy.action import ActionClient
from rclpy.action.client import ClientGoalHandle
from rclpy.executors import SingleThreadedExecutor
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile
from rclpy.task import Future
from sensor_msgs.msg import JointState
from std_msgs.msg import Bool, Float64, String
from trajectory_msgs.msg import JointTrajectoryPoint

JOINT_NAMES = (
    "shoulder_pan_joint",
    "shoulder_lift_joint",
    "elbow_joint",
    "wrist_1_joint",
    "wrist_2_joint",
    "wrist_3_joint",
)
FEEDBACK_TIMEOUT_S = 0.5
GRIPPER_FEEDBACK_TIMEOUT_S = 1.0
GOAL_TOLERANCE_RAD = 0.001
GOAL_TIME_TOLERANCE_S = 2
CANCEL_TIMEOUT_S = 2.0
CAMERA_TIMEOUT_S = 5.0


class RosRobot:
    """Latest feedback from, and commands to, the arm and gripper."""

    def __init__(self, node: Node, commands: bool) -> None:
        """Subscribe to feedback and start spinning the node in the background.

        Args:
            node: Node that owns every subscription and client.
            commands: Create the trajectory action client and the gripper
                publisher. A dry run passes False and cannot command anything.
        """
        self.node = node
        self.samples: dict[str, tuple[float, np.ndarray]] = {}
        self.program_is_running = False
        self.goal_future: Future | None = None
        self.goal_handle: ClientGoalHandle | None = None
        self.result_future: Future | None = None
        node.create_subscription(JointState, "/joint_states", self.on_joints, 10)
        node.create_subscription(
            Float64,
            "/speed_scaling_state_broadcaster/speed_scaling",
            lambda message: self.store("speed", [message.data / 100.0]),
            10,
        )
        node.create_subscription(
            WrenchStamped,
            "/force_torque_sensor_broadcaster/wrench",
            lambda message: self.store(
                "force",
                [
                    message.wrench.force.x,
                    message.wrench.force.y,
                    message.wrench.force.z,
                ],
            ),
            10,
        )
        node.create_subscription(
            Bool,
            "/io_and_status_controller/robot_program_running",
            self.on_program_running,
            QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL),
        )
        node.create_subscription(
            Float64,
            "/gripper_queried_width",
            lambda message: self.store("gripper", [message.data]),
            10,
        )
        if commands:
            self.trajectory_client = ActionClient(
                node,
                FollowJointTrajectory,
                "/scaled_joint_trajectory_controller/follow_joint_trajectory",
            )
            self.gripper_publisher = node.create_publisher(
                String, "/gripper_command", 10
            )
        self.spinner = SingleThreadedExecutor()
        self.spinner.add_node(node)
        self.spin_thread = Thread(target=self.spinner.spin, daemon=True)
        self.spin_thread.start()

    def close(self) -> None:
        """Stop the background spinning before ROS shuts down."""
        self.spinner.shutdown()
        self.spin_thread.join()

    def store(self, name: str, values: list[float]) -> None:
        """Keep the newest sample of one feedback channel with its arrival time.

        Args:
            name: Channel key: ``joints``, ``speed``, ``force`` or ``gripper``.
            values: Sample values.
        """
        self.samples[name] = (monotonic(), np.array(values, dtype=float))

    def fresh(self, name: str, max_age_s: float) -> np.ndarray | None:
        """Return the newest sample of a channel unless it is missing or stale.

        Args:
            name: Channel key passed to ``store``.
            max_age_s: Oldest accepted sample age, seconds.

        Returns:
            The finite sample, or None.
        """
        sample = self.samples.get(name)
        if sample is None or monotonic() - sample[0] > max_age_s:
            return None
        return sample[1] if np.all(np.isfinite(sample[1])) else None

    def on_joints(self, message: JointState) -> None:
        """Store joint angles reordered to ``JOINT_NAMES``.

        Args:
            message: Joint state in the driver's own joint order.
        """
        angle = dict(zip(message.name, message.position))
        self.store("joints", [angle[name] for name in JOINT_NAMES])

    def on_program_running(self, message: Bool) -> None:
        """Store whether the pendant program is running.

        Args:
            message: Latched driver status.
        """
        self.program_is_running = message.data

    def now(self) -> float:
        """Return monotonic time.

        Returns:
            Seconds from an arbitrary origin.
        """
        return monotonic()

    def wait(self, seconds: float) -> None:
        """Sleep while the background thread keeps receiving feedback.

        Args:
            seconds: Time to wait.
        """
        sleep(seconds)

    def joints(self) -> np.ndarray | None:
        """Return fresh joint angles.

        Returns:
            Six angles in ``JOINT_NAMES`` order, radians, or None when stale.
        """
        return self.fresh("joints", FEEDBACK_TIMEOUT_S)

    def force(self) -> np.ndarray | None:
        """Return the fresh tool force.

        Returns:
            Force vector, newtons, or None when stale or not finite.
        """
        return self.fresh("force", FEEDBACK_TIMEOUT_S)

    def speed_fraction(self) -> float | None:
        """Return the fresh driver speed scaling.

        Returns:
            Fraction of programmed speed in [0, 1], or None when stale.
        """
        sample = self.fresh("speed", FEEDBACK_TIMEOUT_S)
        return None if sample is None else float(sample[0])

    def gripper_width(self) -> float | None:
        """Return the fresh measured gripper width.

        Returns:
            Width in millimetres, or None when stale.
        """
        sample = self.fresh("gripper", GRIPPER_FEEDBACK_TIMEOUT_S)
        return None if sample is None else float(sample[0])

    def program_running(self) -> bool:
        """Return whether the External Control program is running.

        Returns:
            Latest latched driver status; False before any message.
        """
        return self.program_is_running

    def controller_ready(self) -> bool:
        """Return whether the trajectory controller accepts goals.

        Returns:
            True once the action server is discovered.
        """
        return self.trajectory_client.server_is_ready()

    def gripper(self, command: str) -> None:
        """Publish one gripper command.

        Args:
            command: ``open``, ``close``, ``query`` or tenths of a millimetre.
        """
        self.gripper_publisher.publish(String(data=command))

    def send(
        self, times: np.ndarray, positions: np.ndarray, velocities: np.ndarray
    ) -> None:
        """Send one joint trajectory to the scaled trajectory controller.

        Args:
            times: Sample times from the start of the move, seconds.
            positions: Joint angles per sample in ``JOINT_NAMES`` order, radians.
            velocities: Joint velocities per sample, rad/s.
        """
        goal = FollowJointTrajectory.Goal()
        goal.trajectory.joint_names = list(JOINT_NAMES)
        for time_s, position, velocity in zip(times, positions, velocities):
            nanoseconds = round(time_s * 1e9)
            goal.trajectory.points.append(
                JointTrajectoryPoint(
                    positions=position.tolist(),
                    velocities=velocity.tolist(),
                    time_from_start=Duration(
                        sec=nanoseconds // 10**9, nanosec=nanoseconds % 10**9
                    ),
                )
            )
        goal.goal_tolerance = [
            JointTolerance(name=name, position=GOAL_TOLERANCE_RAD)
            for name in JOINT_NAMES
        ]
        goal.goal_time_tolerance = Duration(sec=GOAL_TIME_TOLERANCE_S)
        self.goal_handle = None
        self.result_future = None
        self.goal_future = self.trajectory_client.send_goal_async(goal)

    def motion_state(self) -> str:
        """Report the trajectory sent last.

        Returns:
            ``idle`` before any trajectory, then ``active``, ``succeeded``,
            ``canceled`` or a failure description.
        """
        if self.goal_future is None:
            return "idle"
        if self.result_future is None:
            if not self.goal_future.done():
                return "active"
            self.goal_handle = self.goal_future.result()
            if not self.goal_handle.accepted:
                return "rejected by the trajectory controller"
            self.result_future = self.goal_handle.get_result_async()
        if not self.result_future.done():
            return "active"
        response = self.result_future.result()
        if response.status == GoalStatus.STATUS_CANCELED:
            return "canceled"
        if (
            response.status == GoalStatus.STATUS_SUCCEEDED
            and response.result.error_code == FollowJointTrajectory.Result.SUCCESSFUL
        ):
            return "succeeded"
        return (
            f"failed (status {response.status}, code {response.result.error_code} "
            f"{response.result.error_string})"
        )

    def cancel(self) -> None:
        """Cancel the active trajectory; the controller then holds position."""
        deadline = monotonic() + CANCEL_TIMEOUT_S
        while self.motion_state() == "active" and monotonic() < deadline:
            if self.goal_handle is not None:
                cancel_future = self.goal_handle.cancel_goal_async()
                while not cancel_future.done() and monotonic() < deadline:
                    sleep(0.01)
                return
            sleep(0.01)

    def object_xy(self, name: str) -> np.ndarray | None:
        """Wait for one camera pose of an object.

        Args:
            name: Object name; the topic is ``/vision/object_poses/<name>``.

        Returns:
            Object origin ``[x, y]`` in ``base``, metres, or None when no pose
            in ``base`` arrives within ``CAMERA_TIMEOUT_S``.
        """
        poses: list[PoseStamped] = []
        subscription = self.node.create_subscription(
            PoseStamped, f"/vision/object_poses/{name}", poses.append, 1
        )
        deadline = monotonic() + CAMERA_TIMEOUT_S
        while not poses and monotonic() < deadline:
            sleep(0.05)
        self.node.destroy_subscription(subscription)
        if not poses or poses[-1].header.frame_id != "base":
            return None
        position = poses[-1].pose.position
        return np.array([position.x, position.y])
