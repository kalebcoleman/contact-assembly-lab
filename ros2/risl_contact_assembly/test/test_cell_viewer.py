"""Tests for the MuJoCo cell scene and its contact check."""

import json
from pathlib import Path
from types import ModuleType
from xml.etree import ElementTree

import numpy as np
import pytest
import rclpy
from risl_contact_assembly.motion import plan_move
from risl_contact_assembly.planner import Move, load_positions

PACKAGE = Path(__file__).resolve().parents[1]
JOINTS = (
    "shoulder_pan_joint",
    "shoulder_lift_joint",
    "elbow_joint",
    "wrist_1_joint",
    "wrist_2_joint",
    "wrist_3_joint",
)


@pytest.fixture(scope="module")
def viewer() -> ModuleType:
    """Import the viewer module, skipping where MuJoCo or risl_simulation is absent.

    The skip is raised here rather than at import: with the launch_testing
    pytest plugin a module-level skip drops every test file in the directory.

    Returns:
        ``risl_contact_assembly.cell_viewer``.
    """
    pytest.importorskip("mujoco")
    pytest.importorskip("risl_simulation")
    return pytest.importorskip("risl_contact_assembly.cell_viewer")


def contacts_at(viewer: ModuleType, joints_deg: list[float]) -> set[tuple[str, str]]:
    """Return the robot body and cell part pairs in contact at a joint pose.

    Args:
        viewer: ``risl_contact_assembly.cell_viewer``.
        joints_deg: Six arm joint angles, degrees.

    Returns:
        Pairs of robot body name and cell geom name.
    """
    mujoco = viewer.mujoco
    model = viewer.add_cell(
        viewer.simulation_node.build_scene(object_names=("jenga_0",))
    )
    data = mujoco.MjData(model)
    for name, angle in zip(JOINTS, joints_deg):
        data.qpos[model.jnt_qposadr[model.joint(name).id]] = np.radians(angle)
    mujoco.mj_forward(model, data)
    pairs = set()
    for contact in data.contact:
        robot = 0 if model.geom_contype[contact.geom[0]] else 1
        pairs.add(
            (
                model.body(model.geom_bodyid[contact.geom[robot]]).name,
                model.geom(contact.geom[1 - robot]).name,
            )
        )
    return pairs


def test_cell_dimensions_match_the_workstation_drawing() -> None:
    """The robot plate tops out at the base origin with the table 85 mm below."""
    parts = {
        geom.attrib["name"]: (
            np.array(geom.attrib["pos"].split(), dtype=float),
            np.array(geom.attrib["size"].split(), dtype=float),
        )
        for geom in ElementTree.parse(PACKAGE / "scene" / "cell.xml").iter("geom")
    }
    assert len(parts) == 114
    plate_centre, plate_half = parts["ST_RB_001_0002_400_robo_base2"]
    assert plate_centre[:2] == pytest.approx([0.0, 0.0], abs=1e-4)
    assert plate_centre[2] + plate_half[2] == pytest.approx(0.0, abs=1e-4)
    table_centre, table_half = parts["imported_PANEL_B2F52AEB2A0D_804849_271"]
    assert 2 * table_half == pytest.approx([1.89, 0.72, 0.0096], abs=1e-3)
    assert table_centre[2] + table_half[2] == pytest.approx(-0.0855, abs=5e-4)
    # The table lies on the -Y side of the robot, where the demo poses are.
    assert table_centre[1] + table_half[1] < -0.08
    assert parts["floor"][0][2] == pytest.approx(-0.885, abs=1e-3)


def test_working_pose_above_the_table_is_clear(viewer: ModuleType) -> None:
    """The mock start pose over the table touches nothing."""
    assert contacts_at(viewer, [90.0, -80.0, 90.0, -100.0, -90.0, 0.0]) == set()


def test_reaching_into_the_table_is_reported(viewer: ModuleType) -> None:
    """A pose with the gripper below the tabletop reports the table panel."""
    pairs = contacts_at(viewer, [90.0, -40.0, 100.0, -150.0, -90.0, 0.0])
    assert any("PANEL" in cell for _, cell in pairs)
    assert all(robot != "base_link_inertia" for robot, _ in pairs)


def test_demo_positions_sit_on_the_cell_table() -> None:
    """The example pickups put the fingertips just above the cell's tabletop."""
    positions = load_positions(PACKAGE / "config" / "demo_positions.yaml")
    # Flange height minus the 0.1506 m fingertip reach at a 15.8 mm opening.
    fingertip_z = positions.pickups["tower_0"][2, 3] - 0.1506
    assert -0.0855 < fingertip_z < -0.0855 + 0.005


@pytest.mark.parametrize(
    ("bench_z_m", "expected_pairs"),
    [
        (0.0, set()),
        (
            0.02,
            {
                ("rg2_left_finger", "imported_PANEL_B2F52AEB2A0D_804849_271"),
                ("rg2_right_finger", "imported_PANEL_B2F52AEB2A0D_804849_271"),
            },
        ),
    ],
)
def test_viewer_reports_fingers_in_a_raised_table(
    viewer: ModuleType,
    tmp_path: Path,
    bench_z_m: float,
    expected_pairs: set[tuple[str, str]],
) -> None:
    """At the example pickup the fingers clear the table unless it is raised."""
    positions_file = PACKAGE / "config" / "demo_positions.yaml"
    positions = load_positions(positions_file)
    start = np.radians([90.0, -80.0, 90.0, -100.0, -90.0, 0.0])
    _, path, _ = plan_move(
        start, Move(positions.pickups["tower_0"], 0.05), positions.motion
    )
    report_file = tmp_path / "contacts.json"
    rclpy.init(
        args=[
            "--ros-args",
            "-p",
            "show_viewer:=false",
            "-p",
            f"positions_file:={positions_file}",
            "-p",
            f"contact_report:={report_file}",
            "-p",
            f"bench_offset_m:=[0.0, 0.0, {bench_z_m}]",
        ]
    )
    try:
        node = viewer.CellViewer()
        node.refresh_viewer()
        assert node.poses_checked == 0
        node.mirror.update(node.data, list(JOINTS), path[-1].tolist())
        node.mirror.set_width(node.data, 23.8)
        node.refresh_viewer()
        assert node.poses_checked == 1
        assert set(node.closest_m) == expected_pairs
        assert node.report() == len(expected_pairs)
        report = json.loads(report_file.read_text(encoding="utf-8"))
        assert report["poses_checked"] == 1
        assert [contact["closest_mm"] < 0 for contact in report["contacts"]] == [
            True
        ] * len(expected_pairs)
        # The drawn baseplate rests on the tabletop under the taught poses.
        plate_top_z = node.data.mocap_pos[node.model.body("baseplate").mocapid[0]][2]
        assert plate_top_z - 0.0032 == pytest.approx(-0.0855, abs=0.001)
        node.destroy_node()
    finally:
        rclpy.shutdown()
