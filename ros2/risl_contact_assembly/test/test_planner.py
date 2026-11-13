"""Tests for positions loading, stud-grid targets and the step plan."""

import json
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest
import yaml
from risl_contact_assembly.planner import (
    BRICK_HEIGHT_M,
    STUD_PITCH_M,
    Positions,
    load_positions,
    load_structure,
    place_poses,
    plan_assembly,
)
from scipy.spatial.transform import Rotation

PACKAGE = Path(__file__).resolve().parents[1]
POSITIONS_FILE = PACKAGE / "config" / "demo_positions.yaml"
SIMULATOR_STRUCTURES = sorted(
    path
    for path in (PACKAGE.parents[1] / "experiments" / "ur5e_structures").glob("*.json")
    if path.name != "trials.json"
)


def write_structure(directory: Path, **fields: list) -> Path:
    """Write a structure file with one entry per brick.

    Args:
        directory: Directory for the file.
        **fields: Structure keys overriding a single 2x4 brick at stud [0, 0].

    Returns:
        Path of the written file.
    """
    structure = {
        "part_names": ["tower_0"],
        "brick_dimensions": [[4, 2, 3]],
        "support_bricks": [None],
        "placement_offsets": [[0, 0]],
    } | fields
    path = directory / "structure.json"
    path.write_text(json.dumps(structure), encoding="utf-8")
    return path


def edited_positions(directory: Path, section: str, key: str, value: object) -> Path:
    """Copy the demo positions file with one value replaced.

    Args:
        directory: Directory for the copy.
        section: Top-level YAML key.
        key: Key inside the section.
        value: Replacement value.

    Returns:
        Path of the copy.
    """
    document = yaml.safe_load(POSITIONS_FILE.read_text(encoding="utf-8"))
    document[section][key] = value
    path = directory / "positions.yaml"
    path.write_text(yaml.safe_dump(document), encoding="utf-8")
    return path


def rotated_plate(positions: Positions) -> Positions:
    """Return positions whose plate is yawed 37 degrees and tilted 1 degree.

    Args:
        positions: Demo positions.

    Returns:
        Positions with all three taught corners moved rigidly about the origin.
    """
    turn = Rotation.from_euler("xyz", [1.0, 0.0, 37.0], degrees=True).as_matrix()
    corners = {}
    for name in ("x_corner", "y_corner"):
        corner = getattr(positions, name).copy()
        corner[:3, 3] = positions.origin[:3, 3] + turn @ (
            corner[:3, 3] - positions.origin[:3, 3]
        )
        corners[name] = corner
    return replace(positions, **corners)


def test_demo_files_plan_nine_steps_per_brick() -> None:
    """The shipped example plans the three-brick tower inside its limits."""
    positions = load_positions(POSITIONS_FILE)
    plan = plan_assembly(
        load_structure(PACKAGE / "structures" / "three_bricks.json"), positions
    )
    assert len(plan.steps) == 27
    assert [step.label for step in plan.steps[:9]] == [
        "tower_0: open gripper",
        "tower_0: move above pick",
        "tower_0: descend to pick",
        "tower_0: grasp",
        "tower_0: lift",
        "tower_0: move above place",
        "tower_0: descend and seat",
        "tower_0: release",
        "tower_0: retreat",
    ]
    # A 2-stud grasp is 15.8 mm; open 4 mm per side, squeeze 4 mm past it.
    assert plan.steps[0].gripper_mm == pytest.approx(23.8)
    assert plan.steps[3].gripper_mm == pytest.approx(11.8)
    assert plan.steps[3].expected_mm == pytest.approx(15.8)
    assert plan.steps[5].expected_mm == pytest.approx(15.8)
    for step in plan.steps:
        for move in step.moves:
            assert move.speed_m_s <= 0.05
            assert move.pose[2, 3] <= plan.travel_z_m + 1e-12


def test_every_approach_and_retreat_is_vertical() -> None:
    """Sideways motion only happens at the travel height."""
    positions = load_positions(POSITIONS_FILE)
    plan = plan_assembly(
        load_structure(PACKAGE / "structures" / "three_bricks.json"), positions
    )
    previous = None
    for step in plan.steps:
        for move in step.moves:
            if previous is not None:
                sideways = np.linalg.norm(move.pose[:2, 3] - previous[:2, 3])
                if sideways > 1e-9:
                    assert previous[2, 3] == pytest.approx(plan.travel_z_m)
                    assert move.pose[2, 3] == pytest.approx(plan.travel_z_m)
            previous = move.pose
    contact_moves = [
        move for step in plan.steps for move in step.moves if move.contact != "free"
    ]
    assert len(contact_moves) == 6
    assert all(move.speed_m_s == 0.005 for move in contact_moves)


def test_reference_brick_reproduces_taught_corners(tmp_path: Path) -> None:
    """Seating the reference brick at a taught stud returns the taught pose."""
    positions = rotated_plate(load_positions(POSITIONS_FILE))
    for offset, taught in (
        ([0, 0], positions.origin),
        ([16, 0], positions.x_corner),
        ([0, 18], positions.y_corner),
    ):
        structure = load_structure(
            write_structure(tmp_path, placement_offsets=[offset])
        )
        assert place_poses(structure, positions)[0] == pytest.approx(taught)


def test_tower_stacks_and_turns_the_tool(tmp_path: Path) -> None:
    """Crossed bricks share one centre, rise 9.6 mm each and alternate grasp."""
    positions = load_positions(POSITIONS_FILE)
    poses = place_poses(
        load_structure(PACKAGE / "structures" / "three_bricks.json"), positions
    )
    for layer, pose in enumerate(poses):
        # Centre is stud (10, 10); the reference centre is stud (2, 1); the
        # example plate runs along base -X and -Y.
        assert pose[:3, 3] == pytest.approx(
            [0.10 - 8 * 0.008, -0.30 - 9 * 0.008, 0.070 + layer * 0.0096]
        )
    quarter = Rotation.from_euler("z", 90, degrees=True).as_matrix()
    assert poses[0][:3, :3] == pytest.approx(quarter @ positions.origin[:3, :3])
    assert poses[1][:3, :3] == pytest.approx(positions.origin[:3, :3])
    assert poses[2][:3, :3] == pytest.approx(poses[0][:3, :3])


@pytest.mark.parametrize("path", SIMULATOR_STRUCTURES, ids=lambda path: path.stem)
def test_targets_match_simulator_stud_grid_rule(path: Path) -> None:
    """Brick centres equal an independent evaluation of the simulator rule.

    ``centre = support_centre + R_support * (offset - support_size / 2
    + R_yaw * size / 2)`` with complex numbers as plane rotations; the plate is
    a zero-size support at the origin.
    """
    positions = rotated_plate(load_positions(POSITIONS_FILE))
    structure = load_structure(path)
    origin = positions.origin[:3, 3]
    x_step = (positions.x_corner[:3, 3] - origin) / positions.x_corner_studs
    y_step = (positions.y_corner[:3, 3] - origin) / positions.y_corner_studs
    normal = np.cross(x_step, y_step) / STUD_PITCH_M**2
    centres: list[complex] = []
    turns: list[complex] = []
    layers: list[int] = []
    for size, support, offset, yaw in zip(
        structure["brick_dimensions"],
        structure["support_bricks"],
        structure["placement_offsets"],
        structure["placement_yaws"],
    ):
        support_centre = 0j if support is None else centres[support]
        support_turn = 1 + 0j if support is None else turns[support]
        support_size = (
            0j
            if support is None
            else complex(*structure["brick_dimensions"][support][:2])
        )
        centres.append(
            support_centre
            + support_turn
            * (complex(*offset) - support_size / 2 + 1j**yaw * complex(*size[:2]) / 2)
        )
        turns.append(support_turn * 1j**yaw)
        layers.append(0 if support is None else layers[support] + 1)
    for pose, centre, layer in zip(place_poses(structure, positions), centres, layers):
        expected = (
            origin
            + x_step * (centre.real - 2)
            + y_step * (centre.imag - 1)
            + normal * layer * BRICK_HEIGHT_M
        )
        assert pose[:3, 3] == pytest.approx(expected, abs=1e-9)


def test_quarter_turn_placement_pivots_about_the_offset_stud(tmp_path: Path) -> None:
    """A 2x4 placed at [0, 0] with one quarter turn is centred at stud (-2, 1)."""
    positions = load_positions(POSITIONS_FILE)
    structure = load_structure(
        write_structure(tmp_path, brick_dimensions=[[2, 4, 3]], placement_yaws=[1])
    )
    pose = place_poses(structure, positions)[0]
    assert pose[:3, 3] == pytest.approx([0.10 + 4 * 0.008, -0.30, 0.070])
    assert pose[:3, :3] == pytest.approx(positions.origin[:3, :3])


@pytest.mark.parametrize(
    ("section", "key", "value", "message"),
    [
        ("motion", "travel_speed_m_s", 0.06, "travel_speed_m_s"),
        ("motion", "contact_speed_m_s", 0.02, "contact_speed_m_s"),
        ("motion", "acceleration_m_s2", 0.5, "acceleration_m_s2"),
        ("motion", "travel_speed_m_s", float("nan"), "travel_speed_m_s"),
        ("safety", "press_force_n", 60.0, "press_force_n"),
        ("safety", "press_overtravel_m", 0.005, "press_overtravel_m"),
        ("safety", "max_tilt_deg", 30.0, "max_tilt_deg"),
        ("gripper", "width_tolerance_mm", 3.0, "width_tolerance_mm"),
        ("gripper", "width_offset_mm", 8.0, "width_offset_mm"),
        ("baseplate", "x_corner_studs", 15, "re-record the corners"),
        (
            "baseplate",
            "y_corner",
            {"xyz_m": [0.10, -0.156, 0.070], "rpy_deg": [0.0, 180.0, 0.0]},
            "mirrored",
        ),
        (
            "baseplate",
            "x_corner",
            {"xyz_m": [-0.028, -0.30, 0.070], "rpy_deg": [0.0, 180.0, 5.0]},
            "tool orientation",
        ),
    ],
)
def test_positions_over_a_cap_or_off_the_grid_are_rejected(
    tmp_path: Path, section: str, key: str, value: object, message: str
) -> None:
    """Limits above the code caps and inconsistent taught corners fail to load."""
    with pytest.raises(ValueError, match=message):
        load_positions(edited_positions(tmp_path, section, key, value))


def test_target_outside_workspace_is_rejected(tmp_path: Path) -> None:
    """A pickup below the workspace floor fails before any motion is planned."""
    positions = load_positions(
        edited_positions(
            tmp_path,
            "pickups",
            "tower_0",
            {"xyz_m": [-0.20, -0.30, 0.055], "rpy_deg": [0.0, 180.0, 0.0]},
        )
    )
    with pytest.raises(ValueError, match="outside the workspace box"):
        plan_assembly(load_structure(write_structure(tmp_path)), positions)


def test_tilted_tool_is_rejected(tmp_path: Path) -> None:
    """A pickup recorded with the tool 10 degrees off vertical is refused."""
    positions = load_positions(
        edited_positions(
            tmp_path,
            "pickups",
            "tower_0",
            {"xyz_m": [-0.20, -0.30, 0.067], "rpy_deg": [0.0, 170.0, 0.0]},
        )
    )
    with pytest.raises(ValueError, match="tilted 10.0 deg"):
        plan_assembly(load_structure(write_structure(tmp_path)), positions)


@pytest.mark.parametrize(
    ("fields", "message"),
    [
        ({"brick_dimensions": [[4, 2, 1]]}, "plates tall"),
        ({"support_bricks": [0]}, "earlier brick"),
        ({"placement_yaws": [4]}, "quarter turn"),
        ({"placement_offsets": []}, "one entry per part"),
    ],
)
def test_inconsistent_structure_is_rejected(
    tmp_path: Path, fields: dict[str, list], message: str
) -> None:
    """Structures the planner cannot build fail to load."""
    with pytest.raises(ValueError, match=message):
        load_structure(write_structure(tmp_path, **fields))


def test_gripper_width_offset_shifts_commands_and_expectations(tmp_path: Path) -> None:
    """A gripper reading 1 mm wide is commanded and checked 1 mm wider."""
    positions = load_positions(
        edited_positions(tmp_path, "gripper", "width_offset_mm", 1.0)
    )
    plan = plan_assembly(
        load_structure(PACKAGE / "structures" / "single_brick.json"), positions
    )
    assert plan.steps[0].gripper_mm == pytest.approx(24.8)
    assert plan.steps[3].gripper_mm == pytest.approx(12.8)
    assert plan.steps[3].expected_mm == pytest.approx(16.8)
