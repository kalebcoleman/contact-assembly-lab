"""Execute planner steps for known-pose brick assembly on a UR5e.

All poses are tool-centre-point (TCP) poses in the UR ``base`` frame.  The
driver's ``base_link`` differs from ``base`` by a 180 degree rotation about Z;
poses are never silently reinterpreted as ``base_link``.  TCP pose feedback must
declare ``base`` explicitly, otherwise execution fails closed.  Positions are in
metres; orientations are roll-pitch-yaw in degrees, matching
``scipy.spatial.transform.Rotation.from_euler('xyz', rpy, degrees=True)`` as
used by the Max IK solver.  A zero TCP offset is assumed: the commanded TCP is
the UR flange.  Brick descent is assumed to be along ``-Z`` of ``base``.

Config ``seating.force_n`` is the planner's requested *commanded* force.  It is
not a measured force limit and does not establish compliant-axis travel.  This
package never starts UR force mode: hardware seating is refused outright because
no validated force or travel sensing exists.  ``mock_execution`` rehearses the
same steps as a guarded position descent and labels the result ``emulated``.
Travel is capped by ``seating.max_travel_m`` with no extra allowance, and a
completed descent is never reported as seated or in contact.  Dry runs validate
the plan and write a step log without constructing the motion stack, creating
control endpoints, or publishing messages.  Every numeric threshold below that
is not derived from the plan is unvalidated and mock-only.  All watchdogs use
``time.monotonic``; the ROS clock is not monotonic and is never used for guards.
"""

import json
import math
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from logging import getLogger
from os import environ
from pathlib import Path
from typing import Protocol

import rclpy
from geometry_msgs.msg import PoseStamped
from rclpy.node import Node
from sensor_msgs.msg import JointState

BASE_FRAME = "base"
ACTIONS = (
    "approach",
    "descend",
    "close",
    "lift",
    "transfer",
    "approach_target",
    "slow_descend",
    "seat",
    "open",
    "retreat",
)
JOINT_NAMES = (
    "shoulder_pan_joint",
    "shoulder_lift_joint",
    "elbow_joint",
    "wrist_1_joint",
    "wrist_2_joint",
    "wrist_3_joint",
)
POSITION_CONTROLLER = "scaled_joint_trajectory_controller"
VELOCITY_CONTROLLER = "forward_velocity_controller"
FORCE_CONTROLLER = "force_mode_controller"
PASSTHROUGH_CONTROLLER = "passthrough_trajectory_controller"
GRIPPER_TENTHS_PER_MM = 10
MAX_GRIPPER_WIDTH_MM = 110.0
MIN_SEGMENT_S = 0.5
SEAT_SUBSTEP_M = 0.0005
IK_POSITION_TOLERANCE_M = 0.002
IK_ANGLE_TOLERANCE_RAD = 0.01
MAX_JOINT_PATH_SAMPLES = 16
LOGGER = getLogger(__name__)


class PlanValidationError(ValueError):
    """Raised when a planner step list or config violates the contract."""

    def __init__(self, problems: Sequence[str]) -> None:
        """Store every validation problem and build one readable message."""
        self.problems = tuple(problems)
        super().__init__("invalid assembly plan: " + "; ".join(self.problems))


class ExecutionRefusedError(RuntimeError):
    """Raised when operating conditions forbid starting execution."""


class FeedbackError(RuntimeError):
    """Raised when joint or TCP feedback is missing, stale or mis-framed."""


class MotionFaultError(RuntimeError):
    """Raised when a motion command fails, times out, or exceeds a guard."""


@dataclass(frozen=True)
class Step:
    """One validated planner step as consumed by the executor."""

    index: int
    action: str
    brick_id: str
    xyz_m: tuple[float, float, float]
    rpy_deg: tuple[float, float, float]
    speed_m_s: float
    gripper_width_mm: float | None


@dataclass(frozen=True)
class Limits:
    """Workspace and speed limits from ``config.limits``."""

    workspace_min_m: tuple[float, float, float]
    workspace_max_m: tuple[float, float, float]
    max_speed_m_s: float
    max_speed_scale: float


@dataclass(frozen=True)
class SeatingLimits:
    """Seating guards from ``config.seating``; force is commanded, not measured."""

    force_n: float
    max_travel_m: float
    timeout_s: float


@dataclass(frozen=True)
class ValidatedPlan:
    """Fully validated steps together with the limits they were checked against."""

    steps: list[Step]
    limits: Limits
    seating: SeatingLimits
    speed_scale: float


@dataclass(frozen=True)
class ExecutorOptions:
    """Runtime options mirrored by ROS parameters of the same names."""

    dry_run: bool = True
    confirm_each_step: bool = True
    pose_source: str = "known_poses"
    step_log: str = "assembly_steps.jsonl"
    mock_execution: bool = False
    mock_hardware_proof: str = ""
    enable_physical_execution: bool = False
    speed_scale: float = 1.0
    feedback_timeout_s: float = 1.0
    travel_guard_s: float = 5.0


@dataclass(frozen=True)
class StepRecord:
    """Outcome of one step; ``status`` is planned, ok, emulated or aborted."""

    index: int
    action: str
    brick_id: str
    target_xyz_m: tuple[float, float, float]
    target_rpy_deg: tuple[float, float, float]
    effective_speed_m_s: float
    status: str
    force_mode: str
    executed: bool
    detail: str


@dataclass(frozen=True)
class ExecutionResult:
    """Final status of a run: planned, completed or aborted."""

    status: str
    detail: str
    records: list[StepRecord]


def _number(problems: list[str], value: object, label: str) -> float | None:
    """Read a finite number and record a problem instead of raising.

    Args:
        problems: Accumulated validation problems.
        value: Raw value from the plan or config.
        label: Human-readable location used in the problem text.

    Returns:
        The finite float value, or None when the value is unusable.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        problems.append(f"{label} must be a number, got {value!r}")
        return None
    number = float(value)
    if not math.isfinite(number):
        problems.append(f"{label} must be finite, got {number}")
        return None
    return number


def _vector(
    problems: list[str], value: object, label: str
) -> tuple[float, float, float] | None:
    """Read a three-element finite vector and record a problem instead of raising.

    Args:
        problems: Accumulated validation problems.
        value: Raw vector from the plan or config.
        label: Human-readable location used in the problem text.

    Returns:
        The finite tuple, or None when the vector is unusable.
    """
    if isinstance(value, str) or not isinstance(value, Sequence) or len(value) != 3:
        problems.append(f"{label} must be a sequence of three numbers, got {value!r}")
        return None
    numbers = tuple(
        _number(problems, item, f"{label}[{axis}]") for axis, item in enumerate(value)
    )
    if numbers[0] is None or numbers[1] is None or numbers[2] is None:
        return None
    return (numbers[0], numbers[1], numbers[2])


def validate_plan(
    plan: Sequence[object], config: Mapping[str, object], speed_scale: float = 1.0
) -> ValidatedPlan:
    """Validate the complete plan and config before any control is issued.

    Every brick must contain the canonical action order exactly once, every pose
    must lie inside the workspace, every speed must honour
    ``limits.max_speed_m_s``, and the requested derating must be at most 1.0.
    Planner speeds already include ``limits.max_speed_scale``, so limits and the
    requested scale are validated rather than silently clamped or rescaled.
    Planned seating descent from ``approach_target`` is capped by
    ``seating.max_travel_m``.

    Args:
        plan: Step mappings as returned by ``planner.plan_structure``.
        config: Parsed config mapping as returned by ``planner.load_config``.
        speed_scale: Requested operator derating factor applied once.

    Returns:
        Validated steps, limits, seating guards and the accepted speed scale.

    Raises:
        PlanValidationError: When one or more contract violations are found.
    """
    problems: list[str] = []
    if isinstance(plan, (str, bytes)) or not isinstance(plan, Sequence) or not plan:
        raise PlanValidationError(["plan must be a non-empty sequence of steps"])

    raw_limits = config.get("limits")
    raw_seating = config.get("seating")
    if not isinstance(raw_limits, Mapping):
        problems.append("config.limits must be a mapping")
        raw_limits = {}
    if not isinstance(raw_seating, Mapping):
        problems.append("config.seating must be a mapping")
        raw_seating = {}

    workspace_min = _vector(
        problems, raw_limits.get("workspace_min_m"), "config.limits.workspace_min_m"
    )
    workspace_max = _vector(
        problems, raw_limits.get("workspace_max_m"), "config.limits.workspace_max_m"
    )
    max_speed = _number(
        problems, raw_limits.get("max_speed_m_s"), "config.limits.max_speed_m_s"
    )
    max_scale = _number(
        problems, raw_limits.get("max_speed_scale"), "config.limits.max_speed_scale"
    )
    force_n = _number(problems, raw_seating.get("force_n"), "config.seating.force_n")
    max_travel = _number(
        problems, raw_seating.get("max_travel_m"), "config.seating.max_travel_m"
    )
    seat_timeout = _number(
        problems, raw_seating.get("timeout_s"), "config.seating.timeout_s"
    )
    scale = _number(problems, speed_scale, "speed_scale")

    if max_speed is not None and max_speed <= 0.0:
        problems.append("config.limits.max_speed_m_s must be positive")
    if max_scale is not None and max_scale <= 0.0:
        problems.append("config.limits.max_speed_scale must be positive")
    if force_n is not None and force_n <= 0.0:
        problems.append("config.seating.force_n must be positive")
    if max_travel is not None and max_travel <= 0.0:
        problems.append("config.seating.max_travel_m must be positive")
    if seat_timeout is not None and seat_timeout <= 0.0:
        problems.append("config.seating.timeout_s must be positive")
    if scale is not None and not 0.0 < scale <= 1.0:
        problems.append(
            f"speed_scale {scale} must be in (0, 1]; planner speeds already include "
            "config.limits.max_speed_scale"
        )
    if workspace_min is not None and workspace_max is not None:
        for axis, (low, high) in enumerate(
            zip(workspace_min, workspace_max, strict=True)
        ):
            if low >= high:
                problems.append(
                    f"config.limits.workspace_min_m[{axis}] must be below "
                    f"workspace_max_m[{axis}]"
                )

    steps: list[Step] = []
    for position, raw in enumerate(plan):
        label = f"plan[{position}]"
        if not isinstance(raw, Mapping):
            problems.append(f"{label} must be a mapping, got {raw!r}")
            continue
        action = raw.get("action")
        brick_id = raw.get("brick_id")
        if not isinstance(action, str) or action not in ACTIONS:
            problems.append(f"{label}.action must be one of {ACTIONS}, got {action!r}")
        if not isinstance(brick_id, str) or not brick_id:
            problems.append(
                f"{label}.brick_id must be a non-empty string, got {brick_id!r}"
            )
        xyz = _vector(problems, raw.get("xyz_m"), f"{label}.xyz_m")
        rpy = _vector(problems, raw.get("rpy_deg"), f"{label}.rpy_deg")
        speed = _number(problems, raw.get("speed_m_s"), f"{label}.speed_m_s")
        raw_width = raw.get("gripper_width_mm")
        width = (
            None
            if raw_width is None
            else _number(problems, raw_width, f"{label}.gripper_width_mm")
        )
        if speed is not None and speed <= 0.0:
            problems.append(f"{label}.speed_m_s must be positive")
        if speed is not None and max_speed is not None and speed > max_speed:
            problems.append(
                f"{label}.speed_m_s {speed} exceeds config.limits.max_speed_m_s "
                f"{max_speed}"
            )
        if width is not None and not 0.0 <= width <= MAX_GRIPPER_WIDTH_MM:
            problems.append(
                f"{label}.gripper_width_mm {width} outside 0..{MAX_GRIPPER_WIDTH_MM}"
            )
        if xyz is not None and workspace_min is not None and workspace_max is not None:
            for axis, (value, low, high) in enumerate(
                zip(xyz, workspace_min, workspace_max, strict=True)
            ):
                if not low <= value <= high:
                    problems.append(
                        f"{label}.xyz_m[{axis}] {value} outside workspace "
                        f"[{low}, {high}]"
                    )
        if (
            action is None
            or brick_id is None
            or xyz is None
            or rpy is None
            or speed is None
        ):
            continue
        steps.append(
            Step(
                index=position,
                action=action,
                brick_id=brick_id,
                xyz_m=xyz,
                rpy_deg=rpy,
                speed_m_s=speed,
                gripper_width_mm=width,
            )
        )

    brick_actions: dict[str, list[str]] = {}
    for step in steps:
        brick_actions.setdefault(step.brick_id, []).append(step.action)
    for brick_id, actions in brick_actions.items():
        if actions != list(ACTIONS):
            problems.append(
                f"brick {brick_id!r} actions {actions} are not canonical "
                f"{list(ACTIONS)}"
            )
        if actions == list(ACTIONS) and max_travel is not None:
            brick_steps = {
                step.action: step for step in steps if step.brick_id == brick_id
            }
            approach_z = brick_steps["approach_target"].xyz_m[2]
            for action in ("slow_descend", "seat"):
                descent = approach_z - brick_steps[action].xyz_m[2]
                # Match the planner's addition rather than subtracting nearby
                # floats; the cap itself is never enlarged.
                if approach_z > brick_steps[action].xyz_m[2] + max_travel:
                    problems.append(
                        f"brick {brick_id!r} {action} descent {descent} from "
                        f"approach_target exceeds config.seating.max_travel_m "
                        f"{max_travel}"
                    )

    if problems:
        raise PlanValidationError(problems)
    assert workspace_min is not None
    assert workspace_max is not None
    assert max_speed is not None
    assert max_scale is not None
    assert force_n is not None
    assert max_travel is not None
    assert seat_timeout is not None
    assert scale is not None
    return ValidatedPlan(
        steps=steps,
        limits=Limits(
            workspace_min_m=workspace_min,
            workspace_max_m=workspace_max,
            max_speed_m_s=max_speed,
            max_speed_scale=max_scale,
        ),
        seating=SeatingLimits(
            force_n=force_n, max_travel_m=max_travel, timeout_s=seat_timeout
        ),
        speed_scale=scale,
    )


class Feedback(Protocol):
    """Joint and TCP feedback required before every motion command."""

    def require_fresh(self) -> None:
        """Raise ``FeedbackError`` unless both channels were received recently."""
        ...

    def tcp_position(self) -> tuple[float, float, float]:
        """Return the latest TCP position in ``base`` or raise ``FeedbackError``."""
        ...

    def joint_positions(self) -> tuple[float, ...]:
        """Return the latest joint positions ordered as ``JOINT_NAMES``."""
        ...


class RosFeedback:
    """Joint state and TCP pose subscriptions with freshness and frame checks."""

    def __init__(
        self,
        node: Node | None,
        timeout_s: float,
        clock: Callable[[], float] = time.monotonic,
        derived_mock_pose: bool = False,
    ) -> None:
        """Optionally subscribe to the two feedback channels used by the executor.

        Args:
            node: Node used for subscriptions; None creates none so callbacks can
                be fed directly by tests.
            timeout_s: Maximum accepted age of the newest feedback sample.
            clock: Monotonic clock used to age samples.
            derived_mock_pose: Derive base-to-tool0 from mock joint positions.
        """
        self.node = node
        self.derived_mock_pose = derived_mock_pose
        self.timeout_s = timeout_s
        self.clock = clock
        self.joint_stamp: float | None = None
        self.joints: tuple[float, ...] | None = None
        self.tcp_stamp: float | None = None
        self.tcp: tuple[float, float, float] | None = None
        self.tcp_frame = ""
        if node is not None:
            node.create_subscription(
                JointState, "/joint_states", self.on_joint_state, 10
            )
            node.create_subscription(
                PoseStamped, "/tcp_pose_broadcaster/pose", self.on_tcp_pose, 10
            )

    def on_joint_state(self, message: JointState) -> None:
        """Record joint positions ordered by ``JOINT_NAMES`` when all are present.

        Args:
            message: Joint state message from ``/joint_states``.
        """
        by_name = dict(zip(message.name, message.position, strict=False))
        if all(name in by_name for name in JOINT_NAMES):
            self.joints = tuple(by_name[name] for name in JOINT_NAMES)
            self.joint_stamp = self.clock()
            if self.derived_mock_pose:
                from risl_ur.custom_libraries.ik_solver import (
                    dh_params,
                    forward_kinematics,
                )

                pose = forward_kinematics(dh_params, self.joints)
                self.tcp = (float(pose[0, 3]), float(pose[1, 3]), float(pose[2, 3]))
                self.tcp_frame = BASE_FRAME
                self.tcp_stamp = self.joint_stamp

    def on_tcp_pose(self, message: PoseStamped) -> None:
        """Record the TCP position, declared frame and arrival time.

        Args:
            message: Pose message from the TCP pose broadcaster.
        """
        position = message.pose.position
        self.tcp = (position.x, position.y, position.z)
        self.tcp_frame = message.header.frame_id
        self.tcp_stamp = self.clock()

    def require_fresh(self) -> None:
        """Raise ``FeedbackError`` when feedback is missing, stale or mis-framed.

        Raises:
            FeedbackError: When a channel was never received, is older than the
                configured timeout, or the TCP pose does not declare ``base``.
        """
        now = self.clock()
        if self.joint_stamp is None or self.joints is None:
            raise FeedbackError("missing /joint_states feedback")
        if self.tcp is None or self.tcp_stamp is None:
            raise FeedbackError("missing /tcp_pose_broadcaster/pose feedback")
        if not all(math.isfinite(value) for value in (*self.joints, *self.tcp)):
            raise FeedbackError("nonfinite joint or TCP feedback")
        if self.tcp_frame != BASE_FRAME:
            raise FeedbackError(
                f"TCP pose frame {self.tcp_frame!r} is not {BASE_FRAME!r}; "
                "base_link needs the verified pi-Z driver transform and is never "
                "assumed silently"
            )
        if now - self.joint_stamp > self.timeout_s:
            raise FeedbackError(
                f"stale /joint_states feedback ({now - self.joint_stamp:.3f}s old)"
            )
        if now - self.tcp_stamp > self.timeout_s:
            raise FeedbackError(
                f"stale /tcp_pose_broadcaster/pose feedback "
                f"({now - self.tcp_stamp:.3f}s old)"
            )

    def tcp_position(self) -> tuple[float, float, float]:
        """Return the newest TCP position after a freshness check.

        Returns:
            TCP xyz in metres in the ``base`` frame.

        Raises:
            FeedbackError: When TCP feedback is missing, stale or mis-framed.
        """
        self.require_fresh()
        assert self.tcp is not None
        return self.tcp

    def joint_positions(self) -> tuple[float, ...]:
        """Return the newest joint positions after a freshness check.

        Returns:
            Six joint angles in radians ordered as ``JOINT_NAMES``.

        Raises:
            FeedbackError: When joint feedback is missing or stale.
        """
        self.require_fresh()
        assert self.joints is not None
        return self.joints


class MotionBackend(Protocol):
    """Motion primitives used by the executor and replaced by fakes in tests."""

    def move(
        self,
        step: Step,
        duration_s: float,
        timeout_s: float,
        limits: Limits,
        start_joints: tuple[float, ...],
    ) -> None:
        """Move the TCP to the step pose within the given deadline margin."""
        ...

    def gripper(self, command: str) -> None:
        """Publish one gripper command string."""
        ...

    def stop(self) -> None:
        """Stop any active motion as quickly as the stack allows."""
        ...


class MaxMotionBackend:
    """Standard trajectory actions using Max IK, restricted to proven fake hardware."""

    def __init__(self, node: Node, feedback: Feedback) -> None:
        """Create mock control endpoints after live hardware verification.

        Args:
            node: ROS node used for actions and gripper feedback.
            feedback: Fresh joint and derived TCP feedback.
        """
        from control_msgs.action import FollowJointTrajectory
        from rclpy.action import ActionClient
        from std_msgs.msg import String

        self.node = node
        self.feedback = feedback
        self.traj_client = ActionClient(
            node,
            FollowJointTrajectory,
            f"/{POSITION_CONTROLLER}/follow_joint_trajectory",
        )
        self.gripper_publisher = node.create_publisher(String, "/gripper_command", 10)
        self.goal_handle = None

    def move(
        self,
        step: Step,
        duration_s: float,
        timeout_s: float,
        limits: Limits,
        start_joints: tuple[float, ...],
    ) -> None:
        """Verify, send and await one joint trajectory goal.

        The Max IK candidate is warm-started from the measured joints and checked
        with forward kinematics.  The joint-space interpolation between measured
        and goal joints is sampled with forward kinematics so endpoint speeds do
        not hide a faster or out-of-workspace TCP path.

        Args:
            step: Target pose in the ``base`` frame.
            duration_s: Requested trajectory duration in seconds.
            timeout_s: Extra wall-clock margin beyond the trajectory duration.
            limits: Workspace and speed limits for the sampled path.
            start_joints: Measured joint angles ordered as ``JOINT_NAMES``.

        Raises:
            MotionFaultError: When IK fails, FK verification fails, the sampled path
                leaves the workspace or exceeds the speed limit, the goal is
                rejected, the deadline passes, or the controller reports failure.
        """
        import numpy as np
        from action_msgs.msg import GoalStatus
        from builtin_interfaces.msg import Duration
        from control_msgs.action import FollowJointTrajectory
        from control_msgs.msg import JointTolerance
        from risl_ur.custom_libraries.ik_solver import (
            compute_ik,
            dh_params,
            forward_kinematics,
        )
        from scipy.spatial.transform import Rotation
        from trajectory_msgs.msg import JointTrajectoryPoint

        start = np.asarray(start_joints, dtype=float)
        joint_positions = compute_ik(
            list(step.xyz_m),
            list(step.rpy_deg),
            q_guess=start.copy(),
            q6_sweep=[start[5]],
        )
        if joint_positions is None:
            raise MotionFaultError(
                f"IK failed for plan[{step.index}] at {step.xyz_m} rpy {step.rpy_deg}"
            )
        goal = np.asarray(joint_positions, dtype=float)
        achieved = forward_kinematics(dh_params, goal)
        position_error = float(
            np.linalg.norm(achieved[:3, 3] - np.asarray(step.xyz_m, dtype=float))
        )
        target_rotation = Rotation.from_euler(
            "xyz", step.rpy_deg, degrees=True
        ).as_matrix()
        rotation_error = achieved[:3, :3].T @ target_rotation
        angle_error = float(
            np.arccos(np.clip((np.trace(rotation_error) - 1.0) / 2.0, -1.0, 1.0))
        )
        if (
            not np.isfinite(goal).all()
            or not math.isfinite(position_error)
            or position_error > IK_POSITION_TOLERANCE_M
            or angle_error > IK_ANGLE_TOLERANCE_RAD
        ):
            raise MotionFaultError(
                f"IK candidate for plan[{step.index}] failed FK verification: "
                f"{position_error:.4f}m, {angle_error:.4f}rad"
            )
        # Sum of link lengths bounds each revolute joint's TCP lever arm.
        # Position-only JTC points use linear joint interpolation. This bound
        # limits TCP speed throughout that interpolation, not just at samples.
        radius_bound = sum(abs(row[1]) + abs(row[2]) for row in dh_params)
        speed_cap = min(step.speed_m_s, limits.max_speed_m_s)
        duration = max(
            duration_s,
            MIN_SEGMENT_S,
            radius_bound * float(np.abs(goal - start).sum()) / speed_cap,
        )
        segment_s = duration / MAX_JOINT_PATH_SAMPLES
        previous_tcp = forward_kinematics(dh_params, start)[:3, 3]
        for sample in range(1, MAX_JOINT_PATH_SAMPLES + 1):
            interpolated = start + (goal - start) * (sample / MAX_JOINT_PATH_SAMPLES)
            tcp = forward_kinematics(dh_params, interpolated)[:3, 3]
            for axis, (value, low, high) in enumerate(
                zip(
                    tcp,
                    limits.workspace_min_m,
                    limits.workspace_max_m,
                    strict=True,
                )
            ):
                if not low <= float(value) <= high:
                    raise MotionFaultError(
                        f"interpolated TCP axis {axis} value {float(value):.4f} for "
                        f"plan[{step.index}] leaves workspace [{low}, {high}]"
                    )
            tcp_speed = float(np.linalg.norm(tcp - previous_tcp)) / segment_s
            if tcp_speed > limits.max_speed_m_s:
                raise MotionFaultError(
                    f"interpolated TCP speed {tcp_speed:.4f}m/s for "
                    f"plan[{step.index}] exceeds max_speed_m_s "
                    f"{limits.max_speed_m_s}"
                )
            previous_tcp = tcp
        duration_ns = round(duration * 1_000_000_000)
        point = JointTrajectoryPoint()
        point.positions = [float(value) for value in goal]
        point.time_from_start = Duration(
            sec=duration_ns // 1_000_000_000, nanosec=duration_ns % 1_000_000_000
        )
        goal_message = FollowJointTrajectory.Goal()
        goal_message.trajectory.joint_names = list(JOINT_NAMES)
        goal_message.trajectory.points.append(point)
        goal_message.goal_time_tolerance = Duration(sec=0, nanosec=500_000_000)
        goal_message.goal_tolerance = [
            JointTolerance(position=0.01, velocity=0.01, name=name)
            for name in JOINT_NAMES
        ]
        client = self.traj_client
        if not client.wait_for_server(timeout_sec=timeout_s):
            raise MotionFaultError("joint trajectory action server unavailable")
        send_future = client.send_goal_async(goal_message)
        rclpy.spin_until_future_complete(self.node, send_future, timeout_sec=timeout_s)
        if not send_future.done():
            raise MotionFaultError("timed out sending joint trajectory goal")
        goal_handle = send_future.result()
        if goal_handle is None or not goal_handle.accepted:
            raise MotionFaultError("joint trajectory goal rejected")
        self.goal_handle = goal_handle
        result_future = goal_handle.get_result_async()
        deadline_s = duration + timeout_s
        deadline = time.monotonic() + deadline_s
        while not result_future.done() and time.monotonic() < deadline:
            rclpy.spin_once(self.node, timeout_sec=0.02)
            self.feedback.require_fresh()
            current_tcp = self.feedback.tcp_position()
            if any(
                not low <= value <= high
                for value, low, high in zip(
                    current_tcp,
                    limits.workspace_min_m,
                    limits.workspace_max_m,
                    strict=True,
                )
            ):
                raise MotionFaultError("measured mock TCP left workspace")
        if not result_future.done():
            goal_handle.cancel_goal_async()
            self.goal_handle = None
            raise MotionFaultError(
                f"joint trajectory deadline {deadline_s:.3f}s exceeded"
            )
        result = result_future.result()
        self.goal_handle = None
        if result is None:
            raise MotionFaultError("joint trajectory returned no result")
        if (
            result.status != GoalStatus.STATUS_SUCCEEDED
            or result.result.error_code != FollowJointTrajectory.Result.SUCCESSFUL
        ):
            raise MotionFaultError(
                f"joint trajectory failed with status {result.status} "
                f"code {result.result.error_code}"
            )

    def gripper(self, command: str) -> None:
        """Publish one gripper command through the Max gripper handler.

        Args:
            command: ``open``, ``close`` or an integer string in tenths of mm.
        """
        from std_msgs.msg import Float64, String

        widths: list[float] = []
        subscription = self.node.create_subscription(
            Float64,
            "/gripper_queried_width",
            lambda message: widths.append(message.data),
            10,
        )
        try:
            deadline = time.monotonic() + 5.0
            while not self.gripper_publisher.get_subscription_count():
                if time.monotonic() > deadline:
                    raise MotionFaultError("fake gripper unavailable")
                rclpy.spin_once(self.node, timeout_sec=0.02)
            self.gripper_publisher.publish(String(data=command))
            while not widths and time.monotonic() < deadline:
                rclpy.spin_once(self.node, timeout_sec=0.02)
            expected = (
                110.0
                if command == "open"
                else (0.0 if command == "close" else int(command) / 10.0)
            )
            if not widths or abs(widths[-1] - expected) > 0.05:
                raise MotionFaultError("fake gripper feedback missing or incorrect")
        finally:
            self.node.destroy_subscription(subscription)

    def stop(self) -> None:
        """Request cancellation once; no velocity or force mode is used."""
        if self.goal_handle is not None:
            self.goal_handle.cancel_goal_async()
            self.goal_handle = None


class AssemblyExecutor:
    """Validate and execute a planner step list under explicit safety gates."""

    def __init__(
        self,
        node: Node | None,
        plan: Sequence[object],
        config: Mapping[str, object],
        options: ExecutorOptions | None = None,
        *,
        feedback: Feedback | None = None,
        backend: MotionBackend | None = None,
        confirm: Callable[[Step], bool] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """Store the plan and injected feedback, backend and confirmation hooks.

        Args:
            node: ROS node used only when executing; None is valid for dry runs.
            plan: Step list from the planner.
            config: Parsed assembly config.
            options: Runtime options; defaults are dry-run with confirmation.
            feedback: Feedback provider, created from the node when omitted.
            backend: Motion backend, created from the node when omitted.
            confirm: Per-step confirmation callback; terminal prompt when omitted.
            clock: Monotonic clock used for feedback ages and seating guards.
        """
        self.node = node
        self.plan = plan
        self.config = config
        self.options = options or ExecutorOptions()
        self.feedback = feedback
        self.backend = backend
        self.confirm = confirm or self.confirm_from_terminal
        self.clock = clock

    def confirm_from_terminal(self, step: Step) -> bool:
        """Ask the operator at the terminal; only an explicit yes proceeds.

        Args:
            step: Step about to run.

        Returns:
            True only for ``y`` or ``yes``; absent input fails closed.
        """
        try:
            answer = input(
                f"Execute plan[{step.index}] {step.action} for brick "
                f"{step.brick_id}? [y/N] "
            )
        except EOFError:
            return False
        return answer.strip().lower() in ("y", "yes")

    def require_execution_gate(self, validated: ValidatedPlan) -> None:
        """Refuse execution unless mock proof or authorized physical mode is present.

        Hardware seating is always refused because no validated force or travel
        sensing and no operator-approved force limits exist.

        Args:
            validated: Plan that would be executed.

        Raises:
            ExecutionRefusedError: When a gate is not satisfied.
        """
        if self.node is None and (self.feedback is None or self.backend is None):
            raise ExecutionRefusedError(
                "a ROS node is required to create feedback and motion endpoints"
            )
        if self.options.enable_physical_execution:
            raise ExecutionRefusedError(
                "hardware seating is blocked; physical execution is disabled"
            )
        if self.options.mock_execution and self.node is not None:
            from xml.etree.ElementTree import fromstring

            from controller_manager_msgs.srv import ListHardwareComponents
            from rcl_interfaces.srv import GetParameters

            if (
                environ.get("ROS_LOCALHOST_ONLY") != "1"
                or environ.get("ROS_DOMAIN_ID") != "83"
            ):
                raise ExecutionRefusedError("mock requires localhost ROS domain 83")
            for service, kind, request in (
                (
                    "/controller_manager/list_hardware_components",
                    ListHardwareComponents,
                    ListHardwareComponents.Request(),
                ),
                (
                    "/controller_manager/get_parameters",
                    GetParameters,
                    GetParameters.Request(names=["robot_description"]),
                ),
            ):
                client = self.node.create_client(kind, service)
                try:
                    if not client.wait_for_service(timeout_sec=5.0):
                        raise ExecutionRefusedError("mock proof service unavailable")
                    future = client.call_async(request)
                    rclpy.spin_until_future_complete(self.node, future, timeout_sec=5.0)
                    if not future.done() or future.result() is None:
                        raise ExecutionRefusedError("live mock proof timed out")
                    response = future.result()
                    if kind is ListHardwareComponents:
                        if not response.component or any(
                            h.class_type != "mock_components/GenericSystem"
                            for h in response.component
                        ):
                            raise ExecutionRefusedError("non-mock hardware detected")
                    else:
                        plugins = [
                            element.text
                            for element in fromstring(
                                response.values[0].string_value
                            ).findall(".//ros2_control/hardware/plugin")
                        ]
                        if plugins != ["mock_components/GenericSystem"]:
                            raise ExecutionRefusedError(
                                "robot description is not mock-only"
                            )
                finally:
                    self.node.destroy_client(client)
            deadline = time.monotonic() + 5.0
            subscribers = []
            while not subscribers and time.monotonic() < deadline:
                rclpy.spin_once(self.node, timeout_sec=0.05)
                subscribers = self.node.get_subscriptions_info_by_topic(
                    "/gripper_command"
                )
            if not subscribers or any(
                s.node_name != "fake_gripper" for s in subscribers
            ):
                raise ExecutionRefusedError("gripper endpoint is not the fake gripper")
            return
        if self.options.mock_execution:
            proof_path = Path(self.options.mock_hardware_proof)
            if not self.options.mock_hardware_proof:
                raise ExecutionRefusedError(
                    "mock_execution requires mock_hardware_proof pointing at a "
                    "proof file"
                )
            proof = json.loads(proof_path.read_text(encoding="utf-8"))
            if not isinstance(proof, dict) or proof.get("mock_hardware") is not True:
                raise ExecutionRefusedError(
                    f"mock proof {proof_path} does not declare mock_hardware: true"
                )
            return
        raise ExecutionRefusedError(
            "physical execution is disabled; dry_run or proven mock_execution required"
        )

    def run(self) -> ExecutionResult:
        """Validate, gate and execute the plan, writing one log line per step.

        Returns:
            Planned, completed or aborted status with per-step records.

        Raises:
            PlanValidationError: When the plan or config is invalid.
            ExecutionRefusedError: When an execution gate is not satisfied.
        """
        validated = validate_plan(self.plan, self.config, self.options.speed_scale)
        if self.options.dry_run:
            records = [self.planned_record(step, validated) for step in validated.steps]
            for record in records:
                self.write_record(record)
            note = (
                "dry run: plan validated and logged; no control endpoint or message "
                "created; no physical insertion validated"
            )
            return ExecutionResult(status="planned", detail=note, records=records)
        if self.options.pose_source != "known_poses":
            raise ExecutionRefusedError(
                f"pose_source {self.options.pose_source!r} is unsupported; vision "
                "object poses at /vision/object_poses/<name> are not a TCP target "
                "source, refusing to execute"
            )
        self.require_execution_gate(validated)
        records: list[StepRecord] = []
        current: Step | None = None
        issued = False
        try:
            if self.feedback is None:
                assert self.node is not None
                self.feedback = RosFeedback(
                    self.node, self.options.feedback_timeout_s, derived_mock_pose=True
                )
                deadline = time.monotonic() + self.options.travel_guard_s
                while self.feedback.joints is None and time.monotonic() < deadline:
                    rclpy.spin_once(self.node, timeout_sec=0.05)
            self.feedback.require_fresh()
            if self.backend is None:
                assert self.node is not None
                self.backend = MaxMotionBackend(self.node, self.feedback)
            for step in validated.steps:
                current = step
                if self.options.confirm_each_step and not self.confirm(step):
                    records.append(
                        self.aborted_record(step, validated, "operator declined step")
                    )
                    self.write_record(records[-1])
                    return ExecutionResult(
                        status="aborted",
                        detail=f"declined plan[{step.index}]",
                        records=records,
                    )
                self.feedback.require_fresh()
                issued = True
                records.append(self.execute_step(step, validated))
                self.write_record(records[-1])
                if records[-1].status == "aborted":
                    return ExecutionResult(
                        status="aborted", detail=records[-1].detail, records=records
                    )
        except (FeedbackError, MotionFaultError, KeyboardInterrupt) as fault:
            if issued and self.backend is not None:
                self.backend.stop()
            if current is not None:
                records.append(
                    self.aborted_record(current, validated, str(fault), executed=issued)
                )
                self.write_record(records[-1])
            return ExecutionResult(status="aborted", detail=str(fault), records=records)
        note = (
            "mock rehearsal completed; seating was emulated by position descent "
            "and no physical force or contact evidence exists; physical insertion "
            "not validated"
            if self.options.mock_execution
            else "commands completed; physical insertion not validated"
        )
        return ExecutionResult(status="completed", detail=note, records=records)

    def execute_step(self, step: Step, validated: ValidatedPlan) -> StepRecord:
        """Run one validated step and classify how it was performed.

        Args:
            step: Step to execute.
            validated: Limits and seating guards for the plan.

        Returns:
            Record with ``ok``, ``emulated`` or ``aborted`` status.

        Raises:
            ExecutionRefusedError: For hardware seating, which is always blocked.
            MotionFaultError: When a motion or guard fails.
        """
        speed = step.speed_m_s * validated.speed_scale
        if step.action in ("open", "close"):
            command = self.gripper_command(step)
            assert self.backend is not None
            self.backend.gripper(command)
            return StepRecord(
                index=step.index,
                action=step.action,
                brick_id=step.brick_id,
                target_xyz_m=step.xyz_m,
                target_rpy_deg=step.rpy_deg,
                effective_speed_m_s=0.0,
                status="ok",
                force_mode="none",
                executed=True,
                detail=f"gripper command {command}",
            )
        if step.action == "seat":
            return self.seat(step, validated)
        assert self.feedback is not None
        assert self.backend is not None
        current = self.feedback.tcp_position()
        for axis, (value, low, high) in enumerate(
            zip(
                current,
                validated.limits.workspace_min_m,
                validated.limits.workspace_max_m,
                strict=True,
            )
        ):
            if not low <= value <= high:
                raise MotionFaultError(
                    f"current TCP axis {axis} value {value} is outside workspace "
                    f"[{low}, {high}]"
                )
        duration_s = max(math.dist(current, step.xyz_m) / speed, MIN_SEGMENT_S)
        self.backend.move(
            step,
            duration_s,
            self.options.travel_guard_s,
            validated.limits,
            self.feedback.joint_positions(),
        )
        return StepRecord(
            index=step.index,
            action=step.action,
            brick_id=step.brick_id,
            target_xyz_m=step.xyz_m,
            target_rpy_deg=step.rpy_deg,
            effective_speed_m_s=speed,
            status="ok",
            force_mode="none",
            executed=True,
            detail=f"moved in {duration_s:.3f}s at {speed:.4f}m/s",
        )

    def seat(self, step: Step, validated: ValidatedPlan) -> StepRecord:
        """Rehearse seating as a strictly capped slow descent without force.

        The descent never claims contact or seated state: travel is only a
        position change, force mode is not started, and the hard cap
        ``seating.max_travel_m`` allows no extra tolerance.

        Args:
            step: Seat step whose pose is the final descent target.
            validated: Seating travel and timeout guards.

        Returns:
            Record with ``emulated`` status when the descent completes.

        Raises:
            ExecutionRefusedError: When not running in proven mock mode.
            MotionFaultError: When travel or elapsed time exceeds its hard cap.
        """
        if not self.options.mock_execution:
            raise ExecutionRefusedError(
                "hardware seating is blocked pending validated force and travel sensing"
            )
        assert self.feedback is not None
        assert self.backend is not None
        start_z = self.feedback.tcp_position()[2]
        travel = start_z - step.xyz_m[2]
        if travel < 0.0:
            raise MotionFaultError(
                f"plan[{step.index}] seat target is above the current TCP by "
                f"{-travel:.4f}m"
            )
        if travel > validated.seating.max_travel_m:
            raise MotionFaultError(
                f"plan[{step.index}] seat descent {travel:.4f}m exceeds hard cap "
                f"max_travel_m {validated.seating.max_travel_m}"
            )
        deadline = self.clock() + validated.seating.timeout_s
        speed = step.speed_m_s * validated.speed_scale
        substeps = math.ceil(travel / SEAT_SUBSTEP_M) if travel > 0.0 else 0
        for substep in range(1, substeps + 1):
            if self.clock() > deadline:
                raise MotionFaultError(
                    f"plan[{step.index}] seating exceeded timeout "
                    f"{validated.seating.timeout_s}s after {substep - 1} substeps"
                )
            current_z = self.feedback.tcp_position()[2]
            travelled = start_z - current_z
            if travelled > validated.seating.max_travel_m:
                raise MotionFaultError(
                    f"plan[{step.index}] seating overtravel: travelled "
                    f"{travelled:.4f}m exceeds max_travel_m "
                    f"{validated.seating.max_travel_m}"
                )
            target_z = start_z - min(substep * SEAT_SUBSTEP_M, travel)
            target = replace(step, xyz_m=(step.xyz_m[0], step.xyz_m[1], target_z))
            duration_s = max(SEAT_SUBSTEP_M / speed, MIN_SEGMENT_S / 10.0)
            self.backend.move(
                target,
                duration_s,
                self.options.travel_guard_s,
                validated.limits,
                self.feedback.joint_positions(),
            )
        current_z = self.feedback.tcp_position()[2]
        travelled = start_z - current_z
        if travelled > validated.seating.max_travel_m:
            raise MotionFaultError(
                f"plan[{step.index}] seating overtravel: travelled {travelled:.4f}m "
                f"exceeds max_travel_m {validated.seating.max_travel_m}"
            )
        if self.clock() > deadline:
            raise MotionFaultError(
                f"plan[{step.index}] seating exceeded timeout "
                f"{validated.seating.timeout_s}s"
            )
        return StepRecord(
            index=step.index,
            action=step.action,
            brick_id=step.brick_id,
            target_xyz_m=step.xyz_m,
            target_rpy_deg=step.rpy_deg,
            effective_speed_m_s=speed,
            status="emulated",
            force_mode="emulated",
            executed=True,
            detail=(
                f"emulated seating: positioned {travelled:.4f}m of {travel:.4f}m "
                "planned descent with no force applied and no contact evidence; "
                "hardware seating remains blocked"
            ),
        )

    def gripper_command(self, step: Step) -> str:
        """Build the gripper command string for a close or open step.

        Args:
            step: Gripper step with an optional width in millimetres.

        Returns:
            ``open``, ``close`` or an integer string in tenths of millimetres.
        """
        if step.gripper_width_mm is None:
            return step.action
        return str(round(step.gripper_width_mm * GRIPPER_TENTHS_PER_MM))

    def planned_record(self, step: Step, validated: ValidatedPlan) -> StepRecord:
        """Describe a validated step without executing it.

        Args:
            step: Step that would run.
            validated: Plan limits carrying the accepted speed scale.

        Returns:
            Record with ``planned`` status and no execution.
        """
        motion = step.action not in ("open", "close")
        return StepRecord(
            index=step.index,
            action=step.action,
            brick_id=step.brick_id,
            target_xyz_m=step.xyz_m,
            target_rpy_deg=step.rpy_deg,
            effective_speed_m_s=(
                step.speed_m_s * validated.speed_scale if motion else 0.0
            ),
            status="planned",
            force_mode="not_started",
            executed=False,
            detail="validated for dry run; no command issued",
        )

    def aborted_record(
        self, step: Step, validated: ValidatedPlan, detail: str, executed: bool = False
    ) -> StepRecord:
        """Describe a step that was aborted, with the reason.

        Args:
            step: Step that failed or was declined.
            validated: Plan limits carrying the accepted speed scale.
            detail: Human-readable abort reason.
            executed: Whether any command had been issued for the step.

        Returns:
            Record with ``aborted`` status.
        """
        motion = step.action not in ("open", "close")
        return StepRecord(
            index=step.index,
            action=step.action,
            brick_id=step.brick_id,
            target_xyz_m=step.xyz_m,
            target_rpy_deg=step.rpy_deg,
            effective_speed_m_s=(
                step.speed_m_s * validated.speed_scale if motion else 0.0
            ),
            status="aborted",
            force_mode="none",
            executed=executed,
            detail=detail,
        )

    def write_record(self, record: StepRecord) -> None:
        """Append one JSON line describing the record to ``step_log``.

        Args:
            record: Step outcome to persist.
        """
        payload = {
            "time_s": time.time(),
            "index": record.index,
            "action": record.action,
            "brick_id": record.brick_id,
            "target_xyz_m": list(record.target_xyz_m),
            "target_rpy_deg": list(record.target_rpy_deg),
            "effective_speed_m_s": record.effective_speed_m_s,
            "status": record.status,
            "force_mode": record.force_mode,
            "executed": record.executed,
            "dry_run": self.options.dry_run,
            "mock_execution": self.options.mock_execution,
            "frame": BASE_FRAME,
            "physical_insertion_validated": False,
            "detail": record.detail,
        }
        with Path(self.options.step_log).open("a", encoding="utf-8") as log_file:
            log_file.write(json.dumps(payload) + "\n")


def main(args: list[str] | None = None) -> None:
    """Load config and structure, then run the executor with ROS parameters.

    Args:
        args: Optional ROS argument list forwarded to ``rclpy.init``.
    """
    from risl_contact_assembly.planner import (
        load_config,
        load_structure,
        plan_structure,
    )

    rclpy.init(args=args)
    node = Node("risl_contact_assembly_executor")
    try:
        from ament_index_python.packages import get_package_share_directory

        share = Path(get_package_share_directory("risl_contact_assembly"))
        config_file = (
            node.declare_parameter("config_file", str(share / "config/assembly.yaml"))
            .get_parameter_value()
            .string_value
        )
        structure_file = (
            node.declare_parameter(
                "structure_file", str(share / "fixtures/single_brick.json")
            )
            .get_parameter_value()
            .string_value
        )
        options = ExecutorOptions(
            dry_run=node.declare_parameter("dry_run", True)
            .get_parameter_value()
            .bool_value,
            confirm_each_step=node.declare_parameter("confirm_each_step", True)
            .get_parameter_value()
            .bool_value,
            pose_source=node.declare_parameter("pose_source", "known_poses")
            .get_parameter_value()
            .string_value,
            step_log=node.declare_parameter("step_log", "assembly_steps.jsonl")
            .get_parameter_value()
            .string_value,
            mock_execution=node.declare_parameter("mock_execution", False)
            .get_parameter_value()
            .bool_value,
            mock_hardware_proof=node.declare_parameter("mock_hardware_proof", "")
            .get_parameter_value()
            .string_value,
            speed_scale=node.declare_parameter("speed_scale", 1.0)
            .get_parameter_value()
            .double_value,
            feedback_timeout_s=node.declare_parameter("feedback_timeout_s", 1.0)
            .get_parameter_value()
            .double_value,
            travel_guard_s=node.declare_parameter("travel_guard_s", 5.0)
            .get_parameter_value()
            .double_value,
        )
        config = load_config(config_file)
        plan = plan_structure(load_structure(structure_file), config)
        result = AssemblyExecutor(node, plan, config, options).run()
        node.get_logger().info(f"assembly {result.status}: {result.detail}")
        if result.status == "aborted":
            raise SystemExit(1)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
