"""Run bounded fresh-scene assembly attempts, stopping at the first failure."""

import json
import os
import signal
import subprocess
import sys
from argparse import ArgumentParser
from datetime import datetime, timezone
from pathlib import Path
from re import search


def main() -> None:
    """Run 1–5 attempts and save console output and explicit outcomes."""
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--attempts", type=int, choices=range(1, 6), default=1)
    parser.add_argument("--config", default="experiments/ur5e_structures/dog.json")
    parser.add_argument("--timeout", type=int, default=600)
    args = parser.parse_args()
    if not 1 <= args.timeout <= 900:
        parser.error("timeout must be 1–900 seconds")
    root = Path(__file__).resolve().parents[2]
    output = (
        root
        / "outputs/ur5e_assembly"
        / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    )
    output.mkdir(parents=True)
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(root / "python") + os.pathsep + str(root)
    environment["ASSEMBLY_CONFIG"] = args.config
    results = []
    for attempt in range(1, args.attempts + 1):
        log = output / f"attempt-{attempt}.txt"
        print(f"Attempt {attempt}/{args.attempts}: {log}", flush=True)
        with log.open("w") as stream:
            process = subprocess.Popen(
                [sys.executable, "-m", "bricksim", "experiments/ur5e_assembly/run.py"],
                cwd=root,
                env=environment,
                stdout=stream,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            try:
                code = process.wait(timeout=args.timeout)
                outcome = (
                    "completed"
                    if code == 0
                    and search(
                        r"assembly succeeded; all \d+ bricks connected", log.read_text()
                    )
                    else "failed"
                )
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait()
                code, outcome = process.returncode, "timeout"
            except BaseException:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
                raise
        results.append(
            {
                "attempt": attempt,
                "outcome": outcome,
                "returncode": code,
                "console": str(log),
                "simulation_only": True,
            }
        )
        (output / "manifest.json").write_text(json.dumps(results, indent=2) + "\n")
        print(f"Attempt {attempt}: {outcome}", flush=True)
        if outcome != "completed":
            raise SystemExit(1)


if __name__ == "__main__":
    main()
