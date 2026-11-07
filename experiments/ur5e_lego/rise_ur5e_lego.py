"""Pick and place a brick with the lab UR5e on its fixed workstation rail."""

import asyncio
import json
import math
from os import environ
from pathlib import Path
from runpy import run_path

import numpy as np
from carb.events import IEvent
from experiments.ur5e_lego.recording import RunRecorder
from isaacsim.core.api import World
from isaacsim.core.prims import SingleArticulation, SingleXFormPrim
from isaacsim.core.utils.numpy.rotations import rot_matrices_to_quats
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
from bricksim.core import allocate_brick_part
from bricksim.utils.physics_step import wait_for_physics_step


async def move_to(
    world: World,
    robot: SingleArticulation,
    robot_base: SingleXFormPrim,
    rmpflow: RmpFlow,
    policy: ArticulationMotionPolicy,
    recorder: RunRecorder,
    position: np.ndarray,
    orientation: np.ndarray,
) -> None:
    """Move the UR5e tool frame to a world pose, or fail on timeout.

    Args:
        world: Active simulation world.
        robot: UR5e articulation to command.
        robot_base: Transform of the complete robot base.
        rmpflow: UR5e motion policy.
        policy: Adapter between the policy and articulation.
        recorder: Active experiment recorder.
        position: Target world position in meters, shape (3,).
        orientation: Target world orientation as a wxyz quaternion, shape (4,).

    Returns:
        None. Raises RuntimeError if the target is not reached in 15 seconds.
    """
    recorder.tool_target = {
        "position_m": position.tolist(),
        "orientation_wxyz": orientation.tolist(),
    }
    elapsed = 0.0
    settled = 0.0
    end_effector = rmpflow.get_end_effector_as_prim()
    while elapsed < 15.0:
        dt = await wait_for_physics_step(world)
        elapsed += dt
        base_position, base_orientation = robot_base.get_world_pose()
        rmpflow.set_robot_base_pose(base_position, base_orientation)
        rmpflow.set_end_effector_target(position, orientation)
        rmpflow.update_world()
        robot.apply_action(policy.get_next_articulation_action(dt))
        actual_position, actual_orientation = end_effector.get_world_pose()
        position_error = np.linalg.norm(actual_position - position)
        dot = abs(float(np.dot(actual_orientation, orientation)))
        rotation_error = 2.0 * math.acos(min(dot, 1.0))
        if position_error < 0.005 and rotation_error < 0.1:
            settled += dt
            if settled >= 0.25:
                return
        else:
            settled = 0.0
    raise RuntimeError(
        f"Tool target not reached: position error {position_error:.4f} m, "
        f"rotation error {rotation_error:.3f} rad"
    )


async def set_gripper(
    world: World, gripper: SingleArticulation, joint: Usd.Prim, target: float
) -> None:
    """Command the RG2 actuated joint and allow its coupled fingers to settle.

    Args:
        world: Active simulation world.
        gripper: Separate RG2 articulation.
        joint: USD prim for the actuated revolute joint.
        target: Joint target in radians, within the RG2's physical limits.

    Returns:
        None. The force-limited drive can stop early when it contacts a brick.
    """
    if not -0.45 <= target <= 1.0:
        raise ValueError("RG2 target is outside its joint limits")
    # USD angular drives use degrees; articulation actions use radians.
    UsdPhysics.DriveAPI(joint, "angular").GetTargetPositionAttr().Set(
        math.degrees(target)
    )
    index = gripper.get_dof_index("rg2_gripper_joint")
    gripper.apply_action(
        ArticulationAction(
            joint_positions=np.array([target]), joint_indices=np.array([index])
        )
    )
    elapsed = 0.0
    while elapsed < 2.0:
        elapsed += await wait_for_physics_step(world)
    applied = gripper.get_applied_action()
    if applied is None or applied.joint_positions is None:
        raise RuntimeError("Gripper position target is unavailable")
    position = gripper.get_joint_positions()[index]
    velocity = gripper.get_joint_velocities()[index]
    usd_target = UsdPhysics.DriveAPI(joint, "angular").GetTargetPositionAttr().Get()
    print(
        f"UR5e LEGO: gripper command_rad={target:.4f} "
        f"physics_target_rad={applied.joint_positions[index]:.4f} "
        f"usd_target_deg={usd_target:.4f} "
        f"joint_rad={position:.4f} velocity_rad_s={velocity:.4f}",
        flush=True,
    )


async def main() -> None:
    """Create an isolated lab workstation scene and run one brick transfer.

    Positions are meters, angular joint commands are radians, and quaternions
    are wxyz. Press Play after the scene is prepared to begin the motion.

    Returns:
        None. The simulation pauses after a successful release; Stop resets it.
    """
    root = Path(__file__).resolve().parents[2]
    config = json.loads(
        (root / "experiments/ur5e_lego/configs/ur5e_lego.json").read_text()
    )
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
    colors = [(201, 26, 9), (0, 85, 191), (35, 120, 65)]
    brick_paths = []
    for (x, y), color in zip(config["brick_positions_xy_m"], colors, strict=True):
        brick_paths.append(
            allocate_brick_part((2, 4, 3), color, -1, pos=(x, y, table_z + 0.001))
        )

    robot = SingleArticulation(
        prim_path="/World/UR5e", name="ur5e", reset_xform_properties=False
    )
    gripper = SingleArticulation(
        prim_path="/World/RG2_Gripper", name="rg2", reset_xform_properties=False
    )
    world.scene.add(robot)
    world.scene.add(gripper)
    await world.reset_async()
    recorder = RunRecorder(
        root,
        "transfer",
        world,
        robot,
        gripper,
        brick_paths,
        [],
        {
            "scene": config,
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
    brick = SingleXFormPrim(
        prim_path=brick_paths[0], name="target_brick", reset_xform_properties=False
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
        ):
            recorder.finish("stopped")
            print("UR5e LEGO: resetting scene", flush=True)
            kit_runner.rerun()

    await world.pause_async()
    world.add_timeline_callback("ur5e_lego_reset", on_stop)
    print(f"UR5e LEGO: tabletop z={table_z:.6f} m; press Play to begin", flush=True)
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
    for link in ("rg2_l_finger_link", "rg2_r_finger_link"):
        collisions = stage.GetPrimAtPath(f"/World/RG2_Gripper/{link}/collisions")
        meshes = [prim for prim in Usd.PrimRange(collisions) if prim.IsA(UsdGeom.Mesh)]
        if not meshes:
            raise RuntimeError(f"No collision mesh found for {link}")
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
    await set_gripper(world, gripper, joint, 1.0)

    # Grasp-frame columns: approach downward, close across the brick's x side.
    target_grasp = np.eye(4)
    target_grasp[:3, :3] = np.array([[0, 1, 0], [0, 0, -1], [-1, 0, 0]])
    source_xy = config["brick_positions_xy_m"][0]
    destination_xy = config["destination_xy_m"]
    # Keep the furthest finger collision point 1 mm above the tabletop.
    grasp_z = table_z + tip_offset + 0.001
    print(f"UR5e LEGO: fingertip offset={tip_offset:.4f} m", flush=True)
    for phase, x, y, z in (
        ("approach", *source_xy, grasp_z + 0.10),
        ("grasp", *source_xy, grasp_z),
        ("lift", *source_xy, grasp_z + 0.10),
        ("transfer", *destination_xy, grasp_z + 0.10),
        ("place", *destination_xy, grasp_z),
        ("retreat", *destination_xy, grasp_z + 0.10),
    ):
        recorder.phase = phase
        recorder.brick_index = 1
        if phase == "lift":
            recorder.phase = "grasp_close"
            for moment in ("before", "after"):
                if moment == "after":
                    print("UR5e LEGO: closing gripper", flush=True)
                    await set_gripper(world, gripper, joint, -0.45)
                brick_position, _ = brick.get_world_pose()
                finger_bounds = []
                bounds_cache = UsdGeom.BBoxCache(
                    Usd.TimeCode.Default(),
                    [UsdGeom.Tokens.default_, UsdGeom.Tokens.guide],
                    False,
                    True,
                )
                for link in ("rg2_l_finger_link", "rg2_r_finger_link"):
                    collision = stage.GetPrimAtPath(
                        f"/World/RG2_Gripper/{link}/collisions"
                    )
                    finger_box = bounds_cache.ComputeWorldBound(
                        collision
                    ).ComputeAlignedBox()
                    finger_bounds.append(
                        [list(finger_box.GetMin()), list(finger_box.GetMax())]
                    )
                gripper_position = gripper.get_joint_positions()[
                    gripper.get_dof_index("rg2_gripper_joint")
                ]
                print(
                    f"UR5e LEGO: {moment} closing "
                    f"brick_m={brick_position.tolist()} "
                    f"finger_bounds_m={finger_bounds} "
                    f"joint_rad={gripper_position:.4f}",
                    flush=True,
                )
            recorder.phase = phase
        if phase == "retreat":
            recorder.phase = "release"
            print("UR5e LEGO: releasing brick", flush=True)
            await set_gripper(world, gripper, joint, 1.0)
            recorder.phase = phase
        target_grasp[:3, 3] = (x, y, z)
        target_tool = target_grasp @ np.linalg.inv(tool_to_grasp)
        print(f"UR5e LEGO: {phase}", flush=True)
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
        brick_position, _ = brick.get_world_pose()
        if phase in ("lift", "transfer") and brick_position[2] < table_z + 0.04:
            raise RuntimeError(f"Brick was not retained during {phase}")

    elapsed = 0.0
    while elapsed < 2.0:
        elapsed += await wait_for_physics_step(world)
    brick_position, _ = brick.get_world_pose()
    if (
        np.linalg.norm(brick_position[:2] - destination_xy) > 0.025
        or abs(brick_position[2] - table_z) > 0.01
    ):
        raise RuntimeError(f"Brick did not settle at the destination: {brick_position}")
    print(f"UR5e LEGO: pick and place succeeded at {brick_position}", flush=True)
    recorder.finish("completed")
    await world.pause_async()
