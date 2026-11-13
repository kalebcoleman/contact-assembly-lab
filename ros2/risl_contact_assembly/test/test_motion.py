"""Tests for straight-line joint trajectories."""

import numpy as np
import pytest
from risl_contact_assembly import motion
from risl_contact_assembly.motion import plan_move
from risl_contact_assembly.planner import Motion, Move
from risl_ur.custom_libraries.ik_solver import dh_params, forward_kinematics
from scipy.spatial.transform import Rotation

START_JOINTS = np.radians([90.0, -80.0, 90.0, -100.0, -90.0, 0.0])
MOTION = Motion(
    travel_clearance_m=0.10,
    travel_speed_m_s=0.05,
    contact_speed_m_s=0.005,
    contact_zone_m=0.015,
    acceleration_m_s2=0.10,
    rotation_speed_deg_s=15.0,
)


def offset_pose(xyz_m: list[float], yaw_deg: float = 0.0) -> np.ndarray:
    """Return the start tool pose shifted and yawed about base Z.

    Args:
        xyz_m: Shift of the tool origin in ``base``, metres.
        yaw_deg: Rotation about base Z, degrees.

    Returns:
        4x4 ``T_base_tool0``.
    """
    pose = forward_kinematics(dh_params, START_JOINTS)
    pose[:3, 3] += xyz_m
    pose[:3, :3] = (
        Rotation.from_euler("z", yaw_deg, degrees=True).as_matrix() @ pose[:3, :3]
    )
    return pose


def tool_path(positions: np.ndarray) -> np.ndarray:
    """Return the tool origin of every trajectory sample, starting at the start.

    Args:
        positions: Joint samples, radians.

    Returns:
        One ``base`` position per row, metres.
    """
    return np.array(
        [
            forward_kinematics(dh_params, joints)[:3, 3]
            for joints in [START_JOINTS, *positions]
        ]
    )


def test_move_is_a_straight_line_within_speed_and_acceleration() -> None:
    """A long move stays on its line and inside both Cartesian caps."""
    target = offset_pose([-0.25, 0.10, -0.12])
    times, positions, velocities = plan_move(START_JOINTS, Move(target, 0.05), MOTION)
    path = tool_path(positions)
    start = path[0]
    direction = (target[:3, 3] - start) / np.linalg.norm(target[:3, 3] - start)
    along = (path - start) @ direction
    assert (
        np.linalg.norm(path - start - np.outer(along, direction), axis=1).max() < 5e-5
    )
    stamps = np.concatenate([[0.0], times])
    speed = np.diff(along) / np.diff(stamps)
    assert speed.max() == pytest.approx(0.05, rel=1e-3)
    assert np.abs(np.diff(speed) / np.diff(stamps)[1:]).max() <= 0.10 * 1.01
    assert path[-1] == pytest.approx(target[:3, 3], abs=5e-5)
    assert velocities[-1] == pytest.approx(np.zeros(6))
    assert np.abs(velocities).max() < motion.MAX_JOINT_SPEED_RAD_S
    # 0.3 m at 0.05 m/s plus one 0.5 s ramp.
    assert times[-1] == pytest.approx(
        np.linalg.norm(target[:3, 3] - start) / 0.05 + 0.5
    )


def test_short_move_never_reaches_full_speed() -> None:
    """A 2 mm move uses a triangular profile below the speed cap."""
    target = offset_pose([0.0, 0.0, -0.002])
    times, positions, _ = plan_move(START_JOINTS, Move(target, 0.05), MOTION)
    path = tool_path(positions)
    speed = np.linalg.norm(np.diff(path, axis=0), axis=1) / np.diff(
        np.concatenate([[0.0], times])
    )
    assert speed.max() < 0.02
    assert times[-1] == pytest.approx(2 * np.sqrt(0.002 / 0.10))
    assert path[-1] == pytest.approx(target[:3, 3], abs=5e-5)


def test_turn_in_place_is_limited_by_rotation_speed() -> None:
    """A 90 degree yaw at 15 deg/s takes six seconds plus the ramp."""
    target = offset_pose([0.0, 0.0, 0.0], yaw_deg=90.0)
    times, positions, _ = plan_move(START_JOINTS, Move(target, 0.05), MOTION)
    assert times[-1] == pytest.approx(6.5)
    reached = forward_kinematics(dh_params, positions[-1])
    assert reached[:3, :3] == pytest.approx(target[:3, :3], abs=1e-3)
    assert np.linalg.norm(tool_path(positions) - reached[:3, 3], axis=1).max() < 5e-5


def test_no_trajectory_when_already_at_the_target() -> None:
    """A zero-length move returns no samples."""
    times, positions, velocities = plan_move(
        START_JOINTS, Move(offset_pose([0.0, 0.0, 0.0]), 0.05), MOTION
    )
    assert len(times) == len(positions) == len(velocities) == 0


def test_unreachable_target_is_rejected() -> None:
    """A target beyond the arm's reach raises instead of returning a path."""
    with pytest.raises(ValueError, match="cannot reach|joint|singularity"):
        plan_move(START_JOINTS, Move(offset_pose([0.0, -1.0, 0.0]), 0.05), MOTION)


def test_fast_joint_motion_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    """A path needing more than the joint speed cap raises."""
    monkeypatch.setattr(motion, "MAX_JOINT_SPEED_RAD_S", 0.05)
    with pytest.raises(ValueError, match="rad/s"):
        plan_move(START_JOINTS, Move(offset_pose([-0.25, 0.10, -0.12]), 0.05), MOTION)
