"""Assemble bricks on a baseplate with the lab UR5e."""

import asyncio
import json
import math
from os import environ
from pathlib import Path
from runpy import run_path

import numpy as np
from carb.events import IEvent
from experiments.ur5e_lego.recording import RunRecorder
from experiments.ur5e_lego.rise_ur5e_lego import move_to, set_gripper

# Scene.add is annotated SingleXFormPrim but also registers SingleArticulation,
# so those calls carry ty ignores.
from isaacsim.core.api import World
from isaacsim.core.prims import SingleArticulation, SingleXFormPrim
from isaacsim.core.utils.numpy.rotations import (
    quats_to_rot_matrices,
    rot_matrices_to_quats,
)
from isaacsim.core.utils.stage import create_new_stage_async, get_current_stage
from isaacsim.core.utils.viewports import set_camera_view
from isaacsim.robot_motion.motion_generation import ArticulationMotionPolicy, RmpFlow
from isaacsim.robot_motion.motion_generation.interface_config_loader import (
    load_supported_motion_policy_config,
)
from isaacsim.storage.native import get_assets_root_path
from omni.timeline import TimelineEventType
from omni.ui import Workspace
from omni.usd import get_context

# Kit's pxr.UsdPhysics has no type stubs (Tf adds its members at import time),
# so its uses carry ty ignores.
from pxr import Gf, Sdf, Usd, UsdGeom, UsdLux, UsdPhysics, UsdUtils

from bricksim import kit_runner
from bricksim.core import (
    allocate_brick_part,
    compute_connection_transform,
    get_assembly_debug_infos,
    get_assembly_thresholds,
    lookup_physics_connection,
)
from bricksim.utils.physics_step import wait_for_physics_step


async def main(
    assembly_config: str = "experiments/ur5e_lego/configs/ur5e_baseplate.json",
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
        if prim.HasAPI(UsdPhysics.CollisionAPI):  # ty: ignore[unresolved-attribute]
            UsdPhysics.CollisionAPI(prim).GetCollisionEnabledAttr().Set(False)  # ty: ignore[unresolved-attribute]
        if prim.HasAPI(UsdPhysics.RigidBodyAPI):  # ty: ignore[unresolved-attribute]
            UsdPhysics.RigidBodyAPI(prim).GetRigidBodyEnabledAttr().Set(False)  # ty: ignore[unresolved-attribute]

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
    UsdPhysics.CollisionAPI.Apply(support.GetPrim())  # ty: ignore[unresolved-attribute]
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
    UsdPhysics.RigidBodyAPI(  # ty: ignore[unresolved-attribute]
        stage.GetPrimAtPath(plate_path)
    ).GetKinematicEnabledAttr().Set(True)
    colors = [(201, 26, 9), (0, 85, 191), (35, 120, 65), (242, 205, 55)]
    brick_positions = assembly.get(
        "brick_positions_xy_m", config["brick_positions_xy_m"]
    )
    source_yaw = assembly.get("source_yaw_rad", 0.0)
    source_rotation = (math.cos(source_yaw / 2), 0.0, 0.0, math.sin(source_yaw / 2))
    brick_paths = []
    for (x, y), color in zip(
        brick_positions, colors[: len(brick_positions)], strict=True
    ):
        brick_paths.append(
            allocate_brick_part(
                (2, 4, 3),
                color,
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
    world.scene.add(robot)  # ty: ignore[invalid-argument-type]
    world.scene.add(gripper)  # ty: ignore[invalid-argument-type]
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
    recorder = RunRecorder(
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
    task = asyncio.current_task()
    if task is None:
        raise RuntimeError("Experiment task is unavailable")
    task.add_done_callback(recorder.on_task_done)
    set_camera_view(
        eye=np.array([-0.3, -1.75, 0.7]),
        target=np.array([-0.3, -0.3, 0.05]),
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
    await set_gripper(world, gripper, joint, 1.0)

    # Grasp-frame columns: approach downward, close across each brick's x side.
    target_grasp = np.eye(4)
    target_grasp[:3, :3] = np.array([[0, 1, 0], [0, 0, -1], [-1, 0, 0]])
    # Raise the pads clear of adjacent studs when a brick reaches the plate.
    grasp_z = table_z + tip_offset + 0.003
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
        source_position, _ = brick.get_world_pose()
        print(f"UR5e baseplate: brick {index}/{total} approach", flush=True)
        for height in (grasp_z + 0.10, grasp_z):
            target_grasp[:3, 3] = (
                *(source_position[:2] + grasp_error_xy),
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
            np.linalg.norm(np.mean(finger_centers, axis=0)[:2] - brick_position[:2])
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
            support_path, 1, brick_path, 0, tuple(offset), 0
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
        press_position = target_tool[:3, 3] - np.array([0.0, 0.0, 0.0005])
        elapsed = 0.0
        held = 0.0
        peak_force = 0.0
        connection = None
        while elapsed < 10.0:
            dt = await wait_for_physics_step(world)
            elapsed += dt
            descent = min(elapsed / 2.0, 1.0)
            target_position = prepress_position + descent * (
                press_position - prepress_position
            )
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
            if connection is not None and descent >= 1.0:
                held += dt
                if held >= 1.0:
                    break
            elif held > 0.0:
                raise RuntimeError(f"Brick {index} detached during the press")
        if connection is None or held < 1.0:
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
        await set_gripper(world, gripper, joint, 1.0)
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
            if tuple(placed.offset) != expected or placed.yaw != 0:
                raise RuntimeError(
                    f"Brick {placed_index} connected at {placed.offset}, "
                    f"yaw {placed.yaw}; "
                    f"expected {expected}, yaw 0"
                )
        print(f"UR5e baseplate: {index}/{total} bricks secured", flush=True)

    print(
        f"UR5e baseplate: assembly succeeded; all {total} bricks connected", flush=True
    )
    recorder.finish("completed")
    await world.pause_async()
