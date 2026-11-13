"""Plan a known-position brick assembly from taught tool poses.

Conventions used throughout the package:

- Frame: every pose is ``tool0`` (the UR flange) in the UR controller ``base``
  frame. ``base`` is ``base_link`` rotated pi about Z; ``base_link`` is never used.
- Units: metres, seconds and newtons. YAML angles are degrees and gripper widths
  are millimetres.
- Poses in code are 4x4 homogeneous transforms ``T_base_tool0`` (NumPy arrays,
  column-vector convention ``p_base = T @ p_tool``).
- ``rpy_deg`` is extrinsic XYZ, ``R = Rz(yaw) @ Ry(pitch) @ Rx(roll)``, the
  SciPy ``"xyz"`` convention also used by ``risl_ur``.

Poses are taught with the brick in the gripper, so no TCP offset or
brick-to-tool calibration enters the plan.
"""

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import yaml
from scipy.spatial.transform import Rotation

STUD_PITCH_M = 0.008
BRICK_HEIGHT_M = 0.0096
BRICK_HEIGHT_PLATES = 3
# A brick is this much narrower than its stud count times the stud pitch.
BRICK_SIDE_GAP_MM = 0.2
# The plate corners are taught with a 2x4 brick, long side along plate +X.
REFERENCE_BRICK_STUDS = (4, 2)
# The grasp command closes this far past the brick so the fingers clamp it.
GRASP_SQUEEZE_MM = 4.0
GRIPPER_MAX_WIDTH_MM = 110.0

# Hard caps. A positions file may ask for less, never for more.
MAX_TRAVEL_SPEED_M_S = 0.05
MAX_CONTACT_SPEED_M_S = 0.01
MAX_ACCELERATION_M_S2 = 0.25
MAX_ROTATION_SPEED_DEG_S = 30.0
MAX_TILT_DEG = 15.0
MAX_PRESS_FORCE_N = 40.0
MAX_PRESS_OVERTRAVEL_M = 0.002
MAX_WIDTH_OFFSET_MM = 5.0

# Accepted disagreement between the taught plate corners and the stud grid.
CORNER_DISTANCE_TOLERANCE_M = 0.0015
CORNER_ANGLE_TOLERANCE_DEG = 1.0
PLATE_LEVEL_TOLERANCE_DEG = 2.0


@dataclass(frozen=True)
class Motion:
    """Speeds and heights of the pick-and-place path.

    Sideways moves happen ``travel_clearance_m`` above the highest pick or
    place pose. ``contact_speed_m_s`` applies within ``contact_zone_m`` above
    every pick and place pose.
    """

    travel_clearance_m: float
    travel_speed_m_s: float
    contact_speed_m_s: float
    contact_zone_m: float
    acceleration_m_s2: float
    rotation_speed_deg_s: float


@dataclass(frozen=True)
class Safety:
    """Workspace box for the ``tool0`` origin in ``base`` and contact limits.

    ``press_force_n`` is the change in measured tool force that stops a place
    and aborts a pick. ``press_overtravel_m`` is how far below the taught seat
    height a place may push.
    """

    workspace_min_m: np.ndarray
    workspace_max_m: np.ndarray
    max_tilt_deg: float
    press_force_n: float
    press_overtravel_m: float


@dataclass(frozen=True)
class Gripper:
    """Gripper opening and width check, millimetres.

    The fingers open ``clearance_mm`` beyond each side of a brick.
    ``width_tolerance_mm`` is the accepted error of the reported width.
    ``width_offset_mm`` is the width the gripper reports minus the true width;
    it is added to every commanded and expected width.
    """

    clearance_mm: float
    width_tolerance_mm: float
    width_offset_mm: float


@dataclass(frozen=True)
class Positions:
    """One cell setup: taught plate corners, taught pickups and limits.

    ``origin``, ``x_corner`` and ``y_corner`` are tool poses gripping the
    reference brick seated at plate stud ``[0, 0]``, ``[x_corner_studs, 0]``
    and ``[0, y_corner_studs]``. ``pickups`` maps each brick name to the tool
    pose gripping it where it waits.
    """

    origin: np.ndarray
    x_corner: np.ndarray
    y_corner: np.ndarray
    x_corner_studs: int
    y_corner_studs: int
    pickups: dict[str, np.ndarray]
    motion: Motion
    safety: Safety
    gripper: Gripper


@dataclass(frozen=True)
class Move:
    """One straight-line tool move ending at rest.

    ``contact`` is ``"free"``, ``"guard"`` (abort on contact force) or
    ``"seat"`` (stop on contact force and carry on).
    """

    pose: np.ndarray
    speed_m_s: float
    contact: str = "free"


@dataclass(frozen=True)
class Step:
    """One operator-confirmed action: tool moves or a gripper command.

    ``gripper_mm`` is the commanded opening. ``expected_mm`` is the width the
    gripper must report: after the command when there is one, otherwise before
    the moves start.
    """

    label: str
    moves: tuple[Move, ...] = ()
    gripper_mm: float | None = None
    expected_mm: float | None = None


@dataclass(frozen=True)
class Plan:
    """Steps in execution order and the ``base`` Z of all sideways motion."""

    steps: list[Step]
    travel_z_m: float


def pose_matrix(entry: dict[str, list[float]]) -> np.ndarray:
    """Convert a YAML pose entry to a transform.

    Args:
        entry: Mapping with ``xyz_m`` (metres) and ``rpy_deg`` (extrinsic XYZ).

    Returns:
        4x4 ``T_base_tool0``.
    """
    pose = np.eye(4)
    pose[:3, :3] = Rotation.from_euler(
        "xyz", entry["rpy_deg"], degrees=True
    ).as_matrix()
    pose[:3, 3] = entry["xyz_m"]
    return pose


def load_positions(path: str | Path) -> Positions:
    """Load and validate a positions YAML.

    Args:
        path: Positions file; see ``config/demo_positions.yaml``.

    Returns:
        Validated positions.

    Raises:
        ValueError: If a limit exceeds its hard cap or the taught plate
            corners disagree with the stud grid.
    """
    document = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    plate = document["baseplate"]
    safety = document["safety"]
    positions = Positions(
        origin=pose_matrix(plate["origin"]),
        x_corner=pose_matrix(plate["x_corner"]),
        y_corner=pose_matrix(plate["y_corner"]),
        x_corner_studs=plate["x_corner_studs"],
        y_corner_studs=plate["y_corner_studs"],
        pickups={
            name: pose_matrix(entry) for name, entry in document["pickups"].items()
        },
        motion=Motion(**document["motion"]),
        safety=Safety(
            workspace_min_m=np.array(safety["workspace_min_m"], dtype=float),
            workspace_max_m=np.array(safety["workspace_max_m"], dtype=float),
            max_tilt_deg=safety["max_tilt_deg"],
            press_force_n=safety["press_force_n"],
            press_overtravel_m=safety["press_overtravel_m"],
        ),
        gripper=Gripper(**document["gripper"]),
    )
    motion = positions.motion
    for name, value, cap in (
        ("motion.travel_clearance_m", motion.travel_clearance_m, 1.0),
        ("motion.travel_speed_m_s", motion.travel_speed_m_s, MAX_TRAVEL_SPEED_M_S),
        ("motion.contact_speed_m_s", motion.contact_speed_m_s, MAX_CONTACT_SPEED_M_S),
        ("motion.contact_zone_m", motion.contact_zone_m, motion.travel_clearance_m),
        ("motion.acceleration_m_s2", motion.acceleration_m_s2, MAX_ACCELERATION_M_S2),
        (
            "motion.rotation_speed_deg_s",
            motion.rotation_speed_deg_s,
            MAX_ROTATION_SPEED_DEG_S,
        ),
        ("safety.max_tilt_deg", positions.safety.max_tilt_deg, MAX_TILT_DEG),
        ("safety.press_force_n", positions.safety.press_force_n, MAX_PRESS_FORCE_N),
        ("gripper.clearance_mm", positions.gripper.clearance_mm, GRIPPER_MAX_WIDTH_MM),
        (
            "gripper.width_tolerance_mm",
            positions.gripper.width_tolerance_mm,
            GRASP_SQUEEZE_MM / 2,
        ),
    ):
        if not 0 < value <= cap:
            raise ValueError(f"{name} = {value} must be in (0, {cap}]")
    if not abs(positions.gripper.width_offset_mm) <= MAX_WIDTH_OFFSET_MM:
        raise ValueError(
            f"gripper.width_offset_mm must be within {MAX_WIDTH_OFFSET_MM} mm of zero"
        )
    if not 0 <= positions.safety.press_overtravel_m <= MAX_PRESS_OVERTRAVEL_M:
        raise ValueError(
            f"safety.press_overtravel_m must be in [0, {MAX_PRESS_OVERTRAVEL_M}]"
        )
    if not np.all(positions.safety.workspace_min_m < positions.safety.workspace_max_m):
        raise ValueError("safety.workspace_min_m must be below workspace_max_m")

    # The taught corners must reproduce the stud grid they were seated on.
    x_edge = positions.x_corner[:3, 3] - positions.origin[:3, 3]
    y_edge = positions.y_corner[:3, 3] - positions.origin[:3, 3]
    for name, edge, studs in (
        ("x_corner", x_edge, positions.x_corner_studs),
        ("y_corner", y_edge, positions.y_corner_studs),
    ):
        error_m = abs(float(np.linalg.norm(edge)) - studs * STUD_PITCH_M)
        if error_m > CORNER_DISTANCE_TOLERANCE_M:
            raise ValueError(
                f"baseplate.{name} is {np.linalg.norm(edge) * 1000:.2f} mm from "
                f"origin, expected {studs * STUD_PITCH_M * 1000:.1f} mm for "
                f"{studs} studs; re-record the corners"
            )
    normal = np.cross(x_edge, y_edge)
    normal /= np.linalg.norm(normal)
    skew_deg = abs(
        90.0
        - np.degrees(
            np.arccos(
                x_edge @ y_edge / (np.linalg.norm(x_edge) * np.linalg.norm(y_edge))
            )
        )
    )
    if skew_deg > CORNER_ANGLE_TOLERANCE_DEG:
        raise ValueError(f"baseplate corners are {skew_deg:.2f} deg off square")
    if np.degrees(np.arccos(min(normal[2], 1.0))) > PLATE_LEVEL_TOLERANCE_DEG:
        raise ValueError(
            "baseplate +X cross +Y must point up in base: the corners are "
            "mirrored or the plate is not level"
        )
    for name, corner in (
        ("x_corner", positions.x_corner),
        ("y_corner", positions.y_corner),
    ):
        twist_deg = np.degrees(
            Rotation.from_matrix(
                positions.origin[:3, :3].T @ corner[:3, :3]
            ).magnitude()
        )
        if twist_deg > CORNER_ANGLE_TOLERANCE_DEG:
            raise ValueError(
                f"baseplate.{name} tool orientation differs from origin by "
                f"{twist_deg:.2f} deg; seat the reference brick the same way"
            )
    return positions


def load_structure(path: str | Path) -> dict[str, list]:
    """Load and validate a simulator structure JSON.

    Only ``part_names``, ``brick_dimensions`` (``[x, y]`` studs and height in
    plates), ``support_bricks``, ``placement_offsets`` (studs) and optional
    ``placement_yaws`` (quarter turns) are used. The simulator stage
    coordinates in the file are ignored.

    Args:
        path: Structure file, for example ``experiments/ur5e_structures/*.json``.

    Returns:
        The structure document with ``placement_yaws`` filled in.

    Raises:
        ValueError: If the build description is inconsistent.
    """
    structure = json.loads(Path(path).read_text(encoding="utf-8"))
    names = structure["part_names"]
    structure.setdefault("placement_yaws", [0] * len(names))
    if len(set(names)) != len(names):
        raise ValueError("part_names must be unique")
    for key in (
        "brick_dimensions",
        "support_bricks",
        "placement_offsets",
        "placement_yaws",
    ):
        if len(structure[key]) != len(names):
            raise ValueError(f"{key} must have one entry per part")
    for index, name in enumerate(names):
        length, width, height = structure["brick_dimensions"][index]
        support = structure["support_bricks"][index]
        if min(length, width) < 1 or height != BRICK_HEIGHT_PLATES:
            raise ValueError(f"{name}: only bricks {BRICK_HEIGHT_PLATES} plates tall")
        if support is not None and not 0 <= support < index:
            raise ValueError(f"{name}: support must be an earlier brick or null")
        if structure["placement_yaws"][index] not in (0, 1, 2, 3):
            raise ValueError(f"{name}: placement yaw must be a quarter turn 0..3")
    return structure


def place_poses(structure: dict[str, list], positions: Positions) -> list[np.ndarray]:
    """Compute the tool pose that seats each brick, in build order.

    Brick centres follow the simulator stud-grid rule, in studs from the plate
    origin corner, with ``R(k)`` a rotation by ``k`` quarter turns about +Z::

        centre = support_corner + R(support_yaw) @ (offset + R(yaw) @ size / 2)

    The plate is a support with its corner at the origin and yaw 0. The tool
    position is interpolated between the taught corners, which absorbs the
    plate position, yaw and tilt::

        p = p_origin + (p_x - p_origin) * dx / x_corner_studs
                     + (p_y - p_origin) * dy / y_corner_studs + normal * height

    with ``(dx, dy)`` the brick centre minus the reference brick centre. The
    fingers always span the short side of a brick, so the tool is the origin
    orientation turned a quarter about the plate normal when the short side
    lies along plate +X.

    Args:
        structure: Document from ``load_structure``.
        positions: Taught poses from ``load_positions``.

    Returns:
        One 4x4 ``T_base_tool0`` per brick.
    """
    quarter_turns = (
        np.array([[1, 0], [0, 1]]),
        np.array([[0, -1], [1, 0]]),
        np.array([[-1, 0], [0, -1]]),
        np.array([[0, 1], [-1, 0]]),
    )
    origin = positions.origin[:3, 3]
    x_step = (positions.x_corner[:3, 3] - origin) / positions.x_corner_studs
    y_step = (positions.y_corner[:3, 3] - origin) / positions.y_corner_studs
    normal = np.cross(x_step, y_step)
    normal /= np.linalg.norm(normal)
    quarter_about_normal = Rotation.from_rotvec(normal * np.pi / 2).as_matrix()

    centres: list[np.ndarray] = []
    yaws: list[int] = []
    layers: list[int] = []
    poses: list[np.ndarray] = []
    for index, size in enumerate(structure["brick_dimensions"]):
        support = structure["support_bricks"][index]
        if support is None:
            support_corner = np.zeros(2)
            support_yaw = 0
            layer = 0
        else:
            support_yaw = yaws[support]
            support_corner = (
                centres[support]
                - quarter_turns[support_yaw]
                @ np.array(structure["brick_dimensions"][support][:2])
                / 2
            )
            layer = layers[support] + 1
        yaw = structure["placement_yaws"][index]
        centre = support_corner + quarter_turns[support_yaw] @ (
            np.array(structure["placement_offsets"][index])
            + quarter_turns[yaw] @ np.array(size[:2]) / 2
        )
        centres.append(centre)
        yaws.append((support_yaw + yaw) % 4)
        layers.append(layer)

        shift = centre - np.array(REFERENCE_BRICK_STUDS) / 2
        pose = np.eye(4)
        pose[:3, 3] = (
            origin
            + x_step * shift[0]
            + y_step * shift[1]
            + normal * layer * BRICK_HEIGHT_M
        )
        long_side_along_x = (size[0] > size[1]) == (yaws[index] % 2 == 0)
        pose[:3, :3] = positions.origin[:3, :3]
        if size[0] != size[1] and not long_side_along_x:
            pose[:3, :3] = quarter_about_normal @ positions.origin[:3, :3]
        poses.append(pose)
    return poses


def plan_assembly(structure: dict[str, list], positions: Positions) -> Plan:
    """Plan the pick and place of every brick, in build order.

    Every sideways move happens at one travel height; every approach and
    retreat is a vertical line in ``base``. The last ``contact_zone_m`` above
    each pick and place runs at the contact speed.

    Args:
        structure: Document from ``load_structure``.
        positions: Taught poses and limits from ``load_positions``.

    Returns:
        Nine steps per brick and the travel height.

    Raises:
        ValueError: If any target leaves the workspace box or tilts the tool
            beyond ``safety.max_tilt_deg``.
    """
    motion = positions.motion
    picks = [positions.pickups[name] for name in structure["part_names"]]
    places = place_poses(structure, positions)
    travel_z_m = max(pose[2, 3] for pose in picks + places) + motion.travel_clearance_m
    steps: list[Step] = []
    for name, size, pick, place in zip(
        structure["part_names"], structure["brick_dimensions"], picks, places
    ):
        grasp_mm = (
            min(size[:2]) * STUD_PITCH_M * 1000
            - BRICK_SIDE_GAP_MM
            + positions.gripper.width_offset_mm
        )
        open_mm = grasp_mm + 2 * positions.gripper.clearance_mm
        if open_mm > GRIPPER_MAX_WIDTH_MM:
            raise ValueError(f"{name}: opening {open_mm:.1f} mm exceeds the gripper")
        above_pick, near_pick, above_place, near_place, seat = (
            pick.copy(),
            pick.copy(),
            place.copy(),
            place.copy(),
            place.copy(),
        )
        above_pick[2, 3] = above_place[2, 3] = travel_z_m
        near_pick[2, 3] += motion.contact_zone_m
        near_place[2, 3] += motion.contact_zone_m
        seat[2, 3] -= positions.safety.press_overtravel_m
        travel, contact = motion.travel_speed_m_s, motion.contact_speed_m_s
        steps += [
            Step(f"{name}: open gripper", gripper_mm=open_mm, expected_mm=open_mm),
            Step(f"{name}: move above pick", moves=(Move(above_pick, travel),)),
            Step(
                f"{name}: descend to pick",
                moves=(Move(near_pick, travel), Move(pick, contact, "guard")),
            ),
            Step(
                f"{name}: grasp",
                gripper_mm=grasp_mm - GRASP_SQUEEZE_MM,
                expected_mm=grasp_mm,
            ),
            Step(
                f"{name}: lift",
                moves=(Move(near_pick, contact), Move(above_pick, travel)),
            ),
            Step(
                f"{name}: move above place",
                moves=(Move(above_place, travel),),
                expected_mm=grasp_mm,
            ),
            Step(
                f"{name}: descend and seat",
                moves=(Move(near_place, travel), Move(seat, contact, "seat")),
                expected_mm=grasp_mm,
            ),
            Step(f"{name}: release", gripper_mm=open_mm, expected_mm=open_mm),
            Step(
                f"{name}: retreat",
                moves=(Move(near_place, contact), Move(above_place, travel)),
            ),
        ]
    for step in steps:
        for move in step.moves:
            position = move.pose[:3, 3]
            if np.any(position < positions.safety.workspace_min_m) or np.any(
                position > positions.safety.workspace_max_m
            ):
                raise ValueError(
                    f"{step.label}: target {np.round(position, 4).tolist()} m is "
                    "outside the workspace box"
                )
            tilt_deg = np.degrees(np.arccos(np.clip(-move.pose[2, 2], -1.0, 1.0)))
            if tilt_deg > positions.safety.max_tilt_deg:
                raise ValueError(
                    f"{step.label}: tool tilted {tilt_deg:.1f} deg from straight down"
                )
    return Plan(steps, travel_z_m)
