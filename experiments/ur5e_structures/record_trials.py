"""Add simulation trials of structures to `trials.json` from recorded runs.

Each recording under `outputs/ur5e_lego/` whose experiment is `structure_<name>`
(or `dog_ten*`, recorded as structure `dog`) becomes one trial. Connections are
the bricks still connected in the recording's last sample, so a joint that broke
after forming is not counted. The first failure message comes from the matching
console log under `outputs/ur5e_dog/`; a run with one is `failed`. Trials already in
the file (same recording) are kept unchanged. Real-robot trials are added to the
same file by hand; see README.md.

Run from the repository root with the project environment, so the Isaac Sim
version can be recorded:

    .venv/bin/python -m experiments.ur5e_structures.record_trials
"""

import json
from argparse import ArgumentParser
from importlib.metadata import version
from pathlib import Path
from re import search

ROOT = Path(__file__).resolve().parents[2]
TRIALS = Path(__file__).with_name("trials.json")
FAILURE = r"(?:RuntimeError|AssertionError|ValueError): (.+)"


def structure_name(experiment: str) -> str | None:
    """Map a recording's experiment name to its structure name.

    Args:
        experiment: The `experiment` field of a recording's metadata.

    Returns:
        The structure name, or None if the recording is not a structure build.
    """
    if experiment.startswith("structure_"):
        return experiment.removeprefix("structure_")
    # Seed variants (`dog_ten_seed<n>`) jitter only the pickup positions.
    return "dog" if experiment.startswith("dog_ten") else None


def read_recording(path: Path) -> dict[str, object]:
    """Summarize one recording as a simulation trial.

    Args:
        path: Plain JSON Lines recording.

    Returns:
        Trial fields read from the recording (no failure message).
    """
    with path.open() as stream:
        metadata = json.loads(stream.readline())
        last = None
        status = "incomplete"
        for line in stream:
            record = json.loads(line)
            if record["kind"] == "sample":
                last = record
            elif record["kind"] == "end":
                status = record["status"]
    placements = last["placements"] if last else []
    assembly = last["assembly_settings"] if last else {}
    return {
        "experiment": metadata["experiment"],
        "date_utc": metadata["created_utc"],
        "breakage": bool(last and last["breakage_settings"]["enabled"]),
        "bricks_total": len(metadata["config"]["assembly"]["part_names"]),
        "bricks_connected": sum(bool(p["connected"]) for p in placements),
        "outcome": status,
        "required_force_n": assembly.get("required_force_n"),
        "simulation_s": last["simulation_elapsed_s"] if last else 0.0,
        "recording": path.name,
    }


def console_summaries() -> dict[str, tuple[str | None, int | None]]:
    """Read every console log's first failure and gripper contacts.

    Returns:
        Recording file name to (first failure message or None, number of gripper
        contacts with other bricks, or None for runs before contact monitoring).
    """
    summaries: dict[str, tuple[str | None, int | None]] = {}
    for console in sorted((ROOT / "outputs/ur5e_dog").glob("*/attempt-*.txt")):
        text = console.read_text(errors="replace")
        recording = search(r"UR5e recording: (\S+)", text)
        if recording:
            failure = search(FAILURE, text)
            monitored = "finger profile" in text
            summaries[Path(recording.group(1)).name] = (
                failure.group(1).strip() if failure else None,
                text.count("gripper touched") if monitored else None,
            )
    return summaries


def main() -> None:
    """Append new simulation trials to `trials.json` and print them."""
    parser = ArgumentParser(description=__doc__)
    parser.add_argument(
        "recordings",
        nargs="*",
        type=Path,
        help="Recordings to add; default every structure recording in outputs/.",
    )
    args = parser.parse_args()
    trials = json.loads(TRIALS.read_text()) if TRIALS.exists() else []
    known = {trial.get("recording") for trial in trials}
    summaries = console_summaries()
    platform = f"Isaac Sim {version('isaacsim')}"
    paths = args.recordings or sorted((ROOT / "outputs/ur5e_lego").glob("*.jsonl"))
    for path in paths:
        if path.name in known:
            continue
        with path.open() as stream:
            experiment = json.loads(stream.readline()).get("experiment", "")
        name = structure_name(experiment)
        if name is None:
            continue
        trial = {
            "structure": name,
            "kind": "simulation",
            "platform": platform,
            **read_recording(path),
            "failure": summaries.get(path.name, (None, None))[0],
            "gripper_contacts": summaries.get(path.name, (None, None))[1],
            "notes": "",
        }
        # A run that raised never writes its end record.
        if trial["outcome"] == "incomplete" and trial["failure"]:
            trial["outcome"] = "failed"
        trials.append(trial)
        print(
            f"{name}: {trial['bricks_connected']}/{trial['bricks_total']} "
            f"{trial['outcome']} breakage={trial['breakage']}"
        )
    trials.sort(key=lambda trial: (trial["structure"], trial["date_utc"]))
    TRIALS.write_text(json.dumps(trials, indent=2) + "\n")


if __name__ == "__main__":
    main()
