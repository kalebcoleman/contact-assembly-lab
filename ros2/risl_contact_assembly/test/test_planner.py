"""Tests for known-pose assembly planning."""

import copy
from math import cos, nan, pi, sin
from pathlib import Path

import pytest
import yaml
from risl_contact_assembly.planner import load_config, load_structure, plan_structure

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = PACKAGE_ROOT / "config/assembly.yaml"
SINGLE_PATH = PACKAGE_ROOT / "fixtures/single_brick.json"
THREE_PATH = PACKAGE_ROOT / "fixtures/three_bricks.json"

BRICK_ACTIONS = [
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


def test_single_brick_plan_has_contract_steps() -> None:
    """One brick yields ten TCP steps with the fixture pose and target pose."""
    steps = plan_structure(load_structure(SINGLE_PATH), load_config(CONFIG_PATH))
    assert [step["action"] for step in steps] == BRICK_ACTIONS
    assert {step["brick_id"] for step in steps} == {"single_0"}
    for step in steps:
        assert len(step["xyz_m"]) == 3
        assert len(step["rpy_deg"]) == 3
        assert step["speed_m_s"] > 0
    assert steps[2]["gripper_width_mm"] == pytest.approx(20.0)
    assert all("gripper_width_mm" not in step for step in steps[:2] + steps[3:])
    # Absolute fixture TCP pose: approach and lift hover, descend/close at it.
    assert steps[0]["xyz_m"] == pytest.approx([0.25, 0.18, 0.0448])
    assert steps[1]["xyz_m"] == pytest.approx([0.25, 0.18, 0.0048])
    assert steps[3]["xyz_m"] == pytest.approx([0.25, 0.18, 0.0448])
    # The plate-centred brick bottom is at 0.0032 m; calibration lifts TCP by
    # the half brick height, so the target TCP is at 0.008 m.
    assert steps[4]["xyz_m"] == pytest.approx([0.25, 0.40, 0.048])
    assert steps[5]["xyz_m"] == pytest.approx([0.25, 0.40, 0.010])
    assert steps[6]["xyz_m"] == pytest.approx([0.25, 0.40, 0.008])
    assert steps[7]["xyz_m"] == pytest.approx([0.25, 0.40, 0.008])
    assert steps[8]["xyz_m"] == pytest.approx([0.25, 0.40, 0.008])
    assert steps[9]["xyz_m"] == pytest.approx([0.25, 0.40, 0.048])
    assert steps[0]["rpy_deg"] == pytest.approx([180.0, 0.0, 0.0])
    assert steps[7]["rpy_deg"] == pytest.approx([180.0, 0.0, 0.0])


def test_three_bricks_stack_in_build_order() -> None:
    """Three bricks are planned in order at one plate-centred stack."""
    steps = plan_structure(load_structure(THREE_PATH), load_config(CONFIG_PATH))
    assert len(steps) == 30
    assert [step["action"] for step in steps] == BRICK_ACTIONS * 3
    assert [steps[index * 10]["brick_id"] for index in range(3)] == [
        "tower_0",
        "tower_1",
        "tower_2",
    ]
    for index in range(3):
        seat = steps[index * 10 + 7]
        assert seat["xyz_m"][:2] == pytest.approx([0.25, 0.40])
        assert seat["xyz_m"][2] == pytest.approx(0.008 + 0.0096 * index)


def test_native_target_formula_matches_plan() -> None:
    """Target poses reproduce the simulator's stud-grid child pose formula."""
    structure = load_structure(THREE_PATH)
    steps = plan_structure(structure, load_config(CONFIG_PATH))
    stud_pitch_m = 0.008
    plate_unit_m = 0.0096 / 3
    parent_p = (0.25, 0.40, 0.0)
    parent_yaw = 0.0
    parent_size = (20, 20)
    parent_height_m = plate_unit_m
    for index in range(3):
        dimension = structure["brick_dimensions"][index]
        offset = structure["placement_offsets"][index]
        local_yaw = (structure["placement_yaws"][index] * pi) / 2
        # p_child = p_sup + R_sup * (corner + R_local * half_footprint).
        corner_x = (offset[0] - parent_size[0] / 2) * stud_pitch_m
        corner_y = (offset[1] - parent_size[1] / 2) * stud_pitch_m
        corner_z = parent_height_m
        half_x = dimension[0] * stud_pitch_m / 2
        half_y = dimension[1] * stud_pitch_m / 2
        local_x = cos(local_yaw) * half_x - sin(local_yaw) * half_y
        local_y = sin(local_yaw) * half_x + cos(local_yaw) * half_y
        shift_x = corner_x + local_x
        shift_y = corner_y + local_y
        child_x = parent_p[0] + cos(parent_yaw) * shift_x - sin(parent_yaw) * shift_y
        child_y = parent_p[1] + sin(parent_yaw) * shift_x + cos(parent_yaw) * shift_y
        child_z = parent_p[2] + corner_z
        seat = steps[index * 10 + 7]
        assert steps[index * 10 + 4]["xyz_m"] == pytest.approx(
            [child_x, child_y, child_z + 0.0048 + 0.04]
        )
        assert seat["xyz_m"] == pytest.approx([child_x, child_y, child_z + 0.0048])
        assert seat["rpy_deg"][2] == pytest.approx(0.0)
        parent_p = (child_x, child_y, child_z)
        parent_yaw += local_yaw
        parent_size = (dimension[0], dimension[1])
        parent_height_m = dimension[2] * plate_unit_m


def test_baseplate_origin_and_yaw_transform() -> None:
    """Base plate origin and yaw transform the target pose in base."""
    config = load_config(CONFIG_PATH)
    config["baseplate"]["origin_xyz_m"] = [0.10, 0.20, 0.01]
    config["baseplate"]["yaw_deg"] = 90.0
    config["calibration"]["brick_to_tcp_xyz_m"] = [0.001, 0.0, 0.0048]
    steps = plan_structure(load_structure(SINGLE_PATH), config)
    # The plate-centred brick target stays at the plate centre; the calibrated
    # brick-axis X offset now points along base +Y.
    assert steps[7]["xyz_m"] == pytest.approx([0.10, 0.201, 0.018])
    assert steps[7]["rpy_deg"] == pytest.approx([180.0, 0.0, 90.0])


def test_placement_yaw_rotates_target_pose() -> None:
    """A quarter-turn placement rotates the brick footprint and TCP yaw."""
    config = load_config(CONFIG_PATH)
    structure = copy.deepcopy(load_structure(SINGLE_PATH))
    structure["placement_offsets"] = [[0, 0]]
    structure["placement_yaws"] = [1]
    steps = plan_structure(structure, config)
    assert steps[7]["xyz_m"] == pytest.approx([0.154, 0.328, 0.008])
    assert steps[7]["rpy_deg"] == pytest.approx([180.0, 0.0, 90.0])


def test_pickup_pose_is_absolute_and_independent_of_target_orientation() -> None:
    """Pickup yaw only affects grasp-side steps; targets use calibration."""
    config = load_config(CONFIG_PATH)
    config["pickup"]["rpy_deg"] = [180.0, 0.0, 90.0]
    steps = plan_structure(load_structure(SINGLE_PATH), config)
    assert steps[2]["xyz_m"] == pytest.approx([0.25, 0.18, 0.0048])
    assert steps[2]["rpy_deg"] == pytest.approx([180.0, 0.0, 90.0])
    assert steps[7]["rpy_deg"] == pytest.approx([180.0, 0.0, 0.0])


def test_stage_coordinates_are_ignored() -> None:
    """Simulator stage staging coordinates never enter the base-frame plan."""
    config = load_config(CONFIG_PATH)
    structure = copy.deepcopy(load_structure(THREE_PATH))
    expected = plan_structure(structure, config)
    structure["baseplate_xy_m"] = [9.9, -9.9]
    structure["brick_positions_xy_m"] = [[0.0, 0.0]] * 3
    assert plan_structure(structure, config) == expected


def test_speed_scale_applies_and_exceeding_limit_is_rejected() -> None:
    """Speeds scale once and are validated instead of silently clamped."""
    config = load_config(CONFIG_PATH)
    config["limits"]["max_speed_scale"] = 0.5
    steps = plan_structure(load_structure(SINGLE_PATH), config)
    assert steps[0]["speed_m_s"] == pytest.approx(0.025)
    assert steps[1]["speed_m_s"] == pytest.approx(0.005)
    config["limits"]["max_speed_m_s"] = 0.02
    with pytest.raises(ValueError, match="max_speed_m_s"):
        plan_structure(load_structure(SINGLE_PATH), config)


def test_workspace_bounds_reject_outside_pose() -> None:
    """Every step pose must lie inside the configured base-frame AABB."""
    config = load_config(CONFIG_PATH)
    config["limits"]["workspace_max_m"] = [0.24, 0.60, 0.35]
    with pytest.raises(ValueError, match="outside the workspace"):
        plan_structure(load_structure(SINGLE_PATH), config)


def test_nonfinite_values_are_rejected(tmp_path: Path) -> None:
    """Non-finite config values fail validation and non-finite poses fail."""
    document = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    document["baseplate"]["origin_xyz_m"][0] = nan
    path = tmp_path / "assembly.yaml"
    path.write_text(yaml.safe_dump(document), encoding="utf-8")
    with pytest.raises(ValueError, match="finite"):
        load_config(path)
    config = load_config(CONFIG_PATH)
    config["motion"]["hover_m"] = nan
    with pytest.raises(ValueError, match="not finite"):
        plan_structure(load_structure(SINGLE_PATH), config)


def test_invalid_config_limits_are_rejected(tmp_path: Path) -> None:
    """Speed scale, speed and gripper width limits are enforced on load."""
    document = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    path = tmp_path / "assembly.yaml"
    document["limits"]["max_speed_scale"] = 1.5
    path.write_text(yaml.safe_dump(document), encoding="utf-8")
    with pytest.raises(ValueError, match="max_speed_scale"):
        load_config(path)
    document["limits"]["max_speed_scale"] = 1.0
    document["motion"]["travel_speed_m_s"] = 0.0
    path.write_text(yaml.safe_dump(document), encoding="utf-8")
    with pytest.raises(ValueError, match="travel_speed_m_s"):
        load_config(path)
    document["motion"]["travel_speed_m_s"] = 0.05
    document["pickup"]["gripper_width_mm"] = 111.0
    path.write_text(yaml.safe_dump(document), encoding="utf-8")
    with pytest.raises(ValueError, match="gripper_width_mm"):
        load_config(path)


def test_invalid_structure_is_rejected() -> None:
    """Forward supports, mismatched lengths, bogus dims and yaws fail."""
    config = load_config(CONFIG_PATH)
    structure = copy.deepcopy(load_structure(THREE_PATH))
    structure["support_bricks"] = [1, 0, 1]
    with pytest.raises(ValueError, match="support_bricks"):
        plan_structure(structure, config)
    structure = copy.deepcopy(load_structure(THREE_PATH))
    structure["brick_dimensions"] = [[2, 4, 3], [4, 2, 3]]
    with pytest.raises(ValueError, match="equal"):
        plan_structure(structure, config)
    structure = copy.deepcopy(load_structure(THREE_PATH))
    structure["brick_dimensions"] = [[2, 4, 3], [4.0, 2, 3], [2, 4, 3]]
    with pytest.raises(ValueError, match="brick_dimensions"):
        plan_structure(structure, config)
    structure = copy.deepcopy(load_structure(THREE_PATH))
    structure["placement_offsets"] = [[9, 8], [-1.0, 1], [1, -1]]
    with pytest.raises(ValueError, match="placement_offsets"):
        plan_structure(structure, config)
    structure = copy.deepcopy(load_structure(THREE_PATH))
    structure["placement_yaws"] = [0, 0, 4]
    with pytest.raises(ValueError, match="placement_yaws"):
        plan_structure(structure, config)


def test_fixtures_use_simulator_structure_schema() -> None:
    """Fixtures carry the simulator structure keys, not the docs catalog."""
    config = load_config(CONFIG_PATH)
    for path in (SINGLE_PATH, THREE_PATH):
        structure = load_structure(path)
        assert {
            "experiment_name",
            "baseplate_xy_m",
            "part_names",
            "brick_dimensions",
            "brick_colors",
            "brick_positions_xy_m",
            "support_bricks",
            "placement_offsets",
        } <= set(structure)
        plan = plan_structure(structure, config)
        assert len(plan) == 10 * len(structure["part_names"])


@pytest.mark.parametrize("height", [1, 2, 4])
def test_unsupported_brick_height_is_rejected(height: int) -> None:
    """Reject heights unsupported by the source assembly structure contract."""
    structure = load_structure(SINGLE_PATH)
    structure["brick_dimensions"][0][2] = height
    with pytest.raises(ValueError, match="height 3"):
        plan_structure(structure, load_config(CONFIG_PATH))
