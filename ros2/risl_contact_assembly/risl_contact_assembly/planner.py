"""Known-pose pick-and-place planning for a two-finger brick gripper.

All plan poses are TCP poses in the robot ``base`` frame, SI meters and degrees.
``base`` is not ``base_link``; the two frames differ by a 180-degree rotation
about Z, and this module never emits ``base_link`` poses. A zero TCP offset is
assumed, so the tool point is the configured TCP.

The pickup pose is an absolute TCP pose of the fixture in ``base``. Target
poses come from the brick's stud-grid pose on the 20x20 baseplate composed with
an explicit calibrated brick-to-TCP transform. Simulator stage coordinates
(``baseplate_xy_m``, ``brick_positions_xy_m``) are never treated as ``base``.

Rotation convention: ``rpy_deg`` is extrinsic XYZ, i.e. the rotation matrix is
``Rz(yaw) @ Ry(pitch) @ Rx(roll)``. Brick orientations are yaw-only, so the
calibrated target orientation is ``[roll, pitch, brick_yaw + calibration_yaw]``.

``seating.force_n`` is the commanded force sent to the force-mode controller;
it is not a measured force limit. Seating poses are nominal and physical
insertion is unvalidated and blocked pending contact sensing and force limits.
"""

import json
from math import cos, degrees, isfinite, pi, radians, remainder, sin
from pathlib import Path
from typing import Final, Literal, TypeAlias, TypedDict

import yaml

PlanAction: TypeAlias = Literal[
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
]

PLATE_STUDS: Final = 20
PLATE_HEIGHT_PLATE_UNITS: Final = 1
BRICK_HEIGHT_PLATE_UNITS: Final = 3


class BaseplateConfig(TypedDict):
    """Baseplate pose in ``base``; ``origin_xyz_m`` is the bottom-face centre."""

    origin_xyz_m: list[float]
    yaw_deg: float
    stud_pitch_m: float
    brick_height_m: float


class PickupConfig(TypedDict):
    """Absolute fixture TCP pose and commanded gripper width."""

    xyz_m: list[float]
    rpy_deg: list[float]
    gripper_width_mm: float


class CalibrationConfig(TypedDict):
    """Calibrated brick-to-TCP transform, translation in brick axes."""

    brick_to_tcp_xyz_m: list[float]
    brick_to_tcp_rpy_deg: list[float]


class LimitsConfig(TypedDict):
    """Base-frame workspace AABB and speed caps."""

    workspace_min_m: list[float]
    workspace_max_m: list[float]
    max_speed_m_s: float
    max_speed_scale: float


class MotionConfig(TypedDict):
    """Hover height and configured travel and descent speeds."""

    hover_m: float
    travel_speed_m_s: float
    descend_speed_m_s: float


class SeatingConfig(TypedDict):
    """Force-seating parameters; ``force_n`` is commanded, not measured."""

    force_n: float
    max_travel_m: float
    timeout_s: float


class AssemblyConfig(TypedDict):
    """Validated assembly config with every contract field present."""

    baseplate: BaseplateConfig
    pickup: PickupConfig
    calibration: CalibrationConfig
    limits: LimitsConfig
    motion: MotionConfig
    seating: SeatingConfig


class StructureRequired(TypedDict):
    """Fields every simulator stud-grid structure document must carry."""

    experiment_name: str
    baseplate_xy_m: list[float]
    part_names: list[str]
    brick_dimensions: list[list[int]]
    brick_colors: list[list[int]]
    brick_positions_xy_m: list[list[float]]
    support_bricks: list[int | None]
    placement_offsets: list[list[int]]


class Structure(StructureRequired, total=False):
    """Simulator stud-grid structure document.

    ``placement_offsets`` are stud offsets from the support's footprint corner,
    ``placement_yaws`` are optional quarter turns about +Z relative to the
    support, and ``brick_dimensions`` are ``[x, y, z]`` stud and plate-unit
    counts.
    """

    placement_yaws: list[int]
    min_same_layer_gap_studs: int


class PlanStepRequired(TypedDict):
    """Fields present on every plan step."""

    action: PlanAction
    brick_id: str
    xyz_m: list[float]
    rpy_deg: list[float]
    speed_m_s: float


class PlanStep(PlanStepRequired, total=False):
    """One TCP motion or gripper command in execution order."""

    gripper_width_mm: float


def _mapping(value: object, name: str) -> dict[str, object]:
    """Return a string-keyed mapping for a YAML config value.

    Args:
        value: Parsed YAML value to check.
        name: Field name used in the error message.

    Returns:
        The value as a string-keyed dict.

    Raises:
        ValueError: If the value is not a mapping with string keys.
    """
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ValueError(f"{name} must be a mapping with string keys")
    return {str(key): item for key, item in value.items()}


def _finite_float(value: object, name: str) -> float:
    """Return a finite float from a config value.

    Args:
        value: Parsed YAML value to check.
        name: Field name used in the error message.

    Returns:
        The value as a finite float.

    Raises:
        ValueError: If the value is boolean, non-numeric or non-finite.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite number")
    number = float(value)
    if not isfinite(number):
        raise ValueError(f"{name} must be finite")
    return number


def _vector3(value: object, name: str) -> list[float]:
    """Return a finite three-component vector from a config value.

    Args:
        value: Parsed YAML value to check.
        name: Field name used in the error message.

    Returns:
        Three finite floats.

    Raises:
        ValueError: If the value is not a list of three finite numbers.
    """
    if not isinstance(value, list) or len(value) != 3:
        raise ValueError(f"{name} must be a list of three numbers")
    return [_finite_float(item, f"{name}[{index}]") for index, item in enumerate(value)]


def _rotate_xy(angle_rad: float, x: float, y: float) -> tuple[float, float]:
    """Rotate a vector about +Z.

    Args:
        angle_rad: Counter-clockwise rotation about +Z, radians.
        x: X component, meters.
        y: Y component, meters.

    Returns:
        Rotated ``(x, y)`` components in meters.
    """
    return (
        x * cos(angle_rad) - y * sin(angle_rad),
        x * sin(angle_rad) + y * cos(angle_rad),
    )


def load_config(path: str | Path) -> AssemblyConfig:
    """Load and validate the assembly config YAML.

    Poses are TCP in ``base``, SI meters and degrees; gripper widths are mm.
    The calibrated brick-to-TCP translation is expressed in brick axes from the
    brick's bottom-centre reference. ``seating.force_n`` is a commanded force,
    not a measured limit.

    Args:
        path: YAML config path.

    Returns:
        Validated config with every contract field present.

    Raises:
        ValueError: If the document is not a mapping or a field is missing,
            wrong typed, non-finite or outside its allowed range.
    """
    document = _mapping(
        yaml.safe_load(Path(path).read_text(encoding="utf-8")), "config"
    )

    baseplate = _mapping(document.get("baseplate"), "baseplate")
    stud_pitch_m = _finite_float(
        baseplate.get("stud_pitch_m"), "baseplate.stud_pitch_m"
    )
    brick_height_m = _finite_float(
        baseplate.get("brick_height_m"), "baseplate.brick_height_m"
    )
    if stud_pitch_m <= 0:
        raise ValueError("baseplate.stud_pitch_m must be positive")
    if brick_height_m <= 0:
        raise ValueError("baseplate.brick_height_m must be positive")

    pickup = _mapping(document.get("pickup"), "pickup")
    gripper_width_mm = _finite_float(
        pickup.get("gripper_width_mm"), "pickup.gripper_width_mm"
    )
    if not 0 <= gripper_width_mm <= 110:
        raise ValueError("pickup.gripper_width_mm must be within [0, 110]")

    calibration = _mapping(document.get("calibration"), "calibration")

    limits = _mapping(document.get("limits"), "limits")
    workspace_min_m = _vector3(limits.get("workspace_min_m"), "limits.workspace_min_m")
    workspace_max_m = _vector3(limits.get("workspace_max_m"), "limits.workspace_max_m")
    if any(low >= high for low, high in zip(workspace_min_m, workspace_max_m)):
        raise ValueError("limits.workspace_min_m must be below workspace_max_m")
    max_speed_m_s = _finite_float(limits.get("max_speed_m_s"), "limits.max_speed_m_s")
    if max_speed_m_s <= 0:
        raise ValueError("limits.max_speed_m_s must be positive")
    max_speed_scale = _finite_float(
        limits.get("max_speed_scale"), "limits.max_speed_scale"
    )
    if not 0 < max_speed_scale <= 1:
        raise ValueError("limits.max_speed_scale must be within (0, 1]")

    motion = _mapping(document.get("motion"), "motion")
    hover_m = _finite_float(motion.get("hover_m"), "motion.hover_m")
    travel_speed_m_s = _finite_float(
        motion.get("travel_speed_m_s"), "motion.travel_speed_m_s"
    )
    descend_speed_m_s = _finite_float(
        motion.get("descend_speed_m_s"), "motion.descend_speed_m_s"
    )
    if hover_m <= 0:
        raise ValueError("motion.hover_m must be positive")
    if travel_speed_m_s <= 0:
        raise ValueError("motion.travel_speed_m_s must be positive")
    if descend_speed_m_s <= 0:
        raise ValueError("motion.descend_speed_m_s must be positive")

    seating = _mapping(document.get("seating"), "seating")
    force_n = _finite_float(seating.get("force_n"), "seating.force_n")
    max_travel_m = _finite_float(seating.get("max_travel_m"), "seating.max_travel_m")
    timeout_s = _finite_float(seating.get("timeout_s"), "seating.timeout_s")
    if force_n <= 0:
        raise ValueError("seating.force_n must be positive")
    if max_travel_m < 0:
        raise ValueError("seating.max_travel_m must not be negative")
    if timeout_s <= 0:
        raise ValueError("seating.timeout_s must be positive")

    return {
        "baseplate": {
            "origin_xyz_m": _vector3(
                baseplate.get("origin_xyz_m"), "baseplate.origin_xyz_m"
            ),
            "yaw_deg": _finite_float(baseplate.get("yaw_deg"), "baseplate.yaw_deg"),
            "stud_pitch_m": stud_pitch_m,
            "brick_height_m": brick_height_m,
        },
        "pickup": {
            "xyz_m": _vector3(pickup.get("xyz_m"), "pickup.xyz_m"),
            "rpy_deg": _vector3(pickup.get("rpy_deg"), "pickup.rpy_deg"),
            "gripper_width_mm": gripper_width_mm,
        },
        "calibration": {
            "brick_to_tcp_xyz_m": _vector3(
                calibration.get("brick_to_tcp_xyz_m"),
                "calibration.brick_to_tcp_xyz_m",
            ),
            "brick_to_tcp_rpy_deg": _vector3(
                calibration.get("brick_to_tcp_rpy_deg"),
                "calibration.brick_to_tcp_rpy_deg",
            ),
        },
        "limits": {
            "workspace_min_m": workspace_min_m,
            "workspace_max_m": workspace_max_m,
            "max_speed_m_s": max_speed_m_s,
            "max_speed_scale": max_speed_scale,
        },
        "motion": {
            "hover_m": hover_m,
            "travel_speed_m_s": travel_speed_m_s,
            "descend_speed_m_s": descend_speed_m_s,
        },
        "seating": {
            "force_n": force_n,
            "max_travel_m": max_travel_m,
            "timeout_s": timeout_s,
        },
    }


def load_structure(path: str | Path) -> Structure:
    """Load a simulator stud-grid structure JSON document.

    The schema is the simulator's actual structure document, not the docs
    catalog. ``baseplate_xy_m`` and ``brick_positions_xy_m`` are simulator stage
    coordinates, not ``base``; the config supplies the ``base`` plate pose and
    fixture TCP pose instead. Optional simulator hints such as
    ``grasp_offsets_m`` and ``controller`` are not hardware-validated and are
    ignored by planning.

    Args:
        path: Structure JSON path.

    Returns:
        Parsed structure document; ``plan_structure`` validates its fields.

    Raises:
        ValueError: If the file is not a JSON object.
    """
    document = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ValueError("structure must be a JSON object")
    return document


def plan_structure(structure: Structure, config: AssemblyConfig) -> list[PlanStep]:
    """Plan one ten-step cycle per brick in structure build order.

    Step order is ``approach``, ``descend``, ``close``, ``lift``, ``transfer``,
    ``approach_target``, ``slow_descend``, ``seat``, ``open``, ``retreat``.
    Grasp-side steps use the absolute fixture TCP pose. Target steps compose the
    brick bottom-centre from the native stud-grid formula with the calibrated
    brick-to-TCP transform. ``approach_target`` is ``seating.max_travel_m``
    above the target, ``transfer`` and ``retreat`` are ``motion.hover_m`` above
    it, and ``seat`` is the nominal target itself.

    Speeds are the configured speeds times ``limits.max_speed_scale``. They are
    validated against ``limits.max_speed_m_s`` and never silently clamped.

    Args:
        structure: Structure document, as returned by ``load_structure``.
        config: Assembly config, as returned by ``load_config``.

    Returns:
        Plan steps in execution order.

    Raises:
        ValueError: If the structure is inconsistent, the config or a derived
            pose is outside its limits, or a derived pose is non-finite.
    """
    baseplate = config["baseplate"]
    pickup = config["pickup"]
    calibration = config["calibration"]
    limits = config["limits"]
    motion = config["motion"]
    seating = config["seating"]

    part_names = structure.get("part_names")
    brick_dimensions = structure.get("brick_dimensions")
    support_bricks = structure.get("support_bricks")
    placement_offsets = structure.get("placement_offsets")
    if (
        not isinstance(part_names, list)
        or not isinstance(brick_dimensions, list)
        or not isinstance(support_bricks, list)
        or not isinstance(placement_offsets, list)
        or not part_names
    ):
        raise ValueError(
            "structure must provide non-empty part_names, brick_dimensions, "
            "support_bricks and placement_offsets lists"
        )
    count = len(part_names)
    if (
        len(brick_dimensions) != count
        or len(support_bricks) != count
        or len(placement_offsets) != count
    ):
        raise ValueError("structure list lengths must be equal")

    for index, name in enumerate(part_names):
        if not isinstance(name, str) or not name:
            raise ValueError(f"part_names[{index}] must be a non-empty string")
    if len(set(part_names)) != count:
        raise ValueError("part_names must be unique")

    for index, dimension in enumerate(brick_dimensions):
        if (
            not isinstance(dimension, list)
            or len(dimension) != 3
            or any(type(stud) is not int or stud <= 0 for stud in dimension)
        ):
            raise ValueError(
                f"brick_dimensions[{index}] must be three positive integer stud counts"
            )

    for index, parent in enumerate(support_bricks):
        if parent is not None and (type(parent) is not int or not 0 <= parent < index):
            raise ValueError(
                f"support_bricks[{index}] must be null or an earlier brick index"
            )

    for index, offset in enumerate(placement_offsets):
        if (
            not isinstance(offset, list)
            or len(offset) != 2
            or any(type(stud) is not int for stud in offset)
        ):
            raise ValueError(
                f"placement_offsets[{index}] must be two integer stud offsets"
            )

    placement_yaws = structure.get("placement_yaws", [0] * count)
    if not isinstance(placement_yaws, list) or len(placement_yaws) != count:
        raise ValueError("placement_yaws must hold one value per part")
    for index, yaw in enumerate(placement_yaws):
        if type(yaw) is not int or not 0 <= yaw <= 3:
            raise ValueError(
                f"placement_yaws[{index}] must be an integer quarter turn in 0..3"
            )

    stud_pitch_m = baseplate["stud_pitch_m"]
    plate_unit_m = baseplate["brick_height_m"] / BRICK_HEIGHT_PLATE_UNITS
    plate_origin = baseplate["origin_xyz_m"]
    plate_yaw = radians(baseplate["yaw_deg"])
    position: list[tuple[float, float, float]] = []
    yaw: list[float] = []
    for index in range(count):
        parent = support_bricks[index]
        dimension = brick_dimensions[index]
        offset = placement_offsets[index]
        local_yaw = placement_yaws[index] * pi / 2
        if parent is None:
            parent_position = (plate_origin[0], plate_origin[1], plate_origin[2])
            parent_yaw = plate_yaw
            parent_size = (PLATE_STUDS, PLATE_STUDS)
            parent_height_m = PLATE_HEIGHT_PLATE_UNITS * plate_unit_m
        else:
            parent_position = position[parent]
            parent_yaw = yaw[parent]
            parent_size = (brick_dimensions[parent][0], brick_dimensions[parent][1])
            parent_height_m = brick_dimensions[parent][2] * plate_unit_m
        half_shift = _rotate_xy(
            local_yaw,
            dimension[0] * stud_pitch_m / 2,
            dimension[1] * stud_pitch_m / 2,
        )
        parent_shift = _rotate_xy(
            parent_yaw,
            (offset[0] - parent_size[0] / 2) * stud_pitch_m + half_shift[0],
            (offset[1] - parent_size[1] / 2) * stud_pitch_m + half_shift[1],
        )
        position.append(
            (
                parent_position[0] + parent_shift[0],
                parent_position[1] + parent_shift[1],
                parent_position[2] + parent_height_m,
            )
        )
        yaw.append(parent_yaw + local_yaw)

    speed_scale = limits["max_speed_scale"]
    travel_speed_m_s = motion["travel_speed_m_s"] * speed_scale
    descend_speed_m_s = motion["descend_speed_m_s"] * speed_scale
    if max(travel_speed_m_s, descend_speed_m_s) > limits["max_speed_m_s"]:
        raise ValueError(
            "scaled motion speeds exceed limits.max_speed_m_s; lower the "
            "configured speeds or the speed scale"
        )

    hover_m = motion["hover_m"]
    seat_gap_m = seating["max_travel_m"]
    pickup_xyz = pickup["xyz_m"]
    pickup_rpy = pickup["rpy_deg"]
    calibration_xyz = calibration["brick_to_tcp_xyz_m"]
    calibration_rpy = calibration["brick_to_tcp_rpy_deg"]
    workspace_min_m = limits["workspace_min_m"]
    workspace_max_m = limits["workspace_max_m"]
    steps: list[PlanStep] = []
    for index, brick_id in enumerate(part_names):
        target_shift = _rotate_xy(yaw[index], calibration_xyz[0], calibration_xyz[1])
        target_xyz = (
            position[index][0] + target_shift[0],
            position[index][1] + target_shift[1],
            position[index][2] + calibration_xyz[2],
        )
        target_rpy = [
            calibration_rpy[0],
            calibration_rpy[1],
            remainder(degrees(yaw[index]) + calibration_rpy[2], 360.0),
        ]
        brick_steps: list[
            tuple[
                PlanAction,
                tuple[float, float, float],
                list[float],
                float,
                float | None,
            ]
        ] = [
            (
                "approach",
                (pickup_xyz[0], pickup_xyz[1], pickup_xyz[2] + hover_m),
                pickup_rpy,
                travel_speed_m_s,
                None,
            ),
            (
                "descend",
                (pickup_xyz[0], pickup_xyz[1], pickup_xyz[2]),
                pickup_rpy,
                descend_speed_m_s,
                None,
            ),
            (
                "close",
                (pickup_xyz[0], pickup_xyz[1], pickup_xyz[2]),
                pickup_rpy,
                descend_speed_m_s,
                pickup["gripper_width_mm"],
            ),
            (
                "lift",
                (pickup_xyz[0], pickup_xyz[1], pickup_xyz[2] + hover_m),
                pickup_rpy,
                descend_speed_m_s,
                None,
            ),
            (
                "transfer",
                (target_xyz[0], target_xyz[1], target_xyz[2] + hover_m),
                target_rpy,
                travel_speed_m_s,
                None,
            ),
            (
                "approach_target",
                (target_xyz[0], target_xyz[1], target_xyz[2] + seat_gap_m),
                target_rpy,
                descend_speed_m_s,
                None,
            ),
            ("slow_descend", target_xyz, target_rpy, descend_speed_m_s, None),
            ("seat", target_xyz, target_rpy, descend_speed_m_s, None),
            ("open", target_xyz, target_rpy, descend_speed_m_s, None),
            (
                "retreat",
                (target_xyz[0], target_xyz[1], target_xyz[2] + hover_m),
                target_rpy,
                descend_speed_m_s,
                None,
            ),
        ]
        for action, xyz_m, rpy_deg, speed_m_s, gripper_width_mm in brick_steps:
            if not all(isfinite(value) for value in (*xyz_m, *rpy_deg, speed_m_s)):
                raise ValueError(f"{action} pose for {brick_id} is not finite")
            if speed_m_s <= 0:
                raise ValueError(f"{action} speed for {brick_id} must be positive")
            if not all(
                workspace_min_m[axis] <= xyz_m[axis] <= workspace_max_m[axis]
                for axis in range(3)
            ):
                raise ValueError(
                    f"{action} pose for {brick_id} is outside the workspace bounds"
                )
            step: PlanStep = {
                "action": action,
                "brick_id": brick_id,
                "xyz_m": [xyz_m[0], xyz_m[1], xyz_m[2]],
                "rpy_deg": [rpy_deg[0], rpy_deg[1], rpy_deg[2]],
                "speed_m_s": speed_m_s,
            }
            if gripper_width_mm is not None:
                step["gripper_width_mm"] = gripper_width_mm
            steps.append(step)
    return steps
