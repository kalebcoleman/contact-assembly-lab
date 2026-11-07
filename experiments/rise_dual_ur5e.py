"""Load two provisional UR5e models and record a shared-object scene baseline."""

import argparse
import asyncio
import json
import math
import platform
import subprocess
from datetime import datetime, timezone
from hashlib import sha256
from importlib.metadata import version
from pathlib import Path


async def main() -> None:
    """Validate settings, create the scene in Kit, and record a bounded baseline.

    Arguments are read from sys.argv: --config selects a JSON configuration,
    --check validates without starting Isaac Sim, and --quit exits Kit after
    recording. Positions use meters, angles radians, and quaternions wxyz.

    Returns:
        None. Run artifacts are written under outputs/rise/.
    """
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config", type=Path, default=root / "research/configs/dual_ur5e.json"
    )
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--quit", action="store_true")
    args = parser.parse_args()
    config_text = args.config.read_text()
    config = json.loads(config_text)
    if not isinstance(config["asset_path"], str) or not config["asset_path"]:
        raise ValueError("asset_path must be a nonempty USD path or URL")
    for key in ("physics_dt_s", "record_duration_s"):
        if not math.isfinite(config[key]) or config[key] <= 0:
            raise ValueError(f"{key} must be finite and positive")
    if config["record_duration_s"] < config["physics_dt_s"]:
        raise ValueError("record_duration_s must span at least one physics step")
    for key in ("static_friction", "dynamic_friction"):
        if not math.isfinite(config[key]) or config[key] < 0:
            raise ValueError(f"{key} must be finite and nonnegative")
    if config["static_friction"] < config["dynamic_friction"]:
        raise ValueError("static_friction must be >= dynamic_friction")
    if len(config["robots"]) != 2:
        raise ValueError("This baseline requires exactly two robots")
    names = [robot["name"] for robot in config["robots"]]
    if len(set(names)) != 2 or any(not name.isidentifier() for name in names):
        raise ValueError("Robot names must be unique Python/USD identifiers")
    for robot in config["robots"]:
        for key, size in (
            ("position_m", 3),
            ("orientation_wxyz", 4),
            ("joint_positions_rad", 6),
        ):
            values = robot[key]
            if len(values) != size or not all(math.isfinite(x) for x in values):
                raise ValueError(f"{robot['name']}.{key} needs {size} finite values")
        if not math.isclose(
            sum(x * x for x in robot["orientation_wxyz"]), 1.0, abs_tol=1e-6
        ):
            raise ValueError("Robot quaternions must have unit norm (wxyz)")
    obj = config["object"]
    if len(obj["size_m"]) != 3 or any(
        not math.isfinite(x) or x <= 0 for x in obj["size_m"]
    ):
        raise ValueError("object.size_m needs three finite positive dimensions")
    if len(obj["position_m"]) != 3 or not all(
        math.isfinite(x) for x in obj["position_m"]
    ):
        raise ValueError("object.position_m needs three finite values")
    if not math.isfinite(obj["mass_kg"]) or obj["mass_kg"] <= 0:
        raise ValueError("object.mass_kg must be finite and positive")
    print(f"RISE: configuration valid: {args.config}", flush=True)
    if args.check:
        return

    import numpy as np
    import omni.kit.app
    from isaacsim.core.api import World
    from isaacsim.core.api.materials import PhysicsMaterial
    from isaacsim.core.api.objects import DynamicCuboid, FixedCuboid
    from isaacsim.core.prims import SingleArticulation
    from isaacsim.core.utils.stage import (
        add_reference_to_stage,
        create_new_stage_async,
        get_current_stage,
    )
    from isaacsim.core.utils.types import ArticulationAction
    from isaacsim.core.utils.viewports import set_camera_view
    from isaacsim.storage.native import get_assets_root_path_async
    from pxr import Gf, UsdGeom, UsdLux, UsdPhysics

    from bricksim.utils.physics_step import wait_for_physics_step

    run_dir = (
        root / "outputs/rise" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    )
    run_dir.mkdir(parents=True, exist_ok=False)
    (run_dir / "config.json").write_text(config_text)
    asset_path = config["asset_path"]
    if asset_path.startswith("Isaac/"):
        asset_path = (await get_assets_root_path_async()) + "/" + asset_path
    elif "://" not in asset_path:
        asset_path = str((root / asset_path).resolve())
    manifest = {
        "status": "started",
        "experiment_id": config["experiment_id"],
        "purpose": "scene integration only; no grasp or coordinated manipulation",
        "config_sha256": sha256(config_text.encode()).hexdigest(),
        "asset_url": asset_path,
        "asset_content_pinned": False,
        "git_head": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=root, text=True
        ).strip(),
        "git_status": subprocess.check_output(
            ["git", "status", "--short"], cwd=root, text=True
        ),
        "python": platform.python_version(),
        "packages": {p: version(p) for p in ("isaacsim", "isaaclab", "numpy", "torch")},
        "physics_backend": "PhysX, CPU dynamics; Kit World defaults",
        "units": "meters, kilograms, seconds, radians; quaternions wxyz",
        "seed": None,
        "randomization": "none",
    }
    manifest_path = run_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2))
    print(f"RISE: loading {asset_path}; output={run_dir}", flush=True)
    if World.instance() is not None:
        World.clear_instance()
    await create_new_stage_async()
    world = World(
        stage_units_in_meters=1.0,
        physics_dt=config["physics_dt_s"],
        rendering_dt=1 / 60,
        backend="numpy",
        device="cpu",
    )
    if not isinstance(world, World):
        raise RuntimeError(
            "Expected an Isaac Sim World, not a plain simulation context"
        )
    await world.initialize_simulation_context_async()
    world.get_physics_context().set_gravity(-9.81)
    stage = get_current_stage()
    UsdLux.DomeLight.Define(stage, "/World/Light").CreateIntensityAttr(1000)
    material = PhysicsMaterial(
        prim_path="/World/ContactMaterial",
        static_friction=config["static_friction"],
        dynamic_friction=config["dynamic_friction"],
        restitution=0.0,
    )
    table = FixedCuboid(
        prim_path="/World/Table",
        name="table",
        position=np.array([0, 0, 0.2]),
        scale=np.array([2.2, 1.4, 0.4]),
        size=1.0,
        color=np.array([0.3, 0.35, 0.4]),
        physics_material=material,
    )
    world.scene.add(table)
    shared = DynamicCuboid(
        prim_path="/World/SharedObject",
        name="shared_object",
        position=np.array(obj["position_m"]),
        scale=np.array(obj["size_m"]),
        size=1.0,
        mass=obj["mass_kg"],
        color=np.array([0.9, 0.45, 0.05]),
        physics_material=material,
    )
    world.scene.add(shared)
    robots = []
    for entry in config["robots"]:
        path = f"/World/{entry['name']}"
        add_reference_to_stage(usd_path=asset_path, prim_path=path)
        # Articulation APIs resolve to root_joint for this asset. Position the
        # robot's parent Xform, rather than transforming only that joint prim.
        root_joint_prim = stage.GetPrimAtPath(f"{path}/root_joint")
        if not root_joint_prim.IsA(UsdPhysics.FixedJoint):
            raise ValueError(
                f"Expected the audited fixed root joint at {path}/root_joint"
            )
        xform = UsdGeom.Xformable(stage.GetPrimAtPath(path))
        xform.ClearXformOpOrder()
        xform.AddTranslateOp().Set(Gf.Vec3d(*entry["position_m"]))
        q = entry["orientation_wxyz"]
        xform.AddOrientOp(UsdGeom.XformOp.PrecisionDouble).Set(
            Gf.Quatd(q[0], Gf.Vec3d(*q[1:]))
        )
        robot = SingleArticulation(
            prim_path=path,
            name=entry["name"],
            reset_xform_properties=False,
        )
        world.scene.add(robot)
        robot.set_joints_default_state(positions=np.array(entry["joint_positions_rad"]))
        robots.append(robot)
    await world.reset_async()
    for robot, entry in zip(robots, config["robots"], strict=True):
        if robot.num_dof != 6:
            raise ValueError(f"{robot.name}: expected 6 DOFs, got {robot.num_dof}")
        robot.apply_action(
            ArticulationAction(joint_positions=np.array(entry["joint_positions_rad"]))
        )
    manifest["joint_names"] = {robot.name: robot.dof_names for robot in robots}
    manifest["usd_layers"] = [layer.identifier for layer in stage.GetUsedLayers()]
    stage.GetRootLayer().Export(str(run_dir / "scene.usda"))
    set_camera_view(eye=np.array([2.3, 2.3, 1.8]), target=np.array([0, 0, 0.7]))
    await world.play_async()
    start_time = world.current_time
    print("RISE: two six-DOF UR5e arms initialized; recording baseline", flush=True)
    with (run_dir / "states.jsonl").open("w") as trace:
        while world.current_time - start_time < config["record_duration_s"]:
            await wait_for_physics_step(world)
            joints = {
                robot.name: robot.get_joint_positions().tolist() for robot in robots
            }
            position, orientation = shared.get_world_pose()
            if not np.isfinite(position).all() or not all(
                np.isfinite(q).all() for q in joints.values()
            ):
                raise RuntimeError("Non-finite simulation state")
            if np.max(np.abs(position)) > 5 or any(
                np.max(
                    np.abs(
                        np.array(joints[entry["name"]]) - entry["joint_positions_rad"]
                    )
                )
                > 0.25
                for entry in config["robots"]
            ):
                manifest["status"] = "failed_scene_bounds"
                manifest_path.write_text(json.dumps(manifest, indent=2))
                await world.pause_async()
                raise RuntimeError(
                    "Scene baseline exceeded 5 m workspace or 0.25 rad hold error"
                )
            trace.write(
                json.dumps(
                    {
                        "sim_time_s": world.current_time,
                        "joints_rad": joints,
                        "object_position_m": position.tolist(),
                        "object_orientation_wxyz": orientation.tolist(),
                    }
                )
                + "\n"
            )
    await world.pause_async()
    manifest["status"] = "completed_scene_baseline"
    manifest["elapsed_sim_s"] = world.current_time - start_time
    manifest_path.write_text(json.dumps(manifest, indent=2))
    print(f"RISE: baseline complete; evidence={run_dir}", flush=True)
    if args.quit:
        omni.kit.app.get_app().post_quit()


if __name__ == "__main__":
    asyncio.run(main())
