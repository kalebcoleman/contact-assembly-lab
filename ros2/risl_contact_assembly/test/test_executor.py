"""Unit tests for the assembly executor.

Tests never create a ROS node, never construct the Max motion stack, and never
touch hardware.  Feedback and motion are injected fakes; every fake that reacts
to a command records it so tests can prove which endpoint was used.
"""

import json
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
from pathlib import Path

import pytest
from geometry_msgs.msg import PoseStamped
from risl_contact_assembly.executor import (
    JOINT_NAMES,
    AssemblyExecutor,
    ExecutionRefusedError,
    ExecutorOptions,
    FeedbackError,
    MotionFaultError,
    PlanValidationError,
    RosFeedback,
    Step,
    validate_plan,
)
from sensor_msgs.msg import JointState


class FakeClock:
    """Monotonic clock fake that advances on every read."""

    def __init__(self, start_s: float = 0.0, step_s: float = 0.0) -> None:
        """Store the initial time and the advance per read.

        Args:
            start_s: First value returned.
            step_s: Seconds added to the stored time on every read.
        """
        self.now_s = start_s
        self.step_s = step_s

    def __call__(self) -> float:
        """Return the current fake time and advance it.

        Returns:
            Fake monotonic time in seconds.
        """
        value = self.now_s
        self.now_s += self.step_s
        return value


class FakeFeedback:
    """Feedback fake with switchable missing and stale faults."""

    def __init__(
        self,
        position: tuple[float, float, float] = (0.0, 0.0, 0.0104),
        missing: bool = False,
        stale: bool = False,
    ) -> None:
        """Store the reported TCP position and fault flags.

        Args:
            position: TCP xyz in metres reported to the executor.
            missing: Raise ``FeedbackError`` as for absent messages.
            stale: Raise ``FeedbackError`` as for old messages.
        """
        self.position = position
        self.missing = missing
        self.stale = stale
        self.joints: tuple[float, ...] = (0.0,) * len(JOINT_NAMES)

    def require_fresh(self) -> None:
        """Raise the configured feedback fault.

        Raises:
            FeedbackError: When ``missing`` or ``stale`` is set.
        """
        if self.missing:
            raise FeedbackError("missing /joint_states feedback")
        if self.stale:
            raise FeedbackError("stale /tcp_pose_broadcaster/pose feedback")

    def tcp_position(self) -> tuple[float, float, float]:
        """Return the configured TCP position.

        Returns:
            TCP xyz in metres.
        """
        self.require_fresh()
        return self.position

    def joint_positions(self) -> tuple[float, ...]:
        """Return six zero joint angles.

        Returns:
            Joint angles in radians.
        """
        self.require_fresh()
        return self.joints


class FakeBackend:
    """Motion backend fake that records calls and optionally fails or drifts."""

    def __init__(
        self,
        feedback: FakeFeedback | None = None,
        fault: MotionFaultError | None = None,
        z_delta_per_move_m: float | None = None,
        drift_actions: tuple[str, ...] | None = None,
    ) -> None:
        """Configure the fake motion behaviour.

        Args:
            feedback: Feedback fake whose TCP position the fake may move.
            fault: Raised on the first move when set.
            z_delta_per_move_m: Simulated TCP z change per move; negative values
                model a robot that descends further than commanded.
            drift_actions: Actions that apply the z change; all actions when None.
        """
        self.calls: list[tuple[object, ...]] = []
        self.feedback = feedback
        self.fault = fault
        self.z_delta_per_move_m = z_delta_per_move_m
        self.drift_actions = drift_actions

    def move(
        self,
        step: Step,
        duration_s: float,
        timeout_s: float,
        limits: object,
        start_joints: tuple[float, ...],
    ) -> None:
        """Record a move and apply the configured fault or drift.

        Args:
            step: Requested target.
            duration_s: Requested duration.
            timeout_s: Requested deadline margin.
            limits: Workspace and speed limits.
            start_joints: Measured start joints.
        """
        del duration_s, timeout_s, limits, start_joints
        self.calls.append(("move", step.action, step.xyz_m))
        if self.fault is not None:
            raise self.fault
        if (
            self.feedback is not None
            and self.z_delta_per_move_m is not None
            and (self.drift_actions is None or step.action in self.drift_actions)
        ):
            x, y, z = self.feedback.position
            self.feedback.position = (x, y, z + self.z_delta_per_move_m)

    def gripper(self, command: str) -> None:
        """Record a gripper command.

        Args:
            command: Command string sent to the gripper.
        """
        self.calls.append(("gripper", command))

    def stop(self) -> None:
        """Record a stop request."""
        self.calls.append(("stop",))


def make_config(
    max_travel_m: float = 0.002, timeout_s: float = 0.3
) -> dict[str, object]:
    """Build a config that satisfies the planner contract.

    Args:
        max_travel_m: Hard seating travel cap in metres.
        timeout_s: Seating guard timeout in seconds.

    Returns:
        Config mapping with limits, seating, motion and pickup sections.
    """
    return {
        "baseplate": {
            "origin_xyz_m": [0.0, 0.0, 0.0],
            "yaw_deg": 0.0,
            "stud_pitch_m": 0.008,
            "brick_height_m": 0.0096,
        },
        "pickup": {
            "xyz_m": [-0.2, -0.4, 0.02],
            "rpy_deg": [0.0, 180.0, 0.0],
            "gripper_width_mm": 40.0,
        },
        "limits": {
            "workspace_min_m": [-0.6, -0.6, 0.0],
            "workspace_max_m": [0.6, 0.6, 0.4],
            "max_speed_m_s": 0.2,
            "max_speed_scale": 1.0,
        },
        "motion": {
            "hover_m": 0.05,
            "travel_speed_m_s": 0.1,
            "descend_speed_m_s": 0.02,
        },
        "seating": {
            "force_n": 10.0,
            "max_travel_m": max_travel_m,
            "timeout_s": timeout_s,
        },
    }


def make_plan(seat_z_m: float = 0.0104) -> list[dict[str, object]]:
    """Build one canonical ten-step brick plan.

    Args:
        seat_z_m: Nominal target height used by slow_descend, seat and open;
            approach_target is this value plus ``max_travel_m``.

    Returns:
        Ten planner-style step mappings for one brick.
    """
    approach_z = seat_z_m + 0.002
    rpy = [0.0, 180.0, 0.0]
    return [
        {
            "action": "approach",
            "brick_id": "b1",
            "xyz_m": [-0.2, -0.4, 0.05],
            "rpy_deg": rpy,
            "speed_m_s": 0.05,
        },
        {
            "action": "descend",
            "brick_id": "b1",
            "xyz_m": [-0.2, -0.4, 0.02],
            "rpy_deg": rpy,
            "speed_m_s": 0.05,
        },
        {
            "action": "close",
            "brick_id": "b1",
            "xyz_m": [-0.2, -0.4, 0.02],
            "rpy_deg": rpy,
            "speed_m_s": 0.05,
            "gripper_width_mm": 40.0,
        },
        {
            "action": "lift",
            "brick_id": "b1",
            "xyz_m": [-0.2, -0.4, 0.05],
            "rpy_deg": rpy,
            "speed_m_s": 0.05,
        },
        {
            "action": "transfer",
            "brick_id": "b1",
            "xyz_m": [0.0, 0.0, 0.05],
            "rpy_deg": rpy,
            "speed_m_s": 0.05,
        },
        {
            "action": "approach_target",
            "brick_id": "b1",
            "xyz_m": [0.0, 0.0, approach_z],
            "rpy_deg": rpy,
            "speed_m_s": 0.05,
        },
        {
            "action": "slow_descend",
            "brick_id": "b1",
            "xyz_m": [0.0, 0.0, seat_z_m],
            "rpy_deg": rpy,
            "speed_m_s": 0.02,
        },
        {
            "action": "seat",
            "brick_id": "b1",
            "xyz_m": [0.0, 0.0, seat_z_m],
            "rpy_deg": rpy,
            "speed_m_s": 0.02,
        },
        {
            "action": "open",
            "brick_id": "b1",
            "xyz_m": [0.0, 0.0, seat_z_m],
            "rpy_deg": rpy,
            "speed_m_s": 0.05,
            "gripper_width_mm": 40.0,
        },
        {
            "action": "retreat",
            "brick_id": "b1",
            "xyz_m": [0.0, 0.0, 0.05],
            "rpy_deg": rpy,
            "speed_m_s": 0.05,
        },
    ]


def mock_options(tmp_path: Path, **overrides: object) -> ExecutorOptions:
    """Build non-dry-run mock options with a valid hardware proof file.

    Args:
        tmp_path: Directory that receives the proof and step log.
        overrides: Option fields replaced after the defaults.

    Returns:
        Options enabling proven mock execution.
    """
    proof_path = tmp_path / "mock_proof.json"
    proof_path.write_text(json.dumps({"mock_hardware": True}), encoding="utf-8")
    options = ExecutorOptions(
        dry_run=False,
        confirm_each_step=False,
        step_log=str(tmp_path / "steps.jsonl"),
        mock_execution=True,
        mock_hardware_proof=str(proof_path),
    )
    return replace(options, **overrides)


def run_case(
    plan: Sequence[object],
    config: Mapping[str, object],
    options: ExecutorOptions,
    feedback: FakeFeedback | None = None,
    backend: FakeBackend | None = None,
    clock: Callable[[], float] = time.monotonic,
):
    """Run one executor case with fakes and no ROS node.

    Args:
        plan: Planner-style steps.
        config: Config mapping.
        options: Executor options.
        feedback: Injected feedback fake.
        backend: Injected backend fake.
        clock: Monotonic clock fake or ``time.monotonic``.

    Returns:
        The executor result.
    """
    executor = AssemblyExecutor(
        None,
        plan,
        config,
        options,
        feedback=feedback,
        backend=backend,
        confirm=lambda step: True,
        clock=clock,
    )
    return executor.run()


def log_records(path: Path) -> list[dict[str, object]]:
    """Read a step log as parsed JSON records.

    Args:
        path: JSONL step log path.

    Returns:
        One mapping per logged line.
    """
    lines = path.read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines]


def test_dry_run_creates_no_control_endpoint_or_message(tmp_path: Path) -> None:
    """A dry run validates and logs all steps with no node, feedback or backend."""
    log_path = tmp_path / "steps.jsonl"
    options = ExecutorOptions(confirm_each_step=True, step_log=str(log_path))
    result = run_case(make_plan(), make_config(), options)
    assert result.status == "planned"
    assert len(result.records) == 10
    assert all(not record.executed for record in result.records)
    assert all(record.status == "planned" for record in result.records)
    assert all(record.force_mode == "not_started" for record in result.records)
    records = log_records(log_path)
    assert len(records) == 10
    assert all(record["dry_run"] is True for record in records)
    assert all(record["executed"] is False for record in records)
    assert all(record["physical_insertion_validated"] is False for record in records)


def test_missing_feedback_aborts_before_any_command(tmp_path: Path) -> None:
    """Missing joint feedback aborts the run without a backend command."""
    backend = FakeBackend()
    result = run_case(
        make_plan(),
        make_config(),
        mock_options(tmp_path),
        feedback=FakeFeedback(missing=True),
        backend=backend,
    )
    assert result.status == "aborted"
    assert "missing /joint_states" in result.detail
    assert backend.calls == []
    assert result.records == []


def test_stale_feedback_aborts_before_any_command(tmp_path: Path) -> None:
    """Stale TCP feedback aborts the run without a backend command."""
    backend = FakeBackend()
    result = run_case(
        make_plan(),
        make_config(),
        mock_options(tmp_path),
        feedback=FakeFeedback(stale=True),
        backend=backend,
    )
    assert result.status == "aborted"
    assert "stale" in result.detail
    assert backend.calls == []


def test_tcp_pose_frame_must_declare_base() -> None:
    """TCP feedback framed as base_link is rejected instead of reinterpreted."""
    clock = FakeClock()
    feedback = RosFeedback(None, 1.0, clock)
    joints = JointState()
    joints.name = list(JOINT_NAMES)
    joints.position = [0.0] * len(JOINT_NAMES)
    feedback.on_joint_state(joints)
    pose = PoseStamped()
    pose.header.frame_id = "base_link"
    feedback.on_tcp_pose(pose)
    with pytest.raises(FeedbackError, match="base_link"):
        feedback.require_fresh()
    pose.header.frame_id = "base"
    feedback.on_tcp_pose(pose)
    feedback.require_fresh()


def test_travel_timeout_fault_stops_and_aborts(tmp_path: Path) -> None:
    """A motion deadline fault stops once and stops the remaining steps."""
    backend = FakeBackend(fault=MotionFaultError("joint trajectory deadline exceeded"))
    result = run_case(
        make_plan(),
        make_config(),
        mock_options(tmp_path),
        feedback=FakeFeedback(),
        backend=backend,
    )
    assert result.status == "aborted"
    assert "deadline" in result.detail
    assert backend.calls == [("move", "approach", (-0.2, -0.4, 0.05)), ("stop",)]
    assert result.records[-1].status == "aborted"
    assert result.records[-1].executed is True


def test_hard_seat_travel_cap_refuses_before_seat_motion(tmp_path: Path) -> None:
    """A seat descent beyond max_travel_m aborts with no seat move and no allowance."""
    plan = make_plan(seat_z_m=0.0074)
    backend = FakeBackend()
    result = run_case(
        plan,
        make_config(),
        mock_options(tmp_path),
        feedback=FakeFeedback(),
        backend=backend,
    )
    assert result.status == "aborted"
    assert "hard cap" in result.detail
    moves = [call for call in backend.calls if call[0] == "move"]
    assert [call[1] for call in moves] == [
        "approach",
        "descend",
        "lift",
        "transfer",
        "approach_target",
        "slow_descend",
    ]
    assert ("move", "seat", (0.0, 0.0, 0.0074)) not in backend.calls
    assert ("stop",) in backend.calls


def test_seat_overtravel_aborts_and_stops(tmp_path: Path) -> None:
    """Measured descent beyond the hard cap aborts and stops motion."""
    feedback = FakeFeedback()
    backend = FakeBackend(
        feedback=feedback,
        z_delta_per_move_m=-0.0009,
        drift_actions=("seat",),
    )
    result = run_case(
        make_plan(seat_z_m=0.0089),
        make_config(),
        mock_options(tmp_path),
        feedback=feedback,
        backend=backend,
    )
    assert result.status == "aborted"
    assert "overtravel" in result.detail
    assert backend.calls[-1] == ("stop",)


def test_seat_timeout_aborts_and_stops(tmp_path: Path) -> None:
    """Measured descent that outlives seating.timeout_s aborts and stops."""
    feedback = FakeFeedback()
    backend = FakeBackend(feedback=feedback)
    result = run_case(
        make_plan(seat_z_m=0.0089),
        make_config(timeout_s=0.03),
        mock_options(tmp_path),
        feedback=feedback,
        backend=backend,
        clock=FakeClock(step_s=0.02),
    )
    assert result.status == "aborted"
    assert "exceeded timeout" in result.detail
    assert backend.calls[-1] == ("stop",)


def test_physical_seating_is_refused(tmp_path: Path) -> None:
    """Physical mode refuses a plan containing seat before any command."""
    backend = FakeBackend()
    options = ExecutorOptions(
        dry_run=False,
        confirm_each_step=False,
        step_log=str(tmp_path / "steps.jsonl"),
        enable_physical_execution=True,
    )
    with pytest.raises(ExecutionRefusedError, match="hardware seating is blocked"):
        run_case(
            make_plan(),
            make_config(),
            options,
            feedback=FakeFeedback(),
            backend=backend,
        )
    assert backend.calls == []


def test_mock_execution_requires_proof(tmp_path: Path) -> None:
    """Mock execution without a proof file is refused."""
    options = ExecutorOptions(
        dry_run=False,
        confirm_each_step=False,
        step_log=str(tmp_path / "steps.jsonl"),
        mock_execution=True,
    )
    with pytest.raises(ExecutionRefusedError, match="mock_hardware_proof"):
        run_case(
            make_plan(),
            make_config(),
            options,
            feedback=FakeFeedback(),
            backend=FakeBackend(),
        )


def test_vision_pose_source_fails_closed(tmp_path: Path) -> None:
    """Unsupported vision poses are refused rather than replaced silently."""
    options = ExecutorOptions(
        dry_run=False,
        confirm_each_step=False,
        step_log=str(tmp_path / "steps.jsonl"),
        pose_source="vision",
        mock_execution=True,
        mock_hardware_proof=str(tmp_path / "proof.json"),
    )
    (tmp_path / "proof.json").write_text(
        json.dumps({"mock_hardware": True}), encoding="utf-8"
    )
    with pytest.raises(ExecutionRefusedError, match="vision"):
        run_case(
            make_plan(),
            make_config(),
            options,
            feedback=FakeFeedback(),
            backend=FakeBackend(),
        )


def test_speed_scale_above_one_is_rejected() -> None:
    """Planner speeds already include max_speed_scale, so no double scaling."""
    with pytest.raises(PlanValidationError, match="speed_scale"):
        validate_plan(make_plan(), make_config(), speed_scale=2.0)


def test_plan_travel_above_cap_is_rejected() -> None:
    """Planned approach to seating descent above max_travel_m is rejected."""
    plan = make_plan()
    plan[5]["xyz_m"] = [0.0, 0.0, 0.02]
    with pytest.raises(PlanValidationError, match="max_travel_m"):
        validate_plan(plan, make_config())


def test_plan_rejects_workspace_violation_and_wrong_order() -> None:
    """Poses outside the workspace and non-canonical order are rejected."""
    outside = make_plan()
    outside[0]["xyz_m"] = [1.0, -0.4, 0.05]
    with pytest.raises(PlanValidationError, match="outside workspace"):
        validate_plan(outside, make_config())
    shuffled = make_plan()
    shuffled[0], shuffled[1] = shuffled[1], shuffled[0]
    with pytest.raises(PlanValidationError, match="canonical"):
        validate_plan(shuffled, make_config())


def test_mock_run_labels_seating_emulated_and_unvalidated(tmp_path: Path) -> None:
    """A mock run completes, but seating is labelled emulated and unvalidated."""
    feedback = FakeFeedback()
    backend = FakeBackend(feedback=feedback)
    result = run_case(
        make_plan(),
        make_config(),
        mock_options(tmp_path),
        feedback=feedback,
        backend=backend,
    )
    assert result.status == "completed"
    assert "mock rehearsal" in result.detail
    assert "no physical force or contact evidence" in result.detail
    seat_records = [record for record in result.records if record.action == "seat"]
    assert len(seat_records) == 1
    assert seat_records[0].status == "emulated"
    assert seat_records[0].force_mode == "emulated"
    assert "no force applied" in seat_records[0].detail
    records = log_records(tmp_path / "steps.jsonl")
    assert all(record["physical_insertion_validated"] is False for record in records)
    assert all(record["mock_execution"] is True for record in records)
    assert all(record["frame"] == "base" for record in records)


def test_three_brick_planner_output_respects_exact_travel_cap() -> None:
    """Planner and executor agree at the configured cap on every layer."""
    from risl_contact_assembly.planner import (
        load_config,
        load_structure,
        plan_structure,
    )

    package = Path(__file__).resolve().parents[1]
    config = load_config(package / "config/assembly.yaml")
    plan = plan_structure(
        load_structure(package / "fixtures/three_bricks.json"), config
    )
    assert len(validate_plan(plan, config).steps) == 30
    plan[15]["xyz_m"][2] += 1e-10
    with pytest.raises(PlanValidationError, match="exceeds"):
        validate_plan(plan, config)
