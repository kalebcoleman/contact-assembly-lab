"""Turn one straight-line tool move into a joint trajectory.

Kinematics come from ``risl_ur`` (nominal UR5e DH parameters), whose forward
kinematics give ``tool0`` in ``base``. Joint order is shoulder pan, shoulder
lift, elbow, wrist 1, wrist 2, wrist 3; angles are radians.
"""

import numpy as np
from risl_ur.custom_libraries.ik_solver import (
    compute_jacobian,
    dh_params,
    forward_kinematics,
)
from scipy.spatial.transform import Rotation

from risl_contact_assembly.planner import Motion, Move

SAMPLE_PERIOD_S = 0.04
MAX_JOINT_SPEED_RAD_S = 0.5
# UR5e joint range with a margin; the elbow is limited to half a turn.
JOINT_LIMITS_RAD = np.array([6.2, 6.2, 3.1, 6.2, 6.2, 6.2])
IK_DAMPING = 0.01
IK_ITERATIONS = 50
IK_POSITION_TOLERANCE_M = 2e-5
IK_ROTATION_TOLERANCE_RAD = 1e-4


def plan_move(
    start_joints: np.ndarray, move: Move, motion: Motion
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Plan a straight tool line from the current joints to ``move.pose``.

    The tool origin moves along a line and the orientation turns about one
    fixed axis, both following one path fraction ``s(t)`` from 0 to 1. With
    line length ``L``, turn angle ``A``, speed ``v = move.speed_m_s``,
    acceleration ``a`` and rotation speed ``w``::

        cruise_s = max(L / v, A / w)    time at full speed
        ramp_s   = v / a                time to reach full speed

    ``s(t)`` is a trapezoid with those times (a triangle when the move is too
    short to reach full speed), so tool speed never exceeds ``v`` and tool
    acceleration never exceeds ``a``. Each sample is solved by damped
    least-squares steps from the previous sample, which keeps the arm on the
    joint branch it starts on.

    Args:
        start_joints: Six measured joint angles, radians.
        move: Target ``T_base_tool0`` and speed.
        motion: Acceleration and rotation speed limits.

    Returns:
        Sample times from the start of the move (seconds), joint positions
        (radians, one row per sample) and joint velocities (rad/s). All are
        empty when the tool is already at the target.

    Raises:
        ValueError: If a sample cannot be reached, leaves the joint limits, or
            needs a joint speed above ``MAX_JOINT_SPEED_RAD_S``.
    """
    start = forward_kinematics(dh_params, start_joints)
    line = move.pose[:3, 3] - start[:3, 3]
    turn = Rotation.from_matrix(move.pose[:3, :3] @ start[:3, :3].T).as_rotvec()
    cruise_s = max(
        float(np.linalg.norm(line)) / move.speed_m_s,
        float(np.linalg.norm(turn)) / np.radians(motion.rotation_speed_deg_s),
    )
    if cruise_s < SAMPLE_PERIOD_S / 100:
        return np.empty(0), np.empty((0, 6)), np.empty((0, 6))
    ramp_s = min(
        move.speed_m_s / motion.acceleration_m_s2,
        float(np.sqrt(cruise_s * move.speed_m_s / motion.acceleration_m_s2)),
    )
    duration_s = max(cruise_s + ramp_s, 2 * ramp_s)
    peak_rate = 1.0 / (duration_s - ramp_s)
    times = np.linspace(0.0, duration_s, int(np.ceil(duration_s / SAMPLE_PERIOD_S)) + 1)
    fraction = np.where(
        times < ramp_s,
        0.5 * peak_rate * times**2 / ramp_s,
        np.where(
            times <= duration_s - ramp_s,
            peak_rate * (times - ramp_s / 2),
            1.0 - 0.5 * peak_rate * (duration_s - times) ** 2 / ramp_s,
        ),
    )

    joints = np.array(start_joints, dtype=float)
    positions = [joints.copy()]
    for s in fraction[1:]:
        target_position = start[:3, 3] + s * line
        target_rotation = Rotation.from_rotvec(s * turn).as_matrix() @ start[:3, :3]
        for _ in range(IK_ITERATIONS):
            current = forward_kinematics(dh_params, joints)
            error = np.concatenate(
                [
                    target_position - current[:3, 3],
                    Rotation.from_matrix(
                        target_rotation @ current[:3, :3].T
                    ).as_rotvec(),
                ]
            )
            if (
                np.linalg.norm(error[:3]) < IK_POSITION_TOLERANCE_M
                and np.linalg.norm(error[3:]) < IK_ROTATION_TOLERANCE_RAD
            ):
                break
            jacobian = compute_jacobian(joints)
            joints = joints + jacobian.T @ np.linalg.solve(
                jacobian @ jacobian.T + IK_DAMPING**2 * np.eye(6), error
            )
        else:
            raise ValueError(
                f"cannot reach {np.round(target_position, 4).tolist()} m on a "
                "straight line from here: out of reach or near a singularity"
            )
        positions.append(joints.copy())
    positions = np.array(positions)
    if np.any(np.abs(positions) > JOINT_LIMITS_RAD):
        raise ValueError("straight line leaves the joint limits")
    velocities = np.gradient(positions, times, axis=0)
    velocities[-1] = 0.0
    if np.max(np.abs(velocities)) > MAX_JOINT_SPEED_RAD_S:
        raise ValueError(
            f"straight line needs {np.max(np.abs(velocities)):.2f} rad/s at a "
            f"joint (cap {MAX_JOINT_SPEED_RAD_S}); the path passes too close "
            "to a singularity"
        )
    return times[1:], positions[1:], velocities[1:]
