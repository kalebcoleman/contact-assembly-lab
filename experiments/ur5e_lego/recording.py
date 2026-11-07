"""Record the UR5e brick experiments for later measurement comparisons."""

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from time import monotonic_ns, time_ns

import numpy as np
from isaacsim.core.api import World
from isaacsim.core.prims import SingleArticulation
from isaacsim.core.utils.numpy.rotations import (
    quats_to_rot_matrices,
    rot_matrices_to_quats,
)
from isaacsim.core.utils.stage import get_current_stage
from pxr import Usd, UsdGeom

from bricksim.core import (
    compute_connection_transform,
    get_assembly_debug_infos,
    get_assembly_thresholds,
    get_breakage_thresholds,
    lookup_physics_connection,
)


class RunRecorder:
    """Stream physics-step state, commands, and simulation-only contact data."""

    def __init__(
        self,
        root: Path,
        experiment: str,
        world: World,
        robot: SingleArticulation,
        gripper: SingleArticulation,
        part_paths: list[str],
        placements: list[tuple[str, str, tuple[int, int]]],
        config: dict[str, object],
    ) -> None:
        """Create a unique log and subscribe to the experiment's physics steps.

        Args:
            root: Repository root containing the output directory.
            experiment: Transfer, baseplate, or stack experiment name.
            world: Active simulation world.
            robot: UR5e articulation.
            gripper: RG2 articulation.
            part_paths: USD paths of the bricks and any baseplate.
            placements: Stud path, hole path, and target offset for each placement.
            config: Effective experiment settings to preserve with the run.
        """
        self.world = world
        self.robot = robot
        self.gripper = gripper
        self.phase = "calibration"
        self.brick_index = 0
        self.tool_target: dict[str, list[float]] | None = None
        self.elapsed_s = 0.0
        self.sample_index = 0
        self.stage = get_current_stage()
        self.tool_path = "/World/UR5e/wrist_3_link/flange/tool0"
        self.tool = self.stage.GetPrimAtPath(self.tool_path)
        self.parts = {path: self.stage.GetPrimAtPath(path) for path in part_paths}
        self.placements = []
        for stud_path, hole_path, offset in placements:
            orientation, position = compute_connection_transform(
                stud_path, 1, hole_path, 0, offset, 0
            )
            target = np.eye(4)
            target[:3, :3] = quats_to_rot_matrices(np.asarray(orientation))
            target[:3, 3] = position
            self.placements.append((stud_path, hole_path, offset, target))

        now = datetime.now(timezone.utc)
        directory = root / "outputs" / "ur5e_lego"
        directory.mkdir(parents=True, exist_ok=True)
        self.path = (
            directory / f"{now.strftime('%Y%m%dT%H%M%S.%fZ')}-{experiment}.jsonl"
        )
        self.output = self.path.open("x")
        self.output.write(
            json.dumps(
                {
                    "kind": "metadata",
                    "schema_version": 1,
                    "source": "simulation",
                    "experiment": experiment,
                    "created_utc": now.isoformat(),
                    "config": config,
                    "robot_joint_names": robot.dof_names,
                    "gripper_joint_names": gripper.dof_names,
                    "tool_prim": self.tool_path,
                    "part_prims": part_paths,
                    "frames": {
                        "poses": "world",
                        "placement_error": "support part frame",
                        "quaternion": "wxyz",
                    },
                    "units": {
                        "position": "m",
                        "rotation": "rad",
                        "joint_position": "rad",
                        "joint_velocity": "rad/s",
                        "joint_effort": "N*m",
                        "contact_force": "N",
                        "elapsed": "s",
                        "host_clock": "ns",
                    },
                    "clock_note": (
                        "Samples precede the step ending at simulation_elapsed_s; "
                        "host clocks are not synchronized with hardware."
                    ),
                    "measurement_note": (
                        "States, efforts, contacts, and connections are simulated; "
                        "targets are commands."
                    ),
                }
            )
            + "\n"
        )
        self.output.flush()
        world.add_physics_callback("ur5e_run_recorder", self.sample)
        print(f"UR5e recording: {self.path}", flush=True)

    def sample(self, dt: float) -> None:
        """Write one sample from the active simulation physics callback.

        Args:
            dt: Physics step duration in seconds.
        """
        self.elapsed_s += dt
        self.sample_index += 1
        cache = UsdGeom.XformCache(Usd.TimeCode.Default())
        transforms = {
            path: np.array(cache.GetLocalToWorldTransform(prim)).T
            for path, prim in self.parts.items()
        }
        tool = np.array(cache.GetLocalToWorldTransform(self.tool)).T
        robot_action = self.robot.get_applied_action()
        gripper_action = self.gripper.get_applied_action()
        gripper_index = self.gripper.get_dof_index("rg2_gripper_joint")
        assembly = get_assembly_thresholds()
        breakage = get_breakage_thresholds()
        placements = []
        for stud_path, hole_path, offset, target in self.placements:
            relative = np.linalg.inv(transforms[stud_path]) @ transforms[hole_path]
            rotation_error = target[:3, :3].T @ relative[:3, :3]
            connection = lookup_physics_connection(stud_path, 1, hole_path, 0)
            placements.append(
                {
                    "stud_path": stud_path,
                    "hole_path": hole_path,
                    "target_offset_studs": offset,
                    "position_error_m": (relative[:3, 3] - target[:3, 3]).tolist(),
                    "yaw_error_rad": float(
                        np.arctan2(rotation_error[1, 0], rotation_error[0, 0])
                    ),
                    "connected": connection is not None,
                    "connected_offset_studs": None
                    if connection is None
                    else connection.offset,
                    "connected_yaw": None if connection is None else connection.yaw,
                }
            )
        contacts = [
            {
                "stud_path": info.stud_path,
                "hole_path": info.hole_path,
                "accepted": info.accepted,
                "relative_distance_m": info.relative_distance,
                "position_error_m": info.position_error,
                "yaw_error_rad": info.yaw_error,
                "tilt_rad": info.tilt,
                "projected_force_n": info.projected_force,
            }
            for info in get_assembly_debug_infos()
        ]
        self.output.write(
            json.dumps(
                {
                    "kind": "sample",
                    "sample_index": self.sample_index,
                    "simulation_elapsed_s": self.elapsed_s,
                    "physics_dt_s": dt,
                    "host_utc_ns": time_ns(),
                    "host_monotonic_ns": monotonic_ns(),
                    "phase": self.phase,
                    "brick_index": self.brick_index,
                    "assembly_settings": {
                        "enabled": assembly.enabled,
                        "distance_tolerance_m": assembly.distance_tolerance,
                        "max_penetration_m": assembly.max_penetration,
                        "z_angle_tolerance_rad": assembly.z_angle_tolerance,
                        "required_force_n": assembly.required_force,
                        "yaw_tolerance_rad": assembly.yaw_tolerance,
                        "position_tolerance_m": assembly.position_tolerance,
                    },
                    "breakage_settings": {
                        "enabled": breakage.enabled,
                        "contact_regularization": breakage.contact_regularization,
                        "clutch_axial_compliance": breakage.clutch_axial_compliance,
                        "clutch_radial_compliance": breakage.clutch_radial_compliance,
                        "clutch_tangential_compliance": (
                            breakage.clutch_tangential_compliance
                        ),
                        "friction_coefficient": breakage.friction_coefficient,
                        "preloaded_force_n": breakage.preloaded_force,
                        "slack_fraction_warn": breakage.slack_fraction_warn,
                        "slack_fraction_b_floor": breakage.slack_fraction_b_floor,
                        "debug_dump": breakage.debug_dump,
                        "breakage_cooldown_time_s": breakage.breakage_cooldown_time,
                    },
                    "robot": {
                        "position_rad": self.robot.get_joint_positions().tolist(),
                        "velocity_rad_s": self.robot.get_joint_velocities().tolist(),
                        "effort_nm": self.robot.get_measured_joint_efforts().tolist(),
                        "command_position_rad": None
                        if robot_action is None or robot_action.joint_positions is None
                        else np.asarray(robot_action.joint_positions).tolist(),
                    },
                    "gripper": {
                        "position_rad": self.gripper.get_joint_positions().tolist(),
                        "velocity_rad_s": self.gripper.get_joint_velocities().tolist(),
                        "effort_nm": self.gripper.get_measured_joint_efforts().tolist(),
                        "command_position_rad": None
                        if gripper_action is None
                        or gripper_action.joint_positions is None
                        else float(gripper_action.joint_positions[gripper_index]),
                    },
                    "tool_pose_world": {
                        "position_m": tool[:3, 3].tolist(),
                        "orientation_wxyz": rot_matrices_to_quats(
                            tool[:3, :3]
                        ).tolist(),
                    },
                    "tool_target_world": self.tool_target,
                    "part_poses_world": {
                        path: {
                            "position_m": transform[:3, 3].tolist(),
                            "orientation_wxyz": rot_matrices_to_quats(
                                transform[:3, :3]
                            ).tolist(),
                        }
                        for path, transform in transforms.items()
                    },
                    "placements": placements,
                    "simulation_contacts": contacts,
                }
            )
            + "\n"
        )
        self.output.flush()

    def finish(self, status: str) -> None:
        """Close the run and unsubscribe from physics callbacks.

        Args:
            status: Completion or interruption status written to the log.
        """
        if self.output.closed:
            return
        if self.world.physics_callback_exists("ur5e_run_recorder"):
            self.world.remove_physics_callback("ur5e_run_recorder")
        self.output.write(json.dumps({"kind": "end", "status": status}) + "\n")
        self.output.close()

    def on_task_done(self, task: asyncio.Task[None]) -> None:
        """Close the log if the experiment task ends without completing.

        Args:
            task: Finished experiment task.
        """
        self.finish("interrupted_or_failed")
