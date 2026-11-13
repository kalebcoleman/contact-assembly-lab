"""Tests for the executor against a simulated arm and gripper."""

import json
from pathlib import Path

import numpy as np
import pytest
from risl_contact_assembly.executor import AbortError, Executor, camera_pickups
from risl_contact_assembly.motion import plan_move
from risl_contact_assembly.planner import (
    Move,
    Positions,
    load_positions,
    load_structure,
    plan_assembly,
)
from risl_contact_assembly.robot import RosRobot
from risl_ur.custom_libraries.ik_solver import dh_params, forward_kinematics

PACKAGE = Path(__file__).resolve().parents[1]
START_JOINTS = np.radians([90.0, -80.0, 90.0, -100.0, -90.0, 0.0])
STEPS = 9


class SimulatedRobot(RosRobot):
    """Arm that tracks trajectories exactly on a simulated clock.

    Attributes set by tests inject faults: ``stalled`` freezes the arm,
    ``contact_below_z_m`` adds ``contact_force_n`` of tool force below a tool
    height, ``brick_width_mm`` is what the fingers close on, and
    ``joint_feedback`` and ``gripper_feedback`` switch feedback off.
    """

    def __init__(self) -> None:
        """Start at rest at ``START_JOINTS`` with an open, empty-handed gripper."""
        self.time_s = 0.0
        self.joint_angles = START_JOINTS.copy()
        self.trajectory: tuple[float, np.ndarray, np.ndarray] | None = None
        self.state = "idle"
        self.sent: list[np.ndarray] = []
        self.cancels = 0
        self.commands: list[str] = []
        self.width_mm = 110.0
        self.brick_width_mm = 15.8
        self.scaling = 1.0
        self.running = True
        self.stalled = False
        self.joint_feedback = True
        self.gripper_feedback = True
        self.contact_below_z_m = -np.inf
        self.contact_force_n = 0.0
        self.objects: dict[str, np.ndarray] = {}

    def now(self) -> float:
        """Return simulated time.

        Returns:
            Seconds since construction.
        """
        return self.time_s

    def wait(self, seconds: float) -> None:
        """Advance simulated time and move the arm along its trajectory.

        Args:
            seconds: Time step.
        """
        self.time_s += seconds
        if self.trajectory is None or self.state != "active" or self.stalled:
            return
        start_s, times, positions = self.trajectory
        elapsed_s = (self.time_s - start_s) * self.scaling
        self.joint_angles = np.array(
            [np.interp(elapsed_s, times, positions[:, joint]) for joint in range(6)]
        )
        if elapsed_s >= times[-1]:
            self.state = "succeeded"

    def joints(self) -> np.ndarray | None:
        """Return the simulated joint angles.

        Returns:
            Six angles, radians, or None while feedback is switched off.
        """
        return self.joint_angles if self.joint_feedback else None

    def force(self) -> np.ndarray | None:
        """Return gravity-like bias plus contact force below the contact height.

        Returns:
            Tool force, newtons.
        """
        tool_z_m = forward_kinematics(dh_params, self.joint_angles)[2, 3]
        contact_n = self.contact_force_n if tool_z_m < self.contact_below_z_m else 0.0
        return np.array([1.0, -2.0, 7.0 + contact_n])

    def speed_fraction(self) -> float | None:
        """Return the simulated speed scaling.

        Returns:
            Fraction of programmed speed.
        """
        return self.scaling

    def gripper_width(self) -> float | None:
        """Return the simulated finger width.

        Returns:
            Width, millimetres, or None while feedback is switched off.
        """
        return self.width_mm if self.gripper_feedback else None

    def program_running(self) -> bool:
        """Return the simulated pendant program state.

        Returns:
            True while External Control runs.
        """
        return self.running

    def controller_ready(self) -> bool:
        """Report the trajectory controller as available.

        Returns:
            True.
        """
        return True

    def gripper(self, command: str) -> None:
        """Apply a width command in tenths of a millimetre, stopping on the brick.

        Args:
            command: ``query`` or tenths of a millimetre.
        """
        if command != "query":
            self.commands.append(command)
            self.width_mm = max(int(command) / 10.0, self.brick_width_mm)

    def send(
        self, times: np.ndarray, positions: np.ndarray, velocities: np.ndarray
    ) -> None:
        """Start following a trajectory from the current joints.

        Args:
            times: Sample times, seconds.
            positions: Joint samples, radians.
            velocities: Joint velocities, rad/s; unused.
        """
        self.sent.append(positions)
        self.trajectory = (
            self.time_s,
            np.concatenate([[0.0], times]),
            np.vstack([self.joint_angles, positions]),
        )
        self.state = "active"

    def motion_state(self) -> str:
        """Report the simulated trajectory state.

        Returns:
            ``active``, ``succeeded`` or ``canceled``.
        """
        return self.state

    def cancel(self) -> None:
        """Stop where the arm is."""
        self.cancels += 1
        if self.state == "active":
            self.state = "canceled"

    def object_xy(self, name: str) -> np.ndarray | None:
        """Return a simulated camera position.

        Args:
            name: Object name.

        Returns:
            ``[x, y]`` in ``base``, metres, or None when unseen.
        """
        return self.objects.get(name)


class Run:
    """One executor wired to a simulated robot, recording prompts and logs."""

    def __init__(self, tmp_path: Path, **options: bool) -> None:
        """Plan the single-brick structure with the demo positions.

        Args:
            tmp_path: Directory for the step log.
            **options: Executor options overriding an executing fake-hardware run.
        """
        self.robot = SimulatedRobot()
        self.positions = load_positions(PACKAGE / "config" / "demo_positions.yaml")
        self.plan = plan_assembly(
            load_structure(PACKAGE / "structures" / "single_brick.json"),
            self.positions,
        )
        self.prompts: list[str] = []
        self.messages: list[str] = []
        self.step_log = tmp_path / "steps.jsonl"
        settings = {
            "execute": True,
            "auto_continue": False,
            "fake_hardware": True,
        } | options
        self.executor = Executor(
            self.robot,
            self.positions,
            self.plan,
            confirm=self.prompts.append,
            log=self.messages.append,
            step_log=str(self.step_log),
            **settings,
        )

    def tool_xyz(self) -> np.ndarray:
        """Return the simulated tool origin.

        Returns:
            Position in ``base``, metres.
        """
        return forward_kinematics(dh_params, self.robot.joint_angles)[:3, 3]


def test_dry_run_commands_nothing(tmp_path: Path) -> None:
    """The default mode previews every step and never sends a command."""
    run = Run(tmp_path, execute=False)
    run.executor.run()
    assert run.robot.sent == []
    assert run.robot.commands == []
    assert run.prompts == []
    assert any("DRY RUN" in message for message in run.messages)
    assert sum("single_0" in message for message in run.messages) == STEPS
    assert run.tool_xyz() == pytest.approx(
        forward_kinematics(dh_params, START_JOINTS)[:3, 3]
    )


def test_confirmed_run_places_the_brick(tmp_path: Path) -> None:
    """Every step is confirmed, widths go out in tenths of a millimetre."""
    run = Run(tmp_path)
    run.executor.run()
    assert len(run.prompts) == STEPS
    assert run.robot.commands == ["238", "118", "238"]
    records = [json.loads(line) for line in run.step_log.read_text().splitlines()]
    assert [record["step"] for record in records] == [
        step.label for step in run.plan.steps
    ]
    seat = run.plan.steps[6].moves[-1].pose[:3, 3]
    assert records[6]["tool_xyz_m"] == pytest.approx(seat.tolist(), abs=1e-4)
    assert records[3]["gripper_mm"] == pytest.approx(15.8)
    assert max(record["peak_speed_m_s"] for record in records) <= 0.0505
    assert max(records[i]["peak_speed_m_s"] for i in (2, 6)) > 0.04
    assert run.tool_xyz()[2] == pytest.approx(run.plan.travel_z_m, abs=1e-4)
    assert run.robot.cancels == 0


def test_start_below_travel_height_rises_vertically_first(tmp_path: Path) -> None:
    """A low start adds a vertical raise before any sideways motion."""
    run = Run(tmp_path)
    low = forward_kinematics(dh_params, START_JOINTS)
    low[2, 3] = 0.12
    _, positions, _ = plan_move(START_JOINTS, Move(low, 0.05), run.positions.motion)
    run.robot.joint_angles = positions[-1]
    start_xy = run.tool_xyz()[:2].copy()
    run.executor.run()
    assert run.prompts[0] == f"[1/{STEPS + 1}] start: raise to travel height"
    raised = forward_kinematics(dh_params, run.robot.sent[0][-1])[:3, 3]
    assert raised[:2] == pytest.approx(start_xy, abs=1e-4)
    assert raised[2] == pytest.approx(run.plan.travel_z_m, abs=1e-4)


def test_missed_grasp_aborts_before_lifting(tmp_path: Path) -> None:
    """Fingers closing past the brick width stop the run at the grasp."""
    run = Run(tmp_path)
    run.robot.brick_width_mm = 0.0
    with pytest.raises(
        AbortError, match="grasp: gripper reports 11.8 mm, expected 15.8"
    ):
        run.executor.run()
    assert len(run.prompts) == 4
    assert len(run.robot.sent) == 3


def test_brick_lost_during_lift_aborts_before_placing(tmp_path: Path) -> None:
    """A width change while carrying stops the run before the next move."""
    run = Run(tmp_path)

    def confirm(prompt: str) -> None:
        if "move above place" in prompt:
            run.robot.width_mm = 11.8

    run.executor.confirm = confirm
    with pytest.raises(AbortError, match="move above place: gripper reports 11.8"):
        run.executor.run()
    assert len(run.robot.sent) == 5


def test_missing_gripper_feedback_aborts(tmp_path: Path) -> None:
    """No width report within the timeout stops the run before any motion."""
    run = Run(tmp_path)
    run.robot.gripper_feedback = False
    with pytest.raises(AbortError, match="no steady gripper width"):
        run.executor.run()
    assert run.robot.sent == []


def test_seating_stops_at_the_force_cap_and_continues(tmp_path: Path) -> None:
    """Contact force during the seat move ends it early and the run goes on."""
    run = Run(tmp_path, fake_hardware=False)
    seat_z_m = run.plan.steps[6].moves[-1].pose[2, 3]
    run.robot.contact_below_z_m = seat_z_m + 0.003

    def confirm(prompt: str) -> None:
        # Contact exists only while the carried brick meets the plate.
        run.robot.contact_force_n = 25.0 if "descend and seat" in prompt else 0.0

    run.executor.confirm = confirm
    run.executor.run()
    records = [json.loads(line) for line in run.step_log.read_text().splitlines()]
    assert seat_z_m + 0.002 < records[6]["tool_xyz_m"][2] < seat_z_m + 0.003
    assert any("stopped at the force limit" in message for message in run.messages)
    assert run.robot.commands == ["238", "118", "238"]
    assert run.robot.cancels == 1


def test_force_below_the_cap_does_not_stop_seating(tmp_path: Path) -> None:
    """A force change under the cap lets the seat move reach its target."""
    run = Run(tmp_path, fake_hardware=False)
    run.robot.contact_below_z_m = 1.0
    run.robot.contact_force_n = 15.0
    run.executor.run()
    assert run.robot.cancels == 0


def test_contact_while_descending_to_pick_aborts(tmp_path: Path) -> None:
    """Contact force on the guarded pick approach cancels motion and aborts."""
    run = Run(tmp_path, fake_hardware=False)
    pick_z_m = run.plan.steps[2].moves[-1].pose[2, 3]
    run.robot.contact_below_z_m = pick_z_m + 0.005
    run.robot.contact_force_n = 25.0
    with pytest.raises(AbortError, match="descend to pick: unexpected contact"):
        run.executor.run()
    assert run.robot.cancels >= 1
    assert run.tool_xyz()[2] > pick_z_m + 0.004


def test_stalled_arm_times_out_and_cancels(tmp_path: Path) -> None:
    """A trajectory that never finishes aborts and is cancelled."""
    run = Run(tmp_path)
    run.robot.stalled = True
    with pytest.raises(AbortError, match="timed out"):
        run.executor.run()
    assert run.robot.cancels == 1
    assert run.robot.state == "canceled"


def test_slow_pendant_slider_extends_the_timeout(tmp_path: Path) -> None:
    """Half speed scaling finishes without a timeout and stays under the cap."""
    run = Run(tmp_path)
    run.robot.scaling = 0.5
    run.executor.run()
    records = [json.loads(line) for line in run.step_log.read_text().splitlines()]
    assert max(record["peak_speed_m_s"] for record in records) <= 0.026


def test_stopped_robot_is_refused(tmp_path: Path) -> None:
    """Zero speed scaling (protective stop or paused program) aborts the move."""
    run = Run(tmp_path)
    run.robot.scaling = 0.0
    with pytest.raises(AbortError, match="speed scaling is 0%"):
        run.executor.run()
    assert run.robot.sent == []


def test_ctrl_c_cancels_active_motion(tmp_path: Path) -> None:
    """KeyboardInterrupt during a move cancels the trajectory and propagates."""
    run = Run(tmp_path)
    wait = run.robot.wait

    def interrupted_wait(seconds: float) -> None:
        wait(seconds)
        if len(run.robot.sent) == 2 and run.robot.time_s > 12.0:
            raise KeyboardInterrupt

    run.robot.wait = interrupted_wait
    with pytest.raises(KeyboardInterrupt):
        run.executor.run()
    assert run.robot.state == "canceled"


def test_lost_joint_feedback_aborts_and_cancels(tmp_path: Path) -> None:
    """Stale joint states during a move abort it."""
    run = Run(tmp_path)
    wait = run.robot.wait

    def wait_then_lose_feedback(seconds: float) -> None:
        wait(seconds)
        run.robot.joint_feedback = len(run.robot.sent) < 2

    run.robot.wait = wait_then_lose_feedback
    with pytest.raises(AbortError, match="joint feedback lost"):
        run.executor.run()
    assert run.robot.state == "canceled"


def test_start_outside_workspace_is_refused(tmp_path: Path) -> None:
    """A start pose outside the box aborts before the preview."""
    run = Run(tmp_path)
    run.robot.joint_angles = np.radians([0.0, -90.0, 0.0, -90.0, 0.0, 0.0])
    with pytest.raises(AbortError, match="outside the workspace box"):
        run.executor.run()
    assert run.robot.sent == []


def test_real_hardware_waits_for_external_control(tmp_path: Path) -> None:
    """Without the pendant program running, a real run never starts."""
    run = Run(tmp_path, fake_hardware=False)
    run.robot.running = False
    with pytest.raises(AbortError, match="press Play on the pendant"):
        run.executor.run()
    assert run.robot.sent == []
    assert run.robot.commands == []


def test_auto_continue_repeats_only_after_a_confirmed_run(tmp_path: Path) -> None:
    """The second run needs one confirmation; the first needs one per step."""
    run = Run(tmp_path, auto_continue=True)

    def confirm(prompt: str) -> None:
        run.prompts.append(prompt)
        if prompt.startswith("reset the bricks") and len(run.prompts) > STEPS + 1:
            raise KeyboardInterrupt

    run.executor.confirm = confirm
    with pytest.raises(KeyboardInterrupt):
        run.executor.run()
    assert len(run.prompts) == STEPS + 2
    assert run.prompts[STEPS].startswith("reset the bricks")
    assert run.robot.commands == ["238", "118", "238"] * 2


def test_camera_shifts_pickup_xy_within_its_limit() -> None:
    """Camera XY replaces the taught XY; height and orientation stay taught."""
    robot = SimulatedRobot()
    positions: Positions = load_positions(PACKAGE / "config" / "demo_positions.yaml")
    taught = positions.pickups["single_0"]
    robot.objects["single_0"] = taught[:2, 3] + [0.010, -0.005]
    shifted = camera_pickups(robot, positions, ["single_0"]).pickups["single_0"]
    assert shifted[:2, 3] == pytest.approx(taught[:2, 3] + [0.010, -0.005])
    assert shifted[2, 3] == taught[2, 3]
    assert shifted[:3, :3] == pytest.approx(taught[:3, :3])

    robot.objects["single_0"] = taught[:2, 3] + [0.040, 0.0]
    with pytest.raises(AbortError, match="40 mm from its taught pickup"):
        camera_pickups(robot, positions, ["single_0"])
    with pytest.raises(AbortError, match="no pose in base"):
        camera_pickups(robot, positions, ["tower_0"])
