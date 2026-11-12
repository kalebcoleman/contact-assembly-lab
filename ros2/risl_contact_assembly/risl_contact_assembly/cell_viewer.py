"""Show the arm inside the work cell and report contacts with it.

This is the ``risl_simulation`` viewer with ``scene/cell.xml`` added to its
scene. It only subscribes: joint states and gripper width are mirrored, never
commanded, so it runs beside real or fake hardware alike.

The scene frame is the UR ``base`` frame, metres. Contacts are geometric
checks of the mirrored pose; no dynamics are stepped. The gripper is
``risl_simulation``'s schematic RG2 and a carried brick is not modelled.
"""

import json
from os import _exit
from pathlib import Path
from sys import stdout
from tempfile import TemporaryDirectory
from unittest.mock import patch
from xml.etree import ElementTree

import mujoco
import numpy as np
import rclpy
from ament_index_python.packages import get_package_share_directory
from rclpy.executors import ExternalShutdownException
from risl_simulation import simulation_node
from risl_ur.custom_libraries.gripper_geometry import gripper_width_to_reach

from risl_contact_assembly.planner import (
    BRICK_SIDE_GAP_MM,
    REFERENCE_BRICK_STUDS,
    STUD_PITCH_M,
    load_positions,
)

BASEPLATE_STUDS = 20
BASEPLATE_THICKNESS_M = 0.0032
# The drawn plate top sits this far below the taught fingertips.
BASEPLATE_BELOW_FINGERTIPS_M = 0.002
FINGER_BODIES = ("rg2_left_finger", "rg2_right_finger")
WARNING_PERIOD_S = 2.0


def add_cell(robot_model: mujoco.MjModel) -> mujoco.MjModel:
    """Rebuild the ``risl_simulation`` scene with the work cell in it.

    The table plane ``risl_simulation`` draws at ``base`` z = 0 is removed; the
    cell supplies the real surfaces. Collision bits make every arm and gripper
    geom above the base link collide with every cell geom and nothing else. A
    hidden ``baseplate`` body is added for ``CellViewer`` to place.

    Args:
        robot_model: Model just compiled by ``risl_simulation``'s ``build_scene``.

    Returns:
        Model containing the robot and the cell.
    """
    with TemporaryDirectory() as directory:
        robot_file = Path(directory) / "robot.xml"
        mujoco.mj_saveLastXML(str(robot_file), robot_model)
        scene = ElementTree.parse(robot_file).getroot()
    (world,) = scene.iter("worldbody")
    (table_plane,) = world.findall("geom[@type='plane']")
    world.remove(table_plane)
    for geom in world.iter("geom"):
        geom.set("contype", "0")
        geom.set("conaffinity", "0")
    (shoulder,) = world.iterfind(".//body[@name='shoulder_link']")
    for geom in shoulder.iter("geom"):
        geom.set("contype", "1")
    cell_file = (
        Path(get_package_share_directory("risl_contact_assembly"))
        / "scene"
        / "cell.xml"
    )
    (cell,) = ElementTree.parse(cell_file).getroot().iter("worldbody")
    for part in cell:
        for geom in part.iter("geom"):
            geom.set("contype", "0")
            geom.set("conaffinity", "1")
        world.append(part)
    plate = ElementTree.SubElement(
        world, "body", name="baseplate", mocap="true", pos="0 0 -10"
    )
    half_side_m = BASEPLATE_STUDS * STUD_PITCH_M / 2
    ElementTree.SubElement(
        plate,
        "geom",
        type="box",
        size=f"{half_side_m} {half_side_m} {BASEPLATE_THICKNESS_M / 2}",
        pos=f"0 0 {-BASEPLATE_THICKNESS_M / 2}",
        rgba="0.1 0.6 0.2 1",
        contype="0",
        conaffinity="0",
    )
    return mujoco.MjModel.from_xml_string(
        ElementTree.tostring(scene, encoding="unicode")
    )


class CellViewer(simulation_node.SimulationNode):
    """``risl_simulation`` viewer with the cell, a baseplate and contact reports.

    Parameters, besides those of ``risl_simulation``:

    - ``clearance_m``: the arm and gripper body are reported when closer than
      this to the cell. The fingers are reported only when they touch it.
    - ``bench_offset_m``: shift of the bench from its CAD pose, ``[x, y, z]``
      in ``base``; x follows the linear axis the robot rides on.
    - ``positions_file``: positions YAML whose taught baseplate is drawn
      (display only, no collision); empty draws none.
    - ``contact_report``: JSON file written at exit; empty writes none.
    """

    def __init__(self) -> None:
        """Build the scene with the cell and apply this node's parameters."""
        # SimulationNode builds its scene inside __init__ with no hook for
        # extra geometry, so its build_scene is wrapped while it runs.
        build_robot_scene = simulation_node.build_scene
        with patch.object(
            simulation_node,
            "build_scene",
            lambda **options: add_cell(build_robot_scene(**options)),
        ):
            super().__init__()
        self.clearance_m = self.declare_parameter("clearance_m", 0.01).value
        bench_offset_m = self.declare_parameter("bench_offset_m", [0.0, 0.0, 0.0]).value
        positions_file = self.declare_parameter("positions_file", "").value
        self.contact_report = self.declare_parameter("contact_report", "").value
        # Closest approach per (robot body, cell part), metres; negative is
        # penetration depth.
        self.closest_m: dict[tuple[str, str], float] = {}
        self.poses_checked = 0

        self.model.body("bench").pos[:] = bench_offset_m
        finger_bodies = [self.model.body(name).id for name in FINGER_BODIES]
        for geom in range(self.model.ngeom):
            if self.model.geom_contype[geom] and (
                self.model.geom_bodyid[geom] not in finger_bodies
            ):
                self.model.geom_margin[geom] = self.clearance_m
        if positions_file:
            positions = load_positions(positions_file)
            origin = positions.origin[:3, 3]
            x_step = (positions.x_corner[:3, 3] - origin) / positions.x_corner_studs
            y_step = (positions.y_corner[:3, 3] - origin) / positions.y_corner_studs
            x_axis = x_step / np.linalg.norm(x_step)
            normal = np.cross(x_axis, y_step)
            normal /= np.linalg.norm(normal)
            rotation = np.column_stack([x_axis, np.cross(normal, x_axis), normal])
            # The taught origin pose grips the reference brick; the fingertips
            # are one reach along the tool axis from the flange.
            grasp_tenths_mm = 10 * (
                REFERENCE_BRICK_STUDS[1] * STUD_PITCH_M * 1000 - BRICK_SIDE_GAP_MM
            )
            fingertips = origin + positions.origin[:3, 2] * gripper_width_to_reach(
                grasp_tenths_mm
            )
            centre = (
                fingertips
                + x_step * (BASEPLATE_STUDS - REFERENCE_BRICK_STUDS[0]) / 2
                + y_step * (BASEPLATE_STUDS - REFERENCE_BRICK_STUDS[1]) / 2
                - normal * BASEPLATE_BELOW_FINGERTIPS_M
            )
            plate = self.model.body("baseplate").mocapid[0]
            self.data.mocap_pos[plate] = centre
            mujoco.mju_mat2Quat(self.data.mocap_quat[plate], rotation.ravel())

    def refresh_viewer(self) -> None:
        """Redraw the scene, then record and warn about contacts with the cell."""
        super().refresh_viewer()
        if self.mirror.addresses.keys() - self.mirror.seen:
            return
        self.poses_checked += 1
        for contact in self.data.contact:
            bodies = [
                self.model.body(self.model.geom_bodyid[geom]).name
                for geom in contact.geom
            ]
            robot = 0 if self.model.geom_contype[contact.geom[0]] else 1
            pair = (bodies[robot], self.model.geom(contact.geom[1 - robot]).name)
            self.closest_m[pair] = min(
                self.closest_m.get(pair, np.inf), float(contact.dist)
            )
            self.get_logger().warning(
                f"CONTACT: {pair[0]} is {contact.dist * 1000:.1f} mm from cell part "
                f"{pair[1]} (negative is penetration)",
                throttle_duration_sec=WARNING_PERIOD_S,
            )

    def report(self) -> int:
        """Print the contact summary and write the report file.

        Printed rather than logged because ROS is already shut down.

        Returns:
            Number of robot body and cell part pairs that came within the
            clearance.
        """
        contacts = [
            {"robot": robot, "cell": cell, "closest_mm": round(distance * 1000, 2)}
            for (robot, cell), distance in sorted(self.closest_m.items())
        ]
        print(
            f"CONTACT SUMMARY: {len(contacts)} contact pairs in "
            f"{self.poses_checked} checked poses "
            f"(clearance {self.clearance_m * 1000:.0f} mm)"
        )
        for contact in contacts:
            print(
                f"  {contact['robot']} - {contact['cell']}: {contact['closest_mm']} mm"
            )
        if self.contact_report:
            Path(self.contact_report).write_text(
                json.dumps(
                    {
                        "clearance_mm": self.clearance_m * 1000,
                        "poses_checked": self.poses_checked,
                        "contacts": contacts,
                    },
                    indent=1,
                )
                + "\n",
                encoding="utf-8",
            )
        return len(contacts)


def main(args: list[str] | None = None) -> None:
    """Run the viewer until interrupted, then report contacts.

    The process exits with status 1 when any contact was seen or no pose was
    ever checked.

    Args:
        args: ROS arguments.
    """
    rclpy.init(args=args)
    node = CellViewer()
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    contacts = node.report()
    if not node.poses_checked:
        print("NOT CHECKED: no joint states were received")
    stdout.flush()
    # Skip Python's exit handlers: glfw's terminate() deadlocks against the
    # viewer thread, which also hangs the unmodified risl_simulation node.
    _exit(1 if contacts or not node.poses_checked else 0)
