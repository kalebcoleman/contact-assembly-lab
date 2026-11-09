"""Run every pending entry of a sweep definition once, in simulation.

A sweep definition (`sweeps/<name>.json`) holds the sweep `environment` (applied
to every run) and `runs`, each with a `label`, a `config` and its own
`environment` overrides. Runs without a `run` id are pending. Each one goes
through `experiments/ur5e_assembly/run_loop.sh --attempts 1`, then its run id (the new
`outputs/ur5e_assembly/<run>/` folder) is written back into the definition, so the
file records exactly which output belongs to which settings.

With `--capture`, the viewport is rendered to frames during the run
(`ASSEMBLY_CAPTURE_DIR`) and encoded to `.cache/videos/<sweep>/<label>.mp4` (1080p,
30 fps of simulated time); the frames are then deleted. The close-up stills
taken at the end of the run are kept beside the video as
`<label>_closeup_*.png`.

Summarize afterwards with `summarize_sweep.py`. This drives the simulator only;
it never connects to a robot.

    OMNI_KIT_ACCEPT_EULA=YES python3 -m experiments.ur5e_structures.run_sweep \
        experiments/ur5e_structures/sweeps/<name>.json [--capture] [--dry-run]

To reproduce a committed sweep, `--rerun <copy.json>` clears the run ids into
a copy and runs that; summarize the copy and compare it with the committed
summary. A display is needed (Kit runs windowed).
"""

import json
import os
import shutil
import signal
import subprocess
import time
from argparse import ArgumentParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RUNS = ROOT / "outputs/ur5e_assembly"
# The GPU is shared: wait for this much free memory before starting a run.
MIN_FREE_GPU_MB = 14000


def free_gpu_mb() -> int:
    """Return the free memory of the first GPU in MiB."""
    output = subprocess.run(
        ["nvidia-smi", "--query-gpu=memory.free", "--format=csv,noheader,nounits"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return int(output.split()[0])


def run_folders() -> set[str]:
    """Return the names of the run folders under `outputs/ur5e_assembly/`."""
    return {p.name for p in RUNS.iterdir() if p.is_dir()} if RUNS.exists() else set()


def run_once(config: str, environment: dict[str, str], log: Path) -> str:
    """Run one attempt and return its run id.

    The attempt runs in its own process group with stdin closed (a child that
    reads stdin would otherwise consume input meant for this script); the group
    is killed afterwards so no simulator process outlives the run.

    Args:
        config: Repository-relative structure config.
        environment: Full environment for the run.
        log: File receiving the loop's console output.

    Returns:
        The name of the run folder the attempt created.
    """
    before = run_folders()
    with log.open("w") as stream:
        process = subprocess.Popen(
            [
                "bash",
                "experiments/ur5e_assembly/run_loop.sh",
                "--attempts",
                "1",
                "--timeout",
                "900",
                "--config",
                config,
            ],
            cwd=ROOT,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=stream,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        process.wait()
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    created = sorted(run_folders() - before)
    if len(created) != 1:
        raise RuntimeError(f"Expected one new run folder, found {created}")
    return created[0]


def encode(frames: Path, video: Path) -> None:
    """Encode captured frames to an H.264 MP4 and delete the frames.

    Args:
        frames: Folder of `frame_%06d.png`.
        video: Output file.
    """
    video.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg",
            "-nostdin",
            "-loglevel",
            "error",
            "-y",
            "-framerate",
            "30",
            "-i",
            str(frames / "frame_%06d.png"),
            "-c:v",
            "libx264",
            "-preset",
            "slow",
            "-crf",
            "20",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            str(video),
        ],
        check=True,
    )
    shutil.rmtree(frames)


def main() -> None:
    """Run the pending entries of a sweep definition and record their run ids."""
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("sweep", type=Path, help="Sweep definition (JSON).")
    parser.add_argument("--capture", action="store_true", help="Record videos.")
    parser.add_argument("--dry-run", action="store_true", help="Only list runs.")
    parser.add_argument(
        "--rerun",
        type=Path,
        help="Copy the definition here with run ids, videos and media cleared, "
        "and run the copy (to reproduce a committed sweep).",
    )
    args = parser.parse_args()
    sweep = json.loads(args.sweep.read_text())
    if args.rerun:
        sweep["name"] = args.rerun.stem
        for run in sweep["runs"]:
            run.update(run=None, video=None, media=None)
        args.rerun.write_text(json.dumps(sweep, indent=2) + "\n")
        args.sweep = args.rerun
    for run in sweep["runs"]:
        if run.get("run"):
            continue
        environment = {
            **os.environ,
            **sweep.get("environment", {}),
            **run.get("environment", {}),
        }
        overrides = {**sweep.get("environment", {}), **run.get("environment", {})}
        print(f"== {run['label']} {run['config']} {overrides}", flush=True)
        if args.dry_run:
            continue
        frames = ROOT / ".cache/frames" / run["label"]
        if args.capture:
            shutil.rmtree(frames, ignore_errors=True)
            shutil.rmtree(frames.with_name(f"{frames.name}_stills"), ignore_errors=True)
            environment["ASSEMBLY_CAPTURE_DIR"] = str(frames)
        while free_gpu_mb() < MIN_FREE_GPU_MB:
            print("waiting for GPU memory", flush=True)
            time.sleep(30)
        run["run"] = run_once(
            run["config"], environment, ROOT / ".cache/sweep-current.log"
        )
        if args.capture and frames.exists():
            video = ROOT / ".cache/videos" / sweep["name"] / f"{run['label']}.mp4"
            encode(frames, video)
            run["video"] = str(video.relative_to(ROOT))
            stills = frames.with_name(f"{frames.name}_stills")
            if stills.exists():
                for still in sorted(stills.glob("*.png")):
                    still.replace(video.with_name(f"{run['label']}_{still.name}"))
                shutil.rmtree(stills)
        manifest = json.loads((RUNS / run["run"] / "manifest.json").read_text())
        print(f"{run['label']}: {manifest[0]['outcome']} {run['run']}", flush=True)
        # Record progress after every run, so an interrupted sweep can resume.
        args.sweep.write_text(json.dumps(sweep, indent=2) + "\n")


if __name__ == "__main__":
    main()
