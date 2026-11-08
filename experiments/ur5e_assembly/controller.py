"""Assemble bricks on a baseplate with the lab UR5e."""

import asyncio
import json
import math
from datetime import datetime, timezone
from os import environ
from pathlib import Path
from runpy import run_path

import numpy as np
from carb.events import IEvent
from experiments.ur5e_assembly.clearance import (
    FingerFaces,
    neighbours,
    outer_faces,
    release_opening,
)
from experiments.ur5e_assembly.environment import is_set, setting
from experiments.ur5e_assembly.gripper_contacts import GripperContactMonitor
from experiments.ur5e_lego.recording import RunRecorder
from experiments.ur5e_lego.rise_ur5e_lego import move_to, set_gripper
from isaacsim.core.api import World
from isaacsim.core.prims import SingleArticulation, SingleXFormPrim
from isaacsim.core.utils.numpy.rotations import (
    quats_to_rot_matrices,
    rot_matrices_to_quats,
)
from isaacsim.core.utils.stage import create_new_stage_async, get_current_stage
from isaacsim.core.utils.types import ArticulationAction
from isaacsim.core.utils.viewports import set_camera_view
from isaacsim.robot_motion.motion_generation import ArticulationMotionPolicy, RmpFlow
from isaacsim.robot_motion.motion_generation.interface_config_loader import (
    load_supported_motion_policy_config,
)
from isaacsim.storage.native import get_assets_root_path
from omni.timeline import TimelineEventType
from omni.ui import Workspace
from omni.usd import get_context
from pxr import Gf, Sdf, Usd, UsdGeom, UsdLux, UsdPhysics, UsdUtils

from bricksim import kit_runner
from bricksim.core import (
    AssemblyThresholds,
    allocate_brick_part,
    compute_connection_transform,
    get_assembly_debug_infos,
    get_assembly_thresholds,
    get_breakage_thresholds,
    get_connection_utilization,
    lookup_physics_connection,
    set_assembly_thresholds,
    set_breakage_thresholds,
)
from bricksim.utils.physics_step import wait_for_physics_step

# Tunable controller settings: environment variable -> (key in the structure
# config's "controller" block, default). An environment variable wins, then the
# structure's own setting, then the default, so a structure can carry what it
# needs to build and a sweep can still override it.
SETTINGS = {
    "ASSEMBLY_REQUIRED_FORCE_N": ("required_force_n", 1.0),
    "ASSEMBLY_PRESS_DEPTH_M": ("press_depth_m", 0.0005),
    "ASSEMBLY_PRESS_HOLD_S": ("press_hold_s", 0.05),
    "ASSEMBLY_RELEASE_RAMP_S": ("release_ramp_s", 1.0),
    "ASSEMBLY_TIP_CLEARANCE_M": ("tip_clearance_m", 0.003),
    "ASSEMBLY_RELEASE_MARGIN_M": ("release_margin_m", 0.002),
    "ASSEMBLY_RELEASE_MIN_CLEARANCE_M": ("release_min_clearance_m", 0.001),
    "ASSEMBLY_RELEASE_LIFT_M": ("release_lift_m", 0.0),
}


def controller_settings(assembly: dict) -> dict[str, float]:
    """Resolve the tunable settings for one structure.

    Args:
        assembly: The structure config; its optional "controller" block holds
            per-structure values keyed as in `SETTINGS`.

    Returns:
        Config key to value, with environment variables taking precedence.
    """
    tuning = assembly.get("controller", {})
    unknown = set(tuning) - {key for key, _ in SETTINGS.values()}
    if unknown:
        raise ValueError(f"Unknown controller settings: {sorted(unknown)}")
    return {
        key: float(setting(name.removeprefix("ASSEMBLY_"), ""))
        if is_set(name.removeprefix("ASSEMBLY_"))
        else float(tuning.get(key, default))
        for name, (key, default) in SETTINGS.items()
    }


class UtilizationRecorder(RunRecorder):
    """Run recorder that also logs each live connection's load utilization.

    Utilization is the breakage solver's load over capacity per connection (above
    1 means the clutch is overloaded; -1 means not evaluated, e.g. breakage off).
    Rows go to `outputs/ur5e_assembly/utilization-<experiment>-<time>.csv` as
    `elapsed_s,phase,brick_index,connection_path,utilization`.
    """

    def __init__(self, root: Path, experiment: str, *args) -> None:
        """Open the CSV; remaining arguments are those of `RunRecorder`.

        Args:
            root: Repository root.
            experiment: Experiment name used in the CSV file name.
            *args: World, robot, gripper, part paths, placements and config.
        """
        super().__init__(root, experiment, *args)
        self.placement_pairs = [(s, b) for s, b, _ in args[4]]
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        out = root / "outputs/ur5e_assembly"
        out.mkdir(parents=True, exist_ok=True)
        self.utilization_file = (out / f"utilization-{experiment}-{stamp}.csv").open(
            "w"
        )
        self.utilization_file.write(
            "elapsed_s,phase,brick_index,connection_path,utilization\n"
        )

    def sample(self, dt: float) -> None:
        """Write the base sample, then one utilization row per live connection.

        Args:
            dt: Physics step duration in seconds.
        """
        super().sample(dt)
        for support_path, brick_path in self.placement_pairs[: self.brick_index]:
            info = lookup_physics_connection(support_path, 1, brick_path, 0)
            if info is not None:
                path = f"/World/managed/Conns/Conn_{info.physics_csid}"
                self.utilization_file.write(
                    f"{self.elapsed_s:.4f},{self.phase},{self.brick_index},{path},"
                    f"{get_connection_utilization(path):.4f}\n"
                )
        self.utilization_file.flush()


async def main(
    assembly_config: str = "experiments/ur5e_structures/dog.json",
    autoplay: bool = False,
) -> None:
    """Create an isolated lab scene and assemble bricks on a baseplate.

    Positions are meters, angular joint commands are radians, and quaternions
    are wxyz. Press Play after the scene is prepared to begin the motion.

    The configuration can inject controlled errors, all zero or unset by default:
    `source_yaw_rad` rotates each loose brick about world Z; `grasp_error_xy_m` adds
    a world XY error to the commanded grasp; `placement_error_xy_m` and
    `placement_error_yaw_rad` add a world XY error and a yaw about the target brick
    center to the commanded placement. `ground_truth_xy_correction` set to false
    disables the correction of the held brick's XY from simulated poses.
    `held_brick_pose_assumed_from_grasp` set to true plans the placement without the
    grasp error, as a controller that cannot measure the held brick would.

    Args:
        assembly_config: Repository-relative path to the placement configuration.
        autoplay: Start the timeline after the scene is prepared.

    Returns:
        None. The simulation pauses after assembly; Stop resets the scene.
    """
    root = Path(__file__).resolve().parents[2]
    config = json.loads(
        (root / "experiments/ur5e_lego/configs/ur5e_lego.json").read_text()
    )
    assembly = json.loads((root / assembly_config).read_text())
    from experiments.ur5e_assembly.validate import validate

    validate(assembly)
    mcp_root = (
        root
        / Path(environ.get("ISAAC_MCP_ROOT", config["isaac_mcp_root"])).expanduser()
    ).resolve()
    resolve_asset_uri = run_path(str(mcp_root / "exts/ur5e-dt/ur5e_dt/asset_cache.py"))[
        "resolve_uri"
    ]
    workstation = Sdf.Layer.OpenAsAnonymous(str(root / config["workstation_scene"]))
    if workstation is None:
        raise RuntimeError("Could not load the workstation scene")
    UsdUtils.ModifyAssetPaths(workstation, resolve_asset_uri)

    if World.instance() is not None:
        World.clear_instance()
    await create_new_stage_async()
    stage = get_current_stage()
    # The session layer is stronger than the experiment-owned workstation.
    stage.GetRootLayer().subLayerPaths.append(workstation.identifier)
    stage.SetEditTarget(stage.GetSessionLayer())
    stage.GetPrimAtPath("/World/defaultGroundPlane").SetActive(False)

    assets_root = get_assets_root_path()
    if not assets_root:
        raise RuntimeError("Isaac Sim assets root is unavailable")
    room_parent = UsdGeom.Xform.Define(stage, "/World/SimpleRoom")
    room_parent.AddTranslateOp().Set(Gf.Vec3d(0.0, 0.0, -0.11))
    room = UsdGeom.Xform.Define(stage, "/World/SimpleRoom/Room").GetPrim()
    room.GetReferences().AddReference(
        assets_root + "/Isaac/Environments/Simple_Room/simple_room.usd"
    )
    if not room.GetChildren():
        raise RuntimeError("Simple Room asset could not be loaded")
    for child in room.GetChildren():
        if child.GetName().lower().startswith("table_low"):
            child.SetActive(False)
    for prim in Usd.PrimRange(room):
        if prim.HasAPI(UsdPhysics.CollisionAPI):
            UsdPhysics.CollisionAPI(prim).GetCollisionEnabledAttr().Set(False)
        if prim.HasAPI(UsdPhysics.RigidBodyAPI):
            UsdPhysics.RigidBodyAPI(prim).GetRigidBodyEnabledAttr().Set(False)

    table = stage.GetPrimAtPath(config["table_mesh"])
    if not table.IsValid():
        raise RuntimeError(f"Table mesh not found: {config['table_mesh']}")
    bounds = (
        UsdGeom.BBoxCache(Usd.TimeCode.Default(), [UsdGeom.Tokens.default_])
        .ComputeWorldBound(table)
        .ComputeAlignedBox()
    )
    low, high = bounds.GetMin(), bounds.GetMax()
    table_z = float(high[2])
    support = UsdGeom.Cube.Define(stage, "/World/LegoTableSupport")
    support.CreateSizeAttr(1.0)
    support.AddTranslateOp().Set((low + high) / 2.0)
    support.AddScaleOp().Set(Gf.Vec3f(*(high - low)))
    support.CreateVisibilityAttr().Set(UsdGeom.Tokens.invisible)
    UsdPhysics.CollisionAPI.Apply(support.GetPrim())
    UsdLux.DomeLight.Define(stage, "/World/LegoFillLight").CreateIntensityAttr(600.0)

    world = World(
        stage_units_in_meters=1.0,
        physics_dt=1 / 120,
        rendering_dt=1 / 60,
        backend="numpy",
        device="cpu",
        physics_prim_path="/physicsScene",
    )
    if not isinstance(world, World):
        raise RuntimeError("Expected an Isaac Sim World")
    await world.initialize_simulation_context_async()
    plate_xy = assembly["baseplate_xy_m"]
    plate_path = allocate_brick_part(
        (20, 20, 1), (155, 161, 157), -1, pos=(*plate_xy, table_z)
    )
    UsdPhysics.RigidBodyAPI(
        stage.GetPrimAtPath(plate_path)
    ).GetKinematicEnabledAttr().Set(True)
    colors = assembly["brick_colors"]
    dimensions = assembly["brick_dimensions"]
    brick_positions = assembly.get(
        "brick_positions_xy_m", config["brick_positions_xy_m"]
    )
    source_yaw = assembly.get("source_yaw_rad", 0.0)
    source_rotation = (math.cos(source_yaw / 2), 0.0, 0.0, math.sin(source_yaw / 2))
    brick_paths = []
    for (x, y), color, dimension in zip(
        brick_positions, colors, dimensions, strict=True
    ):
        brick_paths.append(
            allocate_brick_part(
                tuple(dimension),
                tuple(color),
                -1,
                rot=source_rotation,
                pos=(x, y, table_z + 0.001),
            )
        )

    robot = SingleArticulation(
        prim_path="/World/UR5e", name="ur5e", reset_xform_properties=False
    )
    gripper = SingleArticulation(
        prim_path="/World/RG2_Gripper", name="rg2", reset_xform_properties=False
    )
    world.scene.add(robot)
    world.scene.add(gripper)
    # Any gripper contact with a brick other than the one being handled is logged;
    # it fails the run unless ASSEMBLY_GRIPPER_CONTACT=log.
    contact_monitor = GripperContactMonitor(
        stage, "/World/RG2_Gripper", plate_path.rsplit("/", 1)[0], brick_paths
    )
    fail_on_gripper_contact = setting("GRIPPER_CONTACT", "fail") != "log"
    await world.reset_async()
    supports = assembly.get("support_bricks", [None] * len(brick_paths))
    for index, support_index in enumerate(supports, start=1):
        if support_index is not None and not 0 <= support_index < index - 1:
            raise ValueError(f"Brick {index} has an invalid support: {support_index}")
    placements = [
        (
            plate_path if support_index is None else brick_paths[support_index],
            brick_path,
            tuple(offset),
        )
        for brick_path, offset, support_index in zip(
            brick_paths, assembly["placement_offsets"], supports, strict=True
        )
    ]
    experiment = assembly.get(
        "experiment_name",
        "stack" if any(index is not None for index in supports) else "baseplate",
    )
    recorder = UtilizationRecorder(
        root,
        experiment,
        world,
        robot,
        gripper,
        [plate_path, *brick_paths],
        placements,
        {
            "scene": config,
            "assembly": assembly,
            "resolved_lab_assets": str(mcp_root / "exts/ur5e-dt"),
            "isaac_assets_root": assets_root,
        },
    )
    contact_monitor.recorder = recorder
    task = asyncio.current_task()
    if task is None:
        raise RuntimeError("Experiment task is unavailable")
    task.add_done_callback(recorder.on_task_done)
    set_camera_view(
        eye=np.array([-0.3, -1.1, 0.55]),
        target=np.array([-0.33, -0.33, 0.06]),
    )
    for window in ("Stage", "Property", "Console", "BrickSim Settings"):
        Workspace.get_window(window).visible = True
    Workspace.get_window("BrickSim Settings").focus()
    get_context().get_selection().set_selected_prim_paths(["/World/UR5e"], True)
    robot_base = SingleXFormPrim(
        prim_path="/World/UR5e", name="ur5e_base", reset_xform_properties=False
    )
    rmpflow = RmpFlow(**load_supported_motion_policy_config("UR5e", "RMPflow"))
    policy = ArticulationMotionPolicy(robot, rmpflow)
    joint = stage.GetPrimAtPath("/World/RG2_Gripper/joints/rg2_gripper_joint")
    if not joint.IsValid():
        raise RuntimeError("RG2 actuated joint was not found")

    target = kit_runner.current_target()

    def on_stop(event: IEvent) -> None:
        """Reload this experiment when the timeline stops.

        Args:
            event: Timeline Stop event.
        """
        if (
            event.type == int(TimelineEventType.STOP)
            and kit_runner.current_target() == target
            and not autoplay
        ):
            recorder.finish("stopped")
            print("UR5e baseplate: resetting scene", flush=True)
            kit_runner.rerun()

    await world.pause_async()
    world.add_timeline_callback("ur5e_baseplate_reset", on_stop)
    print(
        f"UR5e baseplate: tabletop z={table_z:.6f} m; press Play to begin", flush=True
    )
    if autoplay:
        await world.play_async()
    await set_gripper(world, gripper, joint, 1.0)

    # USD matrices use row-vector convention; transpose for column vectors.
    cache = UsdGeom.XformCache(Usd.TimeCode.Default())
    tool = stage.GetPrimAtPath("/World/UR5e/wrist_3_link/flange/tool0")
    tool_world = np.array(cache.GetLocalToWorldTransform(tool)).T
    finger_points = []
    for link, marker in (
        ("rg2_l_finger_link", [0.0379, -0.01898, 0.0, 1.0]),
        ("rg2_r_finger_link", [0.0379, 0.01898, 0.0, 1.0]),
    ):
        prim = stage.GetPrimAtPath(f"/World/RG2_Gripper/{link}")
        finger_transform = np.array(cache.GetLocalToWorldTransform(prim)).T
        finger_points.append((finger_transform @ marker)[:3])
    hand = stage.GetPrimAtPath("/World/RG2_Gripper/rg2_hand_link")
    hand_position = np.array(cache.GetLocalToWorldTransform(hand)).T[:3, 3]
    center = (finger_points[0] + finger_points[1]) / 2
    closing = finger_points[1] - finger_points[0]
    closing /= np.linalg.norm(closing)
    approach = center - hand_position
    approach -= closing * np.dot(approach, closing)
    approach /= np.linalg.norm(approach)
    grasp_world = np.eye(4)
    grasp_world[:3, :3] = np.column_stack(
        (approach, closing, np.cross(approach, closing))
    )
    grasp_world[:3, 3] = center
    tool_to_grasp = np.linalg.inv(tool_world) @ grasp_world

    # The RG2 linkage moves the tips along the approach axis while closing.
    # Measure the fully closed geometry in free air relative to the open frame.
    await set_gripper(world, gripper, joint, -0.45)
    index = gripper.get_dof_index("rg2_gripper_joint")
    if gripper.get_joint_positions()[index] > -0.40:
        raise RuntimeError("RG2 failed to close in free air")
    cache = UsdGeom.XformCache(Usd.TimeCode.Default())
    closed_tool_world = np.array(cache.GetLocalToWorldTransform(tool)).T
    closed_reference = closed_tool_world @ tool_to_grasp
    tip_offset = 0.0
    finger_centers = []
    for link in ("rg2_l_finger_link", "rg2_r_finger_link"):
        collisions = stage.GetPrimAtPath(f"/World/RG2_Gripper/{link}/collisions")
        meshes = [prim for prim in Usd.PrimRange(collisions) if prim.IsA(UsdGeom.Mesh)]
        if not meshes:
            raise RuntimeError(f"No collision mesh found for {link}")
        lateral_min = float("inf")
        lateral_max = float("-inf")
        for mesh in meshes:
            points = np.asarray(UsdGeom.Mesh(mesh).GetPointsAttr().Get())
            transform = np.array(cache.GetLocalToWorldTransform(mesh)).T
            world_points = (
                transform @ np.column_stack((points, np.ones(len(points)))).T
            ).T[:, :3]
            projected = (world_points - closed_reference[:3, 3]) @ closed_reference[
                :3, 0
            ]
            tip_offset = max(tip_offset, float(np.max(projected)))
            lateral = (world_points - closed_reference[:3, 3]) @ closed_reference[:3, 2]
            lateral_min = min(lateral_min, float(np.min(lateral)))
            lateral_max = max(lateral_max, float(np.max(lateral)))
        finger_centers.append((lateral_min + lateral_max) / 2.0)
    lateral_offset = float(np.mean(finger_centers))

    # Finger faces along the closing axis against the RG2 angle, in free air and in
    # the grasp frame (columns: approach, closing, width): the release opening is
    # chosen from these so the fingers free the brick without reaching neighbours.
    finger_profile = []
    finger_half_width = 0.0
    for angle in (-0.45, -0.4, -0.35, -0.3, -0.25, -0.2, -0.1, 0.0, 0.2, 0.5, 1.0):
        UsdPhysics.DriveAPI(joint, "angular").GetTargetPositionAttr().Set(
            math.degrees(angle)
        )
        gripper.apply_action(
            ArticulationAction(
                joint_positions=np.array([angle]), joint_indices=np.array([index])
            )
        )
        elapsed = 0.0
        while elapsed < 0.5:
            elapsed += await wait_for_physics_step(world)
        cache = UsdGeom.XformCache(Usd.TimeCode.Default())
        grasp_now = np.array(cache.GetLocalToWorldTransform(tool)).T @ tool_to_grasp
        finger_points_local = {}
        for link in ("rg2_l_finger_link", "rg2_r_finger_link"):
            collisions = stage.GetPrimAtPath(f"/World/RG2_Gripper/{link}/collisions")
            local = []
            for mesh in Usd.PrimRange(collisions):
                if not mesh.IsA(UsdGeom.Mesh):
                    continue
                points = np.asarray(UsdGeom.Mesh(mesh).GetPointsAttr().Get())
                transform = np.array(cache.GetLocalToWorldTransform(mesh)).T
                world_points = (
                    transform @ np.column_stack((points, np.ones(len(points)))).T
                ).T[:, :3]
                local.append((world_points - grasp_now[:3, 3]) @ grasp_now[:3, :3])
            finger_points_local[link] = np.vstack(local)
            finger_half_width = max(
                finger_half_width, float(np.abs(finger_points_local[link][:, 2]).max())
            )
        left = finger_points_local["rg2_l_finger_link"]
        right = finger_points_local["rg2_r_finger_link"]
        finger_profile.append(
            FingerFaces(
                float(gripper.get_joint_positions()[index]),
                float(left[:, 1].max()),
                float(right[:, 1].min()),
                outer_faces(left, -1),
                outer_faces(right, 1),
            )
        )
    finger_profile.sort(key=lambda faces: faces.angle)
    # Outer faces over the lowest 10 mm of the fingers, where neighbours are met.
    summary = []
    for faces in finger_profile:
        left_tip = faces.left_outer[~np.isnan(faces.left_outer)][-5:].min()
        right_tip = faces.right_outer[~np.isnan(faces.right_outer)][-5:].max()
        summary.append(
            f"{faces.angle:.2f}: inner {faces.left_inner * 1000:.1f}/"
            f"{faces.right_inner * 1000:.1f}, tip outer {left_tip * 1000:.1f}/"
            f"{right_tip * 1000:.1f}"
        )
    print(f"UR5e baseplate: finger profile (rad, mm) {'; '.join(summary)}", flush=True)
    await set_gripper(world, gripper, joint, 1.0)

    # Grasp-frame columns: approach downward, close across each brick's x side.
    target_grasp = np.eye(4)
    target_grasp[:3, :3] = np.array([[0, 1, 0], [0, 0, -1], [-1, 0, 0]])
    # ASSEMBLY_TIP_CLEARANCE_M: fingertip height above the held brick's bottom, which
    # keeps the tips clear of the support's top and studs while seating.
    settings = controller_settings(assembly)
    print(f"UR5e baseplate: controller settings {json.dumps(settings)}", flush=True)
    grasp_z = table_z + tip_offset + settings["tip_clearance_m"]
    # Assembly check: seat within 1 mm and 2 degrees (tighter than the 2 mm and 5
    # degrees of the baseline). A required force above 1 N makes the press harder
    # and, with breakage on, overloads the joints below (see RESULTS.md).
    strict = AssemblyThresholds()
    strict.distance_tolerance = 0.001
    strict.max_penetration = 0.005
    strict.z_angle_tolerance = math.radians(2.0)
    strict.required_force = settings["required_force_n"]
    strict.yaw_tolerance = math.radians(2.0)
    strict.position_tolerance = 0.001
    set_assembly_thresholds(strict)
    # Full BrickSim model: connections can break under load unless ASSEMBLY_BREAKAGE=0.
    breakage = get_breakage_thresholds()
    breakage.enabled = setting("BREAKAGE", "1") == "1"
    set_breakage_thresholds(breakage)
    print(f"UR5e baseplate: breakage enabled={breakage.enabled}", flush=True)
    print(
        f"UR5e baseplate: fingertip offset={tip_offset:.4f} m; "
        f"finger center offset={lateral_offset:.4f} m; "
        f"assembly force threshold={get_assembly_thresholds().required_force:.2f} N",
        flush=True,
    )
    end_effector = rmpflow.get_end_effector_as_prim()
    total = len(brick_paths)
    grasp_error_xy = np.array(assembly.get("grasp_error_xy_m", [0.0, 0.0]))
    placement_error_xy = np.array(assembly.get("placement_error_xy_m", [0.0, 0.0]))
    placement_error_yaw = assembly.get("placement_error_yaw_rad", 0.0)
    press_depth_m = settings["press_depth_m"]
    freeze_on_connection = setting("FREEZE_ON_CONNECTION", "1") == "1"
    release_ramp_s = settings["release_ramp_s"]
    press_hold_s = settings["press_hold_s"]
    placement_yaws = assembly.get("placement_yaws", [0] * len(brick_paths))
    grasp_offsets = assembly.get("grasp_offsets_m", [[0.0, 0.0]] * len(brick_paths))
    for index, (brick_path, offset, support_index) in enumerate(
        zip(brick_paths, assembly["placement_offsets"], supports, strict=True), start=1
    ):
        support_path = (
            plate_path if support_index is None else brick_paths[support_index]
        )
        support = SingleXFormPrim(
            prim_path=support_path,
            name=f"assembly_support_{index}",
            reset_xform_properties=False,
        )
        brick = SingleXFormPrim(
            prim_path=brick_path,
            name=f"assembly_brick_{index}",
            reset_xform_properties=False,
        )
        recorder.brick_index = index
        recorder.phase = "approach"
        source_position, source_orientation = brick.get_world_pose()
        grasp_offset = (
            quats_to_rot_matrices(np.asarray(source_orientation))
            @ np.array([*grasp_offsets[index - 1], 0.0])
        )[:2]
        if np.any(grasp_offset):
            print(
                f"UR5e baseplate: brick {index}/{total} grasp offset "
                f"m={grasp_offset.tolist()}",
                flush=True,
            )
        print(f"UR5e baseplate: brick {index}/{total} approach", flush=True)
        for height in (grasp_z + 0.10, grasp_z):
            target_grasp[:3, 3] = (
                *(source_position[:2] + grasp_error_xy + grasp_offset),
                height,
            )
            target_grasp[:3, 3] -= target_grasp[:3, 2] * lateral_offset
            target_tool = target_grasp @ np.linalg.inv(tool_to_grasp)
            await move_to(
                world,
                robot,
                robot_base,
                rmpflow,
                policy,
                recorder,
                target_tool[:3, 3],
                rot_matrices_to_quats(target_tool[:3, :3]),
            )
        print(f"UR5e baseplate: brick {index}/{total} grasp", flush=True)
        recorder.phase = "grasp"
        await set_gripper(world, gripper, joint, -0.45)
        bounds_cache = UsdGeom.BBoxCache(
            Usd.TimeCode.Default(),
            [UsdGeom.Tokens.default_, UsdGeom.Tokens.guide],
            False,
            True,
        )
        finger_centers = []
        for link in ("rg2_l_finger_link", "rg2_r_finger_link"):
            collisions = stage.GetPrimAtPath(f"/World/RG2_Gripper/{link}/collisions")
            bounds = bounds_cache.ComputeWorldBound(collisions).ComputeAlignedBox()
            finger_centers.append(
                (np.array(bounds.GetMin()) + np.array(bounds.GetMax())) / 2.0
            )
        brick_position, _ = brick.get_world_pose()
        center_error = float(
            np.linalg.norm(
                np.mean(finger_centers, axis=0)[:2] - brick_position[:2] - grasp_offset
            )
        )
        print(
            f"UR5e baseplate: brick {index}/{total} "
            f"grasp center error={center_error:.4f} m",
            flush=True,
        )
        if center_error > 0.003:
            raise RuntimeError(
                f"Brick {index} grasp is off center by {center_error:.4f} m"
            )
        recorder.phase = "lift"
        target_grasp[2, 3] = grasp_z + 0.10
        target_tool = target_grasp @ np.linalg.inv(tool_to_grasp)
        await move_to(
            world,
            robot,
            robot_base,
            rmpflow,
            policy,
            recorder,
            target_tool[:3, 3],
            rot_matrices_to_quats(target_tool[:3, :3]),
        )
        brick_position, brick_orientation = brick.get_world_pose()
        if brick_position[2] < table_z + 0.04:
            raise RuntimeError(f"Brick {index} was not retained during lift")
        # Plan as if the brick sits where the grasp was intended, not where it is.
        if assembly.get("held_brick_pose_assumed_from_grasp", False):
            brick_position = brick_position.copy()
            brick_position[:2] += grasp_error_xy

        # Poses are column-vector transforms; quaternions are wxyz.
        support_position, support_orientation = support.get_world_pose()
        relative_orientation, relative_position = compute_connection_transform(
            support_path, 1, brick_path, 0, tuple(offset), placement_yaws[index - 1]
        )
        tool_position, tool_orientation = end_effector.get_world_pose()
        transforms = []
        for position, orientation in (
            (support_position, support_orientation),
            (relative_position, relative_orientation),
            (brick_position, brick_orientation),
            (tool_position, tool_orientation),
        ):
            transform = np.eye(4)
            transform[:3, :3] = quats_to_rot_matrices(np.asarray(orientation))
            transform[:3, 3] = position
            transforms.append(transform)
        target_tool = (
            transforms[0] @ transforms[1] @ np.linalg.inv(transforms[2]) @ transforms[3]
        )
        target_orientation = rot_matrices_to_quats(target_tool[:3, :3])
        print(
            f"UR5e baseplate: brick {index}/{total} transfer support={support_path} "
            f"offset={offset} "
            f"tool_target_m={target_tool[:3, 3].tolist()}",
            flush=True,
        )
        recorder.phase = "transfer"
        await move_to(
            world,
            robot,
            robot_base,
            rmpflow,
            policy,
            recorder,
            target_tool[:3, 3] + np.array([0.0, 0.0, 0.10]),
            target_orientation,
        )
        prepress_position = target_tool[:3, 3] + np.array([0.0, 0.0, 0.025])
        await move_to(
            world,
            robot,
            robot_base,
            rmpflow,
            policy,
            recorder,
            prepress_position,
            target_orientation,
        )
        recorder.phase = "alignment"
        # Correct the held brick's world XY error while still above the support.
        support_position, support_orientation = support.get_world_pose()
        brick_position, _ = brick.get_world_pose()
        desired_brick_position = support_position + quats_to_rot_matrices(
            np.asarray(support_orientation)
        ) @ np.asarray(relative_position)
        correction = desired_brick_position[:2] - brick_position[:2]
        if not assembly.get("ground_truth_xy_correction", True):
            correction = np.zeros(2)
        target_tool[:2, 3] += correction
        cos_yaw, sin_yaw = math.cos(placement_error_yaw), math.sin(placement_error_yaw)
        yaw_error = np.array(
            [[cos_yaw, -sin_yaw, 0.0], [sin_yaw, cos_yaw, 0.0], [0.0, 0.0, 1.0]]
        )
        target_tool[:3, 3] = desired_brick_position + yaw_error @ (
            target_tool[:3, 3] - desired_brick_position
        )
        target_tool[:3, :3] = yaw_error @ target_tool[:3, :3]
        target_tool[:2, 3] += placement_error_xy
        target_orientation = rot_matrices_to_quats(target_tool[:3, :3])
        prepress_position = target_tool[:3, 3] + np.array([0.0, 0.0, 0.025])
        print(
            f"UR5e baseplate: brick {index}/{total} prepress XY correction "
            f"m={correction.tolist()}",
            flush=True,
        )
        await move_to(
            world,
            robot,
            robot_base,
            rmpflow,
            policy,
            recorder,
            prepress_position,
            target_orientation,
        )
        print(f"UR5e baseplate: brick {index}/{total} press", flush=True)
        recorder.phase = "press"
        press_position = target_tool[:3, 3] - np.array([0.0, 0.0, press_depth_m])
        elapsed = 0.0
        held = 0.0
        peak_force = 0.0
        connection = None
        frozen_target = None
        while elapsed < 10.0:
            dt = await wait_for_physics_step(world)
            elapsed += dt
            descent = min(elapsed / 2.0, 1.0)
            target_position = prepress_position + descent * (
                press_position - prepress_position
            )
            if frozen_target is not None:
                target_position = frozen_target
            recorder.tool_target = {
                "position_m": target_position.tolist(),
                "orientation_wxyz": target_orientation.tolist(),
            }
            base_position, base_orientation = robot_base.get_world_pose()
            rmpflow.set_robot_base_pose(base_position, base_orientation)
            rmpflow.set_end_effector_target(target_position, target_orientation)
            rmpflow.update_world()
            robot.apply_action(policy.get_next_articulation_action(dt))
            for info in get_assembly_debug_infos():
                if info.stud_path == support_path and info.hole_path == brick_path:
                    peak_force = max(peak_force, -float(info.projected_force))
            connection = lookup_physics_connection(support_path, 1, brick_path, 0)
            if (
                connection is not None
                and freeze_on_connection
                and frozen_target is None
            ):
                # Stop descending once seated so the press force stops growing.
                frozen_target = target_position.copy()
            if connection is not None and (descent >= 1.0 or frozen_target is not None):
                held += dt
                if held >= press_hold_s:
                    break
            elif held > 0.0:
                raise RuntimeError(f"Brick {index} detached during the press")
        if connection is None or held < press_hold_s:
            diagnostics = [
                (
                    info.relative_distance,
                    info.projected_force,
                    info.position_error,
                    info.yaw_error,
                    info.tilt,
                    info.grid_pos_snapped,
                )
                for info in get_assembly_debug_infos()
                if info.stud_path == support_path and info.hole_path == brick_path
            ]
            brick_position, _ = brick.get_world_pose()
            tool_position, _ = end_effector.get_world_pose()
            raise RuntimeError(
                f"Brick {index} did not complete the press: "
                f"connected={connection is not None}, held={held:.2f} s, "
                f"brick={brick_position}, "
                f"tool={tool_position}, target={press_position}, "
                f"debug={diagnostics[:3]}"
            )
        print(
            f"UR5e baseplate: brick {index}/{total} connected "
            f"offset={connection.offset} yaw={connection.yaw}; "
            f"press held={held:.2f} s; peak contact force={peak_force:.2f} N",
            flush=True,
        )
        recorder.phase = "release"
        # Open the fingers gradually with the arm held at its current pose: a
        # one-step open releases the stored press load as an impulse, and any arm
        # motion while the fingers still grip (lifting, or still converging on the
        # press target) loads the new joint. Stop short of any neighbouring brick.
        gripper_index = gripper.get_dof_index("rg2_gripper_joint")
        opening_start = float(gripper.get_joint_positions()[gripper_index])
        cache = UsdGeom.XformCache(Usd.TimeCode.Default())
        grasp_now = np.array(cache.GetLocalToWorldTransform(tool)).T @ tool_to_grasp
        boxes_cache = UsdGeom.BBoxCache(
            Usd.TimeCode.Default(), [UsdGeom.Tokens.default_]
        )
        boxes = []
        for other_path in brick_paths:
            if other_path == brick_path:
                continue
            box = boxes_cache.ComputeWorldBound(
                stage.GetPrimAtPath(other_path)
            ).ComputeAlignedBox()
            boxes.append(np.array([box.GetMin(), box.GetMax()]))
        nearby = neighbours(
            boxes,
            grasp_now[:3, 3],
            grasp_now[:3, 1],
            grasp_now[:3, 2],
            finger_half_width,
        )
        nearest = ", ".join(
            f"{'left' if n.side < 0 else 'right'} {n.distance * 1000:.1f} mm"
            for n in sorted(nearby, key=lambda n: n.distance)[:2]
        )
        # As wide as the neighbours allow (fully open in free space): a narrow
        # opening keeps the pads on the brick longer and lets the lift drag it.
        release = release_opening(
            finger_profile,
            opening_start,
            nearby,
            target_clearance=float("inf"),
            min_clearance=settings["release_min_clearance_m"],
            margin=settings["release_margin_m"],
        )
        if release is None:
            raise RuntimeError(
                f"No gripper clearance to release brick {index}: nearest bricks "
                f"{nearest or 'none'}"
            )
        release_angle, release_clearance = release
        print(
            f"UR5e baseplate: brick {index}/{total} release opening="
            f"{release_angle:.3f} rad (clearance {release_clearance * 1000:.1f} mm; "
            f"nearest bricks {nearest or 'none'})",
            flush=True,
        )
        # Ease off the press before letting go: hold the tool `release_lift_m`
        # above where the press left it while the fingers open.
        unload_position, _ = end_effector.get_world_pose()
        unload_position = unload_position + np.array(
            [0.0, 0.0, settings["release_lift_m"]]
        )
        elapsed = 0.0
        while elapsed < release_ramp_s:
            dt = await wait_for_physics_step(world)
            elapsed += dt
            opening = opening_start + (release_angle - opening_start) * min(
                elapsed / release_ramp_s, 1.0
            )
            UsdPhysics.DriveAPI(joint, "angular").GetTargetPositionAttr().Set(
                math.degrees(opening)
            )
            gripper.apply_action(
                ArticulationAction(
                    joint_positions=np.array([opening]),
                    joint_indices=np.array([gripper_index]),
                )
            )
            base_position, base_orientation = robot_base.get_world_pose()
            rmpflow.set_robot_base_pose(base_position, base_orientation)
            rmpflow.set_end_effector_target(unload_position, target_orientation)
            rmpflow.update_world()
            robot.apply_action(policy.get_next_articulation_action(dt))
        # Lift, then open fully above the structure if a neighbour limited the
        # opening.
        recorder.phase = "retreat"
        await move_to(
            world,
            robot,
            robot_base,
            rmpflow,
            policy,
            recorder,
            target_tool[:3, 3] + np.array([0.0, 0.0, 0.10]),
            target_orientation,
        )
        await set_gripper(world, gripper, joint, 1.0)
        if contact_monitor.contacts and fail_on_gripper_contact:
            other, step, phase = contact_monitor.contacts[0]
            raise RuntimeError(
                f"Gripper touched {other} during {phase} of brick {step}"
            )
        if index == len(brick_paths):
            elapsed = 0.0
            while elapsed < 2.0:
                elapsed += await wait_for_physics_step(world)
        for placed_index, placed_path in enumerate(brick_paths[:index], start=1):
            placed_support = supports[placed_index - 1]
            placed_support_path = (
                plate_path if placed_support is None else brick_paths[placed_support]
            )
            placed = lookup_physics_connection(placed_support_path, 1, placed_path, 0)
            if placed is None:
                raise RuntimeError(f"Brick {placed_index} detached from its support")
            expected = tuple(assembly["placement_offsets"][placed_index - 1])
            if (
                tuple(placed.offset) != expected
                or placed.yaw != placement_yaws[placed_index - 1]
            ):
                raise RuntimeError(
                    f"Brick {placed_index} connected at {placed.offset}, "
                    f"yaw {placed.yaw}; "
                    f"expected {expected}, yaw {placement_yaws[placed_index - 1]}"
                )
        print(f"UR5e baseplate: {index}/{total} bricks secured", flush=True)

    print(
        f"UR5e baseplate: gripper contacts with other bricks: "
        f"{len(contact_monitor.contacts)}",
        flush=True,
    )
    print(
        f"UR5e baseplate: assembly succeeded; all {total} bricks connected", flush=True
    )
    recorder.finish("completed")
    await world.pause_async()
