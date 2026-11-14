#!/usr/bin/env python3
"""Run the UR5e simulation test cases, one Isaac Sim process per case.

Run from the repository root with the project interpreter:

    .venv/bin/python experiments/ur5e_lego/scripts/run_ur5e_cases.py
    .venv/bin/python experiments/ur5e_lego/scripts/run_ur5e_cases.py --case C01 C05

Each case launches `run_ur5e_case.sh`, and its recording and console output are
kept in `outputs/ur5e_lego/`. `--publish` also copies the compressed recording and
filtered console log to `docs/evidence/`. The suite manifest records the commit,
environment, asset hashes and per-case results. Positions are meters and angles
are radians unless a field name says otherwise; recorded poses are simulated.
This never connects to a robot.
"""

import gzip
import json
import math
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from argparse import ArgumentParser
from datetime import datetime, timezone
from hashlib import file_digest
from importlib.metadata import version
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from experiments.lab_assets import lab_asset, lab_asset_dir  # noqa: E402

CASES = ROOT / "experiments/ur5e_lego/configs/cases"
ASSET_REFERENCE = ROOT / "experiments/ur5e_lego/assets/lab_assets_sha256.json"
EVIDENCE = ROOT / "experiments/ur5e_lego/docs/evidence"
OUTPUT = ROOT / "outputs/ur5e_lego"
FAILURE_OUTCOMES = (
    ("did not complete the press", "rejected"),
    ("connected at", "wrong_stud"),
    ("detached", "detached"),
    ("Tool target not reached", "target_not_reached"),
    ("off center", "grasp_off_center"),
    ("not retained", "dropped"),
)
EVIDENCE_CLASSES = {
    "contact_physics": (
        "PhysX rigid-body simulation. The RG2 holds a brick through friction and a "
        "force-limited joint drive; no attachment joint is created at grasp. Brick "
        "contact forces and motion are solver outputs, not sensor readings."
    ),
    "simulated_connection": (
        "Stud insertion is not simulated. The brick is pressed against the support; "
        "when gap, tilt, yaw, position and force thresholds pass, the assembly "
        "checker snaps it to the nearest stud position and adds a weld constraint, "
        "closing the recorded pre-connection gap. Breakage checking is off."
    ),
    "ground_truth_corrections": (
        "The controller reads exact simulated brick and support poses: at the grasp, "
        "when planning placement from the held brick's true pose, and to correct the "
        "held brick's XY before descent. Inputs can disable the last two (C09, C10, "
        "C13), but source and support poses stay ground truth in every case. Hardware "
        "has no such measurement."
    ),
    "other_assumptions": (
        "Fixed lab scene and rigid base at the USD pose; kinematic baseplate; RMPflow "
        "commands applied to simulated joint drives with no controller latency, "
        "backlash or calibration error; invisible tabletop collider; simulated "
        "mass and friction are not measured from real bricks."
    ),
}
LIMITATIONS = [
    "Simulation only. These results do not establish physical robot performance.",
    "Each case ran once in a fixed scene: this is not a success rate.",
    "Injected errors are commanded offsets, not measured real-world error models.",
    "Thresholds of 2 mm, 5 degrees and 1 N are simulator settings, not brick "
    "tolerances measured on hardware.",
    "Simulated force values are not calibrated to physical force.",
]


def main() -> None:
    """Run the selected cases and write the suite manifest."""
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--case", nargs="*", help="Case IDs; default all.")
    parser.add_argument(
        "--timeout", type=float, default=420.0, help="Seconds per case."
    )
    parser.add_argument("--publish", action="store_true", help="Copy into evidence.")
    parser.add_argument(
        "launcher_args", nargs="*", help="Launcher arguments after `--`."
    )
    args = parser.parse_args()

    selected = args.case or sorted(path.stem for path in CASES.glob("*.json"))
    suite_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    directory = OUTPUT / "cases" / suite_id
    directory.mkdir(parents=True)

    reference = json.loads(ASSET_REFERENCE.read_text())
    assets = {}
    for name in (
        "robot/ur5e.usd",
        "gripper/husarion_rg2/rg2_gripper_fixed.usd",
        "gripper/QuickChanger.usd",
        "workstation/vention.usd",
    ):
        path = lab_asset(name)
        with path.open("rb") as stream:
            digest = file_digest(stream, "sha256").hexdigest()
        assets[name] = {
            "path": str(path),
            "sha256": digest,
            "matches_reference": digest == reference[name],
        }
    native = next((ROOT / "python/bricksim").glob("core.*.so"))
    with native.open("rb") as stream:
        native_digest = file_digest(stream, "sha256").hexdigest()
    suite = {
        "suite_id": suite_id,
        "source": "simulation",
        "commit": subprocess.run(
            ["git", "-C", str(ROOT), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip(),
        "tracked_changes_at_start": bool(
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(ROOT),
                    "status",
                    "--porcelain",
                    "--untracked-files=no",
                ],
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip()
        ),
        "environment": {
            "isaacsim": version("isaacsim"),
            "isaacsim_kernel": version("isaacsim-kernel"),
            "native_sha256": native_digest,
            "lab_asset_dir": str(lab_asset_dir()),
            "launcher_args": args.launcher_args,
            "lab_assets": assets,
        },
        "evidence_classes": EVIDENCE_CLASSES,
        "limitations": LIMITATIONS,
    }
    results: list[dict] = []
    manifest = directory / "ur5e-cases-suite.json"

    for case_id in selected:
        config_path = CASES / f"{case_id}.json"
        config = json.loads(config_path.read_text())
        console = directory / f"{case_id}-console.log"
        print(f"== {case_id}: {config['case']['title']}", flush=True)
        started = time.monotonic()
        with console.open("w") as stream:
            process = subprocess.Popen(
                [
                    str(ROOT / "experiments/ur5e_lego/scripts/run_ur5e_case.sh"),
                    str(config_path.relative_to(ROOT)),
                    "--",
                    *args.launcher_args,
                ],
                stdout=stream,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            timed_out = False
            finished_at = None
            # Kit's shutdown can outlast the experiment, so stop it once finished.
            while process.poll() is None:
                time.sleep(1.0)
                text = console.read_text(errors="replace")
                if finished_at is None and "UR5e case finished" in text:
                    finished_at = time.monotonic()
                if (finished_at and time.monotonic() - finished_at > 20.0) or (
                    time.monotonic() - started > args.timeout
                ):
                    timed_out = finished_at is None
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait()
        wall_s = time.monotonic() - started
        text = console.read_text(errors="replace")
        recording_match = re.search(r"UR5e recording: (\S+)", text)
        failure_match = re.search(r"UR5e case failure: (.*)", text)
        failure = failure_match.group(1).strip() if failure_match else None

        status = "not_recorded"
        phases = []
        placements = []
        peak_force: dict[str, float] = {}
        duration_s = None
        samples = 0
        created_utc = None
        if recording_match:
            previous = {}
            for line in Path(recording_match.group(1)).open():
                record = json.loads(line)
                if record["kind"] == "metadata":
                    created_utc = record["created_utc"]
                elif record["kind"] == "end":
                    status = record["status"]
                elif record["kind"] == "sample":
                    samples += 1
                    duration_s = record["simulation_elapsed_s"]
                    if not phases or phases[-1] != record["phase"]:
                        phases.append(record["phase"])
                    for contact in record["simulation_contacts"]:
                        key = contact["hole_path"]
                        peak_force[key] = max(
                            peak_force.get(key, 0.0), -contact["projected_force_n"]
                        )
                    for placement in record["placements"]:
                        before = previous.get(placement["hole_path"])
                        if placement["connected"] and not (
                            before and before["connected"]
                        ):
                            placement["pre_connection_error_m"] = (
                                before["position_error_m"] if before else None
                            )
                            placement["pre_connection_yaw_rad"] = (
                                before["yaw_error_rad"] if before else None
                            )
                        elif before:
                            placement["pre_connection_error_m"] = before.get(
                                "pre_connection_error_m"
                            )
                            placement["pre_connection_yaw_rad"] = before.get(
                                "pre_connection_yaw_rad"
                            )
                        previous[placement["hole_path"]] = placement
            placements = [
                {
                    "brick": index,
                    "target_offset_studs": placement["target_offset_studs"],
                    "connected": placement["connected"],
                    "connected_offset_studs": placement["connected_offset_studs"],
                    "connected_yaw_index": placement["connected_yaw"],
                    "pre_connection_lateral_mm": None
                    if not placement.get("pre_connection_error_m")
                    else 1000.0 * math.hypot(*placement["pre_connection_error_m"][:2]),
                    "pre_connection_gap_mm": None
                    if not placement.get("pre_connection_error_m")
                    else 1000.0 * placement["pre_connection_error_m"][2],
                    "pre_connection_yaw_deg": None
                    if placement.get("pre_connection_yaw_rad") is None
                    else math.degrees(placement["pre_connection_yaw_rad"]),
                    "final_lateral_error_mm": 1000.0
                    * math.hypot(*placement["position_error_m"][:2]),
                    "final_gap_mm": 1000.0 * placement["position_error_m"][2],
                    "final_yaw_deg": math.degrees(placement["yaw_error_rad"]),
                    "peak_simulated_contact_force_n": peak_force.get(
                        placement["hole_path"]
                    ),
                }
                for index, placement in enumerate(previous.values(), start=1)
            ]

        if status == "completed":
            observed = "connected"
        elif timed_out or not recording_match:
            observed = "harness_failure"
        else:
            observed = next(
                (
                    outcome
                    for needle, outcome in FAILURE_OUTCOMES
                    if needle in (failure or "")
                ),
                "other_failure",
            )
        expected = config["case"]["expected_outcome"]
        console_lines = [
            line
            for line in text.splitlines()
            if line.startswith("UR5e ") or "Error" in line and "RuntimeError" in line
        ]
        result = {
            **config["case"],
            "inputs": {
                key: config[key]
                for key in config
                if key not in ("case", "experiment_name")
            },
            "config_file": str(config_path.relative_to(ROOT)),
            "commit": suite["commit"],
            "suite_id": suite_id,
            "created_utc": created_utc,
            "observed_outcome": observed,
            "as_predicted": observed == expected,
            "recorded_status": status,
            "failure": failure,
            "simulation_duration_s": duration_s,
            "wall_time_s": wall_s,
            "samples": samples,
            "last_phase": phases[-1] if phases else None,
            "placements": placements,
            "run_log": f"ur5e-case-{case_id}-run.jsonl.gz",
            "console_log": f"ur5e-case-{case_id}-console.txt",
        }
        results.append(result)
        manifest.write_text(json.dumps({**suite, "cases": results}, indent=2) + "\n")
        (directory / result["console_log"]).write_text("\n".join(console_lines) + "\n")
        if recording_match:
            with Path(recording_match.group(1)).open("rb") as source:
                with gzip.GzipFile(
                    directory / result["run_log"], "wb", compresslevel=9, mtime=0
                ) as target:
                    shutil.copyfileobj(source, target)
        print(
            f"   expected={expected} observed={observed} status={status} "
            f"wall={wall_s:.0f}s failure={failure}",
            flush=True,
        )

    as_predicted = all(case["as_predicted"] for case in results)
    if args.publish:
        # A video beside an older log would be mislabeled as this run's recording.
        for case_id in selected:
            (EVIDENCE / f"ur5e-case-{case_id}-run.mp4").unlink(missing_ok=True)
        for path in directory.glob("ur5e-case*"):
            if path.name != manifest.name:
                shutil.copy2(path, EVIDENCE / path.name)
        # Keep published cases that this invocation did not rerun.
        published = EVIDENCE / manifest.name
        if published.exists():
            kept = [
                case
                for case in json.loads(published.read_text())["cases"]
                if case["id"] not in selected
            ]
            results = sorted([*kept, *results], key=lambda case: case["id"])
        published.write_text(json.dumps({**suite, "cases": results}, indent=2) + "\n")
    print(f"Suite manifest: {manifest}", flush=True)
    sys.exit(0 if as_predicted else 1)


if __name__ == "__main__":
    main()
