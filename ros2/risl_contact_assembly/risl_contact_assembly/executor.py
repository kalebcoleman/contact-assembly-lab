"""Run a planned brick assembly on the arm, one confirmed step at a time.

A dry run (the default) plans every move from the current joint angles and
prints the result without commanding anything. ``execute`` is required for
motion. Frames and units follow ``planner``.
"""

import json
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from signal import SIGINT, SIGTERM, default_int_handler, signal
from typing import TypeVar

import numpy as np
import rclpy
from ament_index_python.packages import get_package_share_directory
from rclpy.node import Node
from rclpy.signals import SignalHandlerOptions
from risl_ur.custom_libraries.ik_solver import dh_params, forward_kinematics

from risl_contact_assembly.motion import plan_move
from risl_contact_assembly.planner import (
    Move,
    Plan,
    Positions,
    Step,
    load_positions,
    load_structure,
    plan_assembly,
)
from risl_contact_assembly.robot import RosRobot

STARTUP_TIMEOUT_S = 30.0
PROGRAM_START_TIMEOUT_S = 300.0
MONITOR_PERIOD_S = 0.02
MOVE_TIMEOUT_MARGIN_S = 5.0
MIN_SPEED_FRACTION = 0.1
# Measured tool speed is averaged over this window and may exceed the speed of
# the move by this factor before the run aborts.
SPEED_WINDOW_S = 0.1
OVERSPEED_FACTOR = 1.5
WORKSPACE_MARGIN_M = 0.002
ARRIVAL_TOLERANCE_M = 0.0005
SETTLE_TIMEOUT_S = 2.0
GRIPPER_POLL_S = 0.25
GRIPPER_SETTLE_S = 1.0
GRIPPER_TIMEOUT_S = 6.0
GRIPPER_STILL_MM = 0.2
CAMERA_MAX_SHIFT_M = 0.03

Feedback = TypeVar("Feedback")


class AbortError(RuntimeError):
    """Raised to stop a run; motion is cancelled before it propagates."""


def camera_pickups(
    robot: RosRobot, positions: Positions, names: list[str]
) -> Positions:
    """Replace each taught pickup XY with the camera's brick position.

    The localizer must publish each brick's centre in ``base`` on
    ``/vision/object_poses/<brick name>``. Height and orientation stay as
    taught, and the tool is assumed vertical so its XY equals the brick's.

    Args:
        robot: Source of camera poses.
        positions: Taught positions.
        names: Bricks of the structure being built.

    Returns:
        Positions with shifted pickup poses.

    Raises:
        AbortError: If a brick has no pose or lies more than ``CAMERA_MAX_SHIFT_M``
            from its taught pickup.
    """
    pickups = dict(positions.pickups)
    for name in names:
        taught = positions.pickups[name]
        xy = robot.object_xy(name)
        if xy is None:
            raise AbortError(f"no pose in base on /vision/object_poses/{name}")
        shift_m = float(np.linalg.norm(xy - taught[:2, 3]))
        if shift_m > CAMERA_MAX_SHIFT_M:
            raise AbortError(
                f"camera places {name} {shift_m * 1000:.0f} mm from its taught "
                f"pickup (limit {CAMERA_MAX_SHIFT_M * 1000:.0f} mm)"
            )
        pickups[name] = taught.copy()
        pickups[name][:2, 3] = xy
    return replace(positions, pickups=pickups)


def confirm_on_terminal(prompt: str) -> None:
    """Block until the operator presses Enter on the controlling terminal.

    ``/dev/tty`` is used because ``ros2 launch`` does not forward stdin.

    Args:
        prompt: Text shown before waiting.

    Raises:
        AbortError: If the terminal is closed.
    """
    with open("/dev/tty", "rb+", buffering=0) as terminal:
        terminal.write(f"\n>>> {prompt} - Enter to go, Ctrl-C to abort: ".encode())
        if not terminal.readline():
            raise AbortError("terminal closed while waiting for confirmation")


class Executor:
    """Executes a plan with feedback guards on every move and grasp."""

    def __init__(
        self,
        robot: RosRobot,
        positions: Positions,
        plan: Plan,
        *,
        execute: bool,
        auto_continue: bool,
        fake_hardware: bool,
        confirm: Callable[[str], None],
        log: Callable[[str], None],
        step_log: str = "",
    ) -> None:
        """Store the plan and its collaborators.

        Args:
            robot: Arm and gripper interface.
            positions: Limits the plan was made with.
            plan: Steps from ``plan_assembly``.
            execute: Command the robot. False plans and prints only.
            auto_continue: After one fully confirmed run, offer repeat runs
                that need a single confirmation each.
            fake_hardware: The driver runs mock hardware, which has no pendant
                program and no force signal; both checks are skipped.
            confirm: Blocks until the operator approves the described action.
            log: Receives progress messages.
            step_log: Optional JSON Lines file receiving one record per step.
        """
        self.robot = robot
        self.positions = positions
        self.plan = plan
        self.execute = execute
        self.auto_continue = auto_continue
        self.fake_hardware = fake_hardware
        self.confirm = confirm
        self.log = log
        self.step_log = step_log

    def read(
        self,
        getter: Callable[[], Feedback | None],
        problem: str,
        timeout_s: float = 0.0,
    ) -> Feedback:
        """Return a feedback value, waiting for it up to a timeout.

        Args:
            getter: Returns the value, or None or False while unavailable.
            problem: AbortError message when the value never arrives.
            timeout_s: Longest wait; zero requires the value immediately.

        Returns:
            The first available value.

        Raises:
            AbortError: If the value is still unavailable at the timeout.
        """
        deadline = self.robot.now() + timeout_s
        while True:
            value = getter()
            if value is not None and value is not False:
                return value
            if self.robot.now() >= deadline:
                raise AbortError(problem)
            self.robot.wait(0.1)

    def run(self) -> None:
        """Check the start state, preview every move, then execute if enabled.

        Raises:
            AbortError: On any failed check, guard or timeout. Active motion is
                cancelled first, also on Ctrl-C.
        """
        try:
            joints = self.read(
                self.robot.joints,
                "no /joint_states: is the driver running?",
                STARTUP_TIMEOUT_S,
            )
            tool = forward_kinematics(dh_params, joints)
            safety = self.positions.safety
            motion = self.positions.motion
            if np.any(tool[:3, 3] < safety.workspace_min_m) or np.any(
                tool[:3, 3] > safety.workspace_max_m
            ):
                raise AbortError(
                    f"tool0 is at {np.round(tool[:3, 3], 3).tolist()} m, outside "
                    "the workspace box: jog it inside first"
                )
            tilt_deg = np.degrees(np.arccos(np.clip(-tool[2, 2], -1.0, 1.0)))
            if tilt_deg > safety.max_tilt_deg:
                raise AbortError(
                    f"tool is tilted {tilt_deg:.0f} deg from straight down: jog "
                    "it to point at the table first"
                )
            steps = list(self.plan.steps)
            if tool[2, 3] < self.plan.travel_z_m - 1e-4:
                raised = tool.copy()
                raised[2, 3] = self.plan.travel_z_m
                steps.insert(
                    0,
                    Step(
                        "start: raise to travel height",
                        moves=(Move(raised, motion.travel_speed_m_s),),
                    ),
                )

            total_s = 0.0
            for index, step in enumerate(steps, start=1):
                if step.moves:
                    step_s = 0.0
                    for move in step.moves:
                        times, positions, _ = plan_move(joints, move, motion)
                        if len(times):
                            joints = positions[-1]
                            step_s += times[-1]
                    total_s += step_s
                    target_mm = np.round(step.moves[-1].pose[:3, 3] * 1000, 1)
                    detail = f"to {target_mm.tolist()} mm in {step_s:.1f} s"
                else:
                    detail = (
                        f"gripper to {step.gripper_mm:.1f} mm, must report "
                        f"{step.expected_mm:.1f} mm"
                    )
                self.log(f"{index:3d}. {step.label}: {detail}")
            self.log(
                f"{len(steps)} steps, {total_s:.0f} s of motion, travel height "
                f"z = {self.plan.travel_z_m:.3f} m; every move is reachable"
            )
            if not self.execute:
                self.log("DRY RUN: nothing was commanded. Add execute:=true to move.")
                return

            if not self.fake_hardware:
                self.log("waiting for the External Control program on the pendant")
                self.read(
                    self.robot.program_running,
                    "External Control is not running: press Play on the pendant",
                    PROGRAM_START_TIMEOUT_S,
                )
                self.read(
                    self.robot.force,
                    "no tool force on /force_torque_sensor_broadcaster/wrench",
                    STARTUP_TIMEOUT_S,
                )
            self.read(
                self.robot.controller_ready,
                "scaled_joint_trajectory_controller is not available",
                STARTUP_TIMEOUT_S,
            )
            fraction = self.read(
                self.robot.speed_fraction, "no speed scaling", STARTUP_TIMEOUT_S
            )
            self.log(f"pendant speed slider: {fraction:.0%} of the planned speed")

            confirming = True
            while True:
                for index, step in enumerate(steps, start=1):
                    if confirming:
                        self.confirm(f"[{index}/{len(steps)}] {step.label}")
                    self.log(f"[{index}/{len(steps)}] {step.label}")
                    self.run_step(step)
                self.log("assembly complete")
                if not self.auto_continue:
                    return
                self.confirm(
                    "reset the bricks to their pickups; the next run will not "
                    "stop between steps"
                )
                confirming = False
                steps = self.plan.steps
        except BaseException:
            if self.execute:
                self.robot.cancel()
            raise

    def run_step(self, step: Step) -> None:
        """Run one step: the gripper command or width check, then the moves.

        Args:
            step: Step to run.

        Raises:
            AbortError: If the gripper reports an unexpected width or a move fails.
        """
        width = None
        if step.expected_mm is not None:
            commanded_at = self.robot.now()
            settle_s = 0.0
            if step.gripper_mm is not None:
                # /gripper_command takes tenths of a millimetre.
                self.robot.gripper(str(round(step.gripper_mm * 10)))
                settle_s = GRIPPER_SETTLE_S
            previous = None
            while True:
                self.robot.gripper("query")
                self.robot.wait(GRIPPER_POLL_S)
                width = self.robot.gripper_width()
                elapsed_s = self.robot.now() - commanded_at
                if (
                    width is not None
                    and previous is not None
                    and abs(width - previous) < GRIPPER_STILL_MM
                    and elapsed_s >= settle_s
                ):
                    break
                if elapsed_s > GRIPPER_TIMEOUT_S:
                    raise AbortError(f"{step.label}: no steady gripper width reported")
                previous = width
            tolerance_mm = self.positions.gripper.width_tolerance_mm
            if abs(width - step.expected_mm) > tolerance_mm:
                raise AbortError(
                    f"{step.label}: gripper reports {width:.1f} mm, expected "
                    f"{step.expected_mm:.1f} mm (missed or dropped brick?)"
                )
        results = [self.move(step.label, move) for move in step.moves]
        tool = forward_kinematics(
            dh_params, self.read(self.robot.joints, "joint feedback lost")
        )
        if self.step_log:
            record = {
                "step": step.label,
                "tool_xyz_m": np.round(tool[:3, 3], 5).tolist(),
                "peak_speed_m_s": round(max([0.0, *results]), 4),
                "gripper_mm": width,
            }
            with Path(self.step_log).open("a", encoding="utf-8") as log_file:
                log_file.write(json.dumps(record) + "\n")

    def move(self, label: str, move: Move) -> float:
        """Execute one straight-line move under feedback guards.

        The move aborts on stale joint feedback, a tool position outside the
        workspace box, measured tool speed above the planned speed, a timeout, a
        controller failure, or not arriving at the target. A ``guard`` move
        also aborts when the tool force changes by more than
        ``safety.press_force_n``; a ``seat`` move stops there and succeeds.

        Args:
            label: Step label for messages.
            move: Target pose, speed and contact behaviour.

        Returns:
            Peak measured tool speed, m/s.

        Raises:
            AbortError: When a guard trips.
        """
        safety = self.positions.safety
        joints = self.read(self.robot.joints, "joint feedback lost")
        times, positions, velocities = plan_move(joints, move, self.positions.motion)
        if len(times) == 0:
            return 0.0
        force_start = None
        if move.contact != "free" and not self.fake_hardware:
            force_start = self.read(self.robot.force, "tool force feedback lost")
        fraction = self.read(self.robot.speed_fraction, "speed scaling feedback lost")
        if fraction < MIN_SPEED_FRACTION:
            raise AbortError(
                f"{label}: speed scaling is {fraction:.0%}; raise the pendant "
                "speed slider or clear the robot stop"
            )
        deadline = self.robot.now() + times[-1] / fraction + MOVE_TIMEOUT_MARGIN_S
        self.robot.send(times, positions, velocities)
        sample_time = self.robot.now()
        sample_position = forward_kinematics(dh_params, joints)[:3, 3]
        peak_speed = 0.0
        stopped_by_contact = False
        while not stopped_by_contact:
            self.robot.wait(MONITOR_PERIOD_S)
            state = self.robot.motion_state()
            if state == "succeeded":
                break
            if state != "active":
                raise AbortError(f"{label}: trajectory {state}")
            now = self.robot.now()
            if now > deadline:
                raise AbortError(f"{label}: timed out")
            position = forward_kinematics(
                dh_params, self.read(self.robot.joints, "joint feedback lost")
            )[:3, 3]
            if np.any(position < safety.workspace_min_m - WORKSPACE_MARGIN_M) or np.any(
                position > safety.workspace_max_m + WORKSPACE_MARGIN_M
            ):
                raise AbortError(f"{label}: tool left the workspace box")
            if now - sample_time >= SPEED_WINDOW_S:
                speed = float(np.linalg.norm(position - sample_position)) / (
                    now - sample_time
                )
                peak_speed = max(peak_speed, speed)
                if speed > OVERSPEED_FACTOR * move.speed_m_s:
                    raise AbortError(f"{label}: tool moving at {speed:.3f} m/s")
                sample_time, sample_position = now, position
            if force_start is not None:
                force = self.read(self.robot.force, "tool force feedback lost")
                change_n = float(np.linalg.norm(force - force_start))
                if change_n > safety.press_force_n:
                    self.robot.cancel()
                    if move.contact == "guard":
                        raise AbortError(
                            f"{label}: unexpected contact ({change_n:.0f} N)"
                        )
                    stopped_by_contact = True

        # The controller reports success within its goal tolerance; wait for
        # the arm to come to rest and require it at the target unless contact
        # stopped it early.
        settle_deadline = self.robot.now() + SETTLE_TIMEOUT_S
        while True:
            position = forward_kinematics(
                dh_params, self.read(self.robot.joints, "joint feedback lost")
            )[:3, 3]
            error_m = float(np.linalg.norm(position - move.pose[:3, 3]))
            if stopped_by_contact and self.robot.motion_state() != "active":
                self.log(
                    f"{label}: stopped at the force limit {error_m * 1000:.1f} mm "
                    "above the commanded height"
                )
                break
            if not stopped_by_contact and error_m <= ARRIVAL_TOLERANCE_M:
                break
            if self.robot.now() > settle_deadline:
                raise AbortError(
                    f"{label}: stopped {error_m * 1000:.1f} mm from target"
                )
            self.robot.wait(MONITOR_PERIOD_S)
        return peak_speed


def main(args: list[str] | None = None) -> None:
    """Run the executor node.

    Parameters: ``positions_file``, ``structure_file``, ``execute`` (default
    false), ``auto_continue``, ``fake_hardware``, ``camera`` and ``step_log``.

    Args:
        args: ROS arguments.

    Raises:
        SystemExit: With status 1 when the run aborts.
    """
    # rclpy's own handler would shut the context down before the trajectory
    # could be cancelled, so Ctrl-C and SIGTERM raise KeyboardInterrupt here.
    signal(SIGINT, default_int_handler)
    signal(SIGTERM, default_int_handler)
    rclpy.init(args=args, signal_handler_options=SignalHandlerOptions.NO)
    node = Node("assembly_executor")
    share = Path(get_package_share_directory("risl_contact_assembly"))
    positions_file = node.declare_parameter(
        "positions_file", str(share / "config" / "demo_positions.yaml")
    ).value
    structure_file = node.declare_parameter(
        "structure_file", str(share / "structures" / "three_bricks.json")
    ).value
    execute = node.declare_parameter("execute", False).value
    robot = RosRobot(node, commands=execute)
    try:
        positions = load_positions(positions_file)
        structure = load_structure(structure_file)
        if node.declare_parameter("camera", False).value:
            positions = camera_pickups(robot, positions, structure["part_names"])
        Executor(
            robot,
            positions,
            plan_assembly(structure, positions),
            execute=execute,
            auto_continue=node.declare_parameter("auto_continue", False).value,
            fake_hardware=node.declare_parameter("fake_hardware", False).value,
            confirm=confirm_on_terminal,
            log=node.get_logger().info,
            step_log=node.declare_parameter("step_log", "").value,
        ).run()
    except (AbortError, ValueError, KeyboardInterrupt) as stop:
        node.get_logger().error(f"ABORTED: {str(stop) or 'interrupted'}")
        raise SystemExit(1) from stop
    finally:
        robot.close()
        rclpy.shutdown()
