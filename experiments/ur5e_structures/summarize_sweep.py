"""Summarize a structure sweep from its definition and the raw run outputs.

A sweep definition (`sweeps/<name>.json`) lists each run's label, config,
environment overrides, run id (the `outputs/ur5e_dog/<run>/` folder) and video.
This script reads, per run:

- the console log (`attempt-1.txt`): first failure, gripper contacts, BrickSim
  joint events and breakage-solver warnings, in log order;
- the recording it names (`outputs/ur5e_lego/*.jsonl`): the assembly and breakage
  settings applied, bricks connected at the end, simulated time;
- the utilization CSV written beside it (`outputs/ur5e_dog/utilization-*.csv`):
  the breakage solver's load over capacity per joint before each break.

It writes `sweeps/<name>.summary.json` and `sweeps/<name>.summary.md`. The raw
outputs are not in git; the summaries are. Everything is simulation.

Each run gets separate fields, not one merged label:

- `failure_class`: what stopped the controller (see `FAILURE_CLASSES`).
- `contact_mode` and `gripper_contacts`: whether a gripper contact with another
  brick stops the run (`fail`) or is only logged (`log`), and how many occurred.
- `breakage_enabled`: whether joints can break at all.
- per joint break: whether utilization of at least 1 was already sampled in the
  0.5 s before it (`overload_seen`), the breakage-solver warnings logged since
  the previous joint event, and whether the same pair joined again at once
  (`rejoined`, a transient break the structure survives in ground truth).

How BrickSim breaks joints (native/modules/bricksim/physx/physics_graph.cppm,
breakage_selector.cppm): only a converged solve updates utilization; when the
largest utilization of a component is at least 1 (and the 0.05 s cooldown after
a topology change has passed), it removes the minimum cut between the parts of
that joint, which can include joints below 1. The breaking solve itself is not
sampled (the joint is gone before the recorder reads it), so a break with no
earlier overload is reported as `sudden`, not as unexplained. Utilization 1e6 is
BrickSim's sentinel for exhausted capacity (`frc_cap <= 0`), not a load.

    python3 -m experiments.ur5e_structures.summarize_sweep \
        experiments/ur5e_structures/sweeps/2026-11-08-failure-sweep.json
"""

import json
import re
from argparse import ArgumentParser
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# Controller settings read from the environment, with the defaults in
# experiments/ur5e_dog/controller.py and run.py (checked by test_summarize_sweep).
CONTROLLER_DEFAULTS = {
    "DOG_BREAKAGE": "1",
    "DOG_GRIPPER_CONTACT": "fail",
    "DOG_REQUIRED_FORCE_N": "1.0",
    "DOG_PRESS_DEPTH_M": "0.0005",
    "DOG_PRESS_HOLD_S": "0.05",
    "DOG_FREEZE_ON_CONNECTION": "1",
    "DOG_RELEASE_RAMP_S": "1.0",
    "DOG_TIP_CLEARANCE_M": "0.003",
    "DOG_HOLD_S": "10",
}

# (class, pattern on the first failure message), first match wins.
FAILURE_CLASSES = [
    ("gripper_contact_abort", r"Gripper touched"),
    ("no_release_clearance", r"No gripper clearance"),
    ("joint_lost", r"detached from its support"),
    ("joint_lost_in_press", r"detached during the press"),
    ("not_seated", r"did not complete the press"),
    ("misplaced", r"connected at .* yaw"),
    ("grasp", r"grasp is off center|not retained during lift"),
]
FAILURE = re.compile(r"(?:RuntimeError|AssertionError|ValueError): (.+)")
JOINT_EVENT = re.compile(
    r"\[bricksim\] (Assembled|Disassembled) at t=(\d+) Connection #(\d+) .*"
    r"between (\S+) #\d+ -> (\S+) #\d+"
)
NOT_CONVERGED = "BreakageChecker: solver failed to converge"
HIGH_SLACK = re.compile(r"BreakageChecker: abnormally high slack fraction ([\d.]+)%")
BREAK_WINDOW_S = 0.5
# A planned joint connected again within this time after a break was re-formed.
REJOIN_S = 1.0
# A brick farther than this (xy) from the tool when the press fails was not held.
LOST_FROM_GRASP_M = 0.02


def classify_failure(message: str | None) -> str:
    """Name what stopped the controller.

    Args:
        message: First failure message from the console, or None.

    Returns:
        A class from `FAILURE_CLASSES`, `none` without a failure, else `other`.
    """
    if message is None:
        return "none"
    for name, pattern in FAILURE_CLASSES:
        if re.search(pattern, message):
            if name == "not_seated" and press_lost_grasp(message):
                return "lost_from_grasp"
            return name
    return "other"


def press_lost_grasp(message: str) -> bool:
    """Tell whether a failed press had the brick far from the tool.

    Args:
        message: A "did not complete the press" message with brick and tool xyz.

    Returns:
        True if the brick was more than `LOST_FROM_GRASP_M` from the tool in xy.
    """
    brick = re.search(r"brick=\[([^\]]+)\]", message)
    tool = re.search(r"tool=\[([^\]]+)\]", message)
    if not (brick and tool):
        return False
    b = [float(v) for v in brick.group(1).split()[:2]]
    t = [float(v) for v in tool.group(1).split()[:2]]
    return ((b[0] - t[0]) ** 2 + (b[1] - t[1]) ** 2) ** 0.5 > LOST_FROM_GRASP_M


def read_console(path: Path) -> dict:
    """Read one attempt's console log.

    Args:
        path: `attempt-1.txt` of a run.

    Returns:
        Recording path, first failure, contact counts, joint events (each with
        the solver warnings logged since the previous event) and warning totals.
    """
    text = path.read_text(errors="replace")
    recording = re.search(r"UR5e recording: (\S+)", text)
    failure = FAILURE.search(text)
    events = []
    pending = {"not_converged": 0, "high_slack": 0, "max_slack_pct": 0.0}
    totals = {"not_converged": 0, "high_slack": 0}
    for line in text.splitlines():
        if NOT_CONVERGED in line:
            pending["not_converged"] += 1
            totals["not_converged"] += 1
        elif slack := HIGH_SLACK.search(line):
            pending["high_slack"] += 1
            pending["max_slack_pct"] = max(pending["max_slack_pct"], float(slack[1]))
            totals["high_slack"] += 1
        elif event := JOINT_EVENT.search(line):
            events.append(
                {
                    "kind": event[1].lower(),
                    "step": int(event[2]),
                    "connection": f"/World/managed/Conns/Conn_{event[3]}",
                    "parent": event[4],
                    "child": event[5],
                    "solver_warnings_before": dict(pending),
                }
            )
            pending = {"not_converged": 0, "high_slack": 0, "max_slack_pct": 0.0}
    monitored = "finger profile" in text
    # Kit flushes its log asynchronously and the process exits with os._exit,
    # so the last BrickSim lines can be missing. Every brick the controller saw
    # connect must have an "Assembled" event, else the event log is incomplete.
    connected = len(re.findall(r"brick (\d+)/\d+ connected offset", text))
    assembled = {
        e["child"].rsplit("/", 1)[-1] for e in events if e["kind"] == "assembled"
    }
    complete = all(f"Part_{i}" in assembled for i in range(1, connected + 1))
    return {
        "recording": Path(recording[1]) if recording else None,
        "failure": failure[1].strip() if failure else None,
        "gripper_contacts": text.count("gripper touched") if monitored else None,
        "events": events,
        "solver_warnings": totals,
        "event_log_complete": complete,
    }


def read_recording(path: Path) -> dict:
    """Read the settings and end state of a recording.

    Args:
        path: JSON Lines recording.

    Returns:
        Experiment, start time, settings from the last sample, bricks connected
        at the end, simulated seconds, end status, and for each brick's joint to
        its planned support (`primary_joints`, keyed "support>brick" part names)
        the (elapsed s, connected, phase) samples where its state changed.
    """
    primary: dict[str, list[tuple[float, bool, str]]] = {}
    with path.open() as stream:
        metadata = json.loads(stream.readline())
        last = None
        status = "incomplete"
        for line in stream:
            record = json.loads(line)
            if record["kind"] == "sample":
                last = record
                for placement in record["placements"]:
                    key = joint_key(placement["stud_path"], placement["hole_path"])
                    changes = primary.setdefault(key, [(0.0, False, "")])
                    if bool(placement["connected"]) != changes[-1][1]:
                        changes.append(
                            (
                                record["simulation_elapsed_s"],
                                bool(placement["connected"]),
                                record["phase"],
                            )
                        )
            elif record["kind"] == "end":
                status = record["status"]
    placements = last["placements"] if last else []
    return {
        "experiment": metadata["experiment"],
        "created_utc": metadata["created_utc"],
        "bricks_total": len(metadata["config"]["assembly"]["part_names"]),
        "bricks_connected_end": sum(bool(p["connected"]) for p in placements),
        "simulation_s": round(last["simulation_elapsed_s"], 2) if last else 0.0,
        "status": status,
        "assembly_settings": last["assembly_settings"] if last else {},
        "breakage_settings": last["breakage_settings"] if last else {},
        "primary_joints": {key: changes[1:] for key, changes in primary.items()},
    }


def joint_key(parent: str, child: str) -> str:
    """Name a joint by its part names, e.g. "Part_0>Part_1".

    Args:
        parent: Stud-side part path or name.
        child: Hole-side part path or name.

    Returns:
        The key used for joints in summaries.
    """
    return f"{parent.rsplit('/', 1)[-1]}>{child.rsplit('/', 1)[-1]}"


def reconcile_with_recording(
    breaks: list[dict], events: list[dict], primary: dict
) -> bool:
    """Correct breaks of planned joints with the recording, and check the log.

    The recording samples every brick's joint to its planned support each
    physics step, so it is the ground truth for those joints. The k-th console
    break of such a joint is matched to its k-th disconnection in the recording;
    `rejoined` then means the joint was connected again within `REJOIN_S`.
    Disconnections the console did not log are added as breaks with cause
    `not in console log`.

    Args:
        breaks: From `describe_breaks`, updated and extended in place.
        events: Joint events from `read_console`.
        primary: `primary_joints` from `read_recording`.

    Returns:
        False if the recording shows more connections or disconnections of a
        planned joint than the console logged (the log lost events).
    """
    complete = True
    for key, changes in primary.items():
        connects = [t for t, connected, _ in changes if connected]
        disconnects = [(t, phase) for t, connected, phase in changes if not connected]
        logged = [joint_key(e["parent"], e["child"]) == key for e in events]
        assembled = sum(
            hit and e["kind"] == "assembled" for hit, e in zip(logged, events)
        )
        if len(connects) > assembled or len(disconnects) > len(logged) - assembled:
            complete = False
        matching = [b for b in breaks if f"{b['parent']}>{b['child']}" == key]
        parent, child = key.split(">")
        for position, (t_break, phase) in enumerate(disconnects):
            if position < len(matching):
                entry = matching[position]
            else:
                entry = {
                    "parent": parent,
                    "child": child,
                    "last_seen_s": None,
                    "phase": phase,
                    "peak_utilization": None,
                    "peak_utilization_before_break": None,
                    "overload_seen": False,
                    "solver_warnings": {
                        "not_converged": 0,
                        "high_slack": 0,
                        "max_slack_pct": 0.0,
                    },
                    "cause": "not in console log",
                }
                breaks.append(entry)
            later = [t for t in connects if t > t_break]
            entry["rejoined"] = bool(later) and later[0] - t_break <= REJOIN_S
            entry["rejoined_source"] = "recording"
            entry["broken_at_s"] = round(t_break, 4)
    return complete


def find_utilization(experiment: str, created_utc: str) -> Path | None:
    """Find the utilization CSV the recorder opened with a recording.

    Args:
        experiment: The recording's experiment name.
        created_utc: The recording's ISO creation time.

    Returns:
        The CSV stamped within 3 s of the recording, or None.
    """
    created = datetime.fromisoformat(created_utc).replace(tzinfo=None)
    for csv in (ROOT / "outputs/ur5e_dog").glob(f"utilization-{experiment}-*.csv"):
        stamp = datetime.strptime(csv.stem.rsplit("-", 1)[1], "%Y%m%dT%H%M%S")
        if abs((stamp - created).total_seconds()) <= 3:
            return csv
    return None


def read_utilization(path: Path | None) -> dict[str, list[tuple[float, str, float]]]:
    """Read a utilization CSV.

    Args:
        path: CSV with `elapsed_s,phase,brick_index,connection_path,utilization`.

    Returns:
        Connection path to its (elapsed s, phase, utilization) rows, in time
        order. Utilization -1 means not evaluated.
    """
    rows: dict[str, list[tuple[float, str, float]]] = {}
    if path is None:
        return rows
    with path.open() as stream:
        next(stream)
        for line in stream:
            elapsed, phase, _, connection, utilization = line.rstrip().split(",")
            rows.setdefault(connection, []).append(
                (float(elapsed), phase, float(utilization))
            )
    return rows


def describe_breaks(events: list[dict], utilization: dict) -> list[dict]:
    """Describe each joint removed during the run.

    Args:
        events: Joint events from `read_console`.
        utilization: Rows from `read_utilization`.

    Returns:
        One entry per `disassembled` event: the parts, when and in which phase
        the joint was last seen, peak utilization over its life and in the
        0.5 s before the break, the solver warnings since the previous joint
        event, whether the same pair joined again right after, and the cause.
    """
    breaks = []
    for position, event in enumerate(events):
        if event["kind"] != "disassembled":
            continue
        rows = [r for r in utilization.get(event["connection"], []) if r[2] >= 0]
        last_t, last_phase = (rows[-1][0], rows[-1][1]) if rows else (None, None)
        window = [r[2] for r in rows if last_t - r[0] <= BREAK_WINDOW_S] if rows else []
        peak_window = max(window, default=None)
        warnings = event["solver_warnings_before"]
        after_warnings = warnings["not_converged"] + warnings["high_slack"] > 0
        overload_seen = peak_window is not None and peak_window >= 1.0
        following = events[position + 1] if position + 1 < len(events) else None
        breaks.append(
            {
                "parent": event["parent"].rsplit("/", 1)[-1],
                "child": event["child"].rsplit("/", 1)[-1],
                "last_seen_s": last_t,
                "phase": last_phase,
                "peak_utilization": max((r[2] for r in rows), default=None),
                "peak_utilization_before_break": peak_window,
                "overload_seen": overload_seen,
                "solver_warnings": warnings,
                "rejoined_source": "console",
                "rejoined": bool(
                    following
                    and following["kind"] == "assembled"
                    and (following["parent"], following["child"])
                    == (event["parent"], event["child"])
                ),
                "cause": (
                    "no utilization data"
                    if not rows
                    else ("overload seen" if overload_seen else "sudden")
                    + (", after solver warnings" if after_warnings else "")
                ),
            }
        )
    return breaks


def summarize_run(sweep: dict, run: dict) -> dict:
    """Summarize one run of a sweep.

    Args:
        sweep: The sweep definition.
        run: One entry of its `runs`.

    Returns:
        The run's settings (with where each came from), outcome, failure class,
        contacts, joint breaks, solver warnings and evidence paths.
    """
    run_dir = ROOT / "outputs/ur5e_dog" / run["run"]
    manifest = json.loads((run_dir / "manifest.json").read_text())[0]
    console = read_console(run_dir / "attempt-1.txt")
    recording = read_recording(console["recording"]) if console["recording"] else {}
    utilization_csv = (
        find_utilization(recording["experiment"], recording["created_utc"])
        if recording
        else None
    )
    environment = {**sweep.get("environment", {}), **run.get("environment", {})}
    settings = {
        name: {
            "value": environment.get(name, default),
            "source": "sweep definition" if name in environment else "default",
        }
        for name, default in CONTROLLER_DEFAULTS.items()
    }
    breakage = recording.get("breakage_settings", {})
    assembly = recording.get("assembly_settings", {})
    # The recording is the ground truth for what the simulator applied.
    if breakage:
        settings["DOG_BREAKAGE"] = {
            "value": "1" if breakage["enabled"] else "0",
            "source": "recording",
        }
    if assembly:
        settings["DOG_REQUIRED_FORCE_N"] = {
            "value": str(assembly["required_force_n"]),
            "source": "recording",
        }
    failure_class = classify_failure(console["failure"])
    breaks = describe_breaks(console["events"], read_utilization(utilization_csv))
    recording_agrees = reconcile_with_recording(
        breaks, console["events"], recording.get("primary_joints", {})
    )
    return {
        "label": run["label"],
        "config": run["config"],
        "run": run["run"],
        "recording": console["recording"].name if console["recording"] else None,
        "utilization_csv": utilization_csv.name if utilization_csv else None,
        "video": run.get("video"),
        "media": run.get("media"),
        "settings": settings,
        "breakage_enabled": settings["DOG_BREAKAGE"]["value"] == "1",
        "contact_mode": settings["DOG_GRIPPER_CONTACT"]["value"],
        "outcome": manifest["outcome"],
        "bricks_total": recording.get("bricks_total"),
        "bricks_connected_end": recording.get("bricks_connected_end"),
        "simulation_s": recording.get("simulation_s"),
        "failure": console["failure"],
        "failure_class": failure_class,
        "gripper_contacts": console["gripper_contacts"],
        "contact_stopped_run": failure_class == "gripper_contact_abort",
        "solver_warnings": console["solver_warnings"],
        "event_log_complete": console["event_log_complete"] and recording_agrees,
        "breaks": breaks,
        "lasting_breaks": sum(not b["rejoined"] for b in breaks),
        "transient_breaks": sum(b["rejoined"] for b in breaks),
        "breakage_settings": breakage,
        "assembly_settings": assembly,
    }


def describe_break(entry: dict) -> str:
    """Render one joint break for the Markdown table.

    Args:
        entry: One element of a run's `breaks`.

    Returns:
        "support→brick in phase: cause, u=peak (rejoined)".
    """
    peak = entry["peak_utilization_before_break"]
    value = (
        "" if peak is None else ", u exhausted" if peak >= 1e6 else f", u {peak:.3f}"
    )
    rejoined = " (rejoined)" if entry["rejoined"] else ""
    return (
        f"{entry['parent']}→{entry['child']} in {entry['phase']}: "
        f"{entry['cause']}{value}{rejoined}"
    )


def markdown(sweep: dict, runs: list[dict]) -> str:
    """Render a sweep summary as Markdown.

    Args:
        sweep: The sweep definition.
        runs: Run summaries from `summarize_run`.

    Returns:
        A Markdown document.
    """
    lines = [
        f"# Sweep {sweep['name']} (simulation)",
        "",
        "Generated by `experiments/ur5e_structures/summarize_sweep.py` from the sweep",
        f"definition [{sweep['name']}.json]({sweep['name']}.json); do not edit.",
        "",
        sweep["description"],
        "",
        f"- Controller commit: `{sweep['controller_commit']}`",
        f"- Invocation: `{sweep['invocation']}`",
        f"- Sweep environment: `{json.dumps(sweep.get('environment', {}))}`",
        "",
        "| Run | Config | Overrides | Breakage | Contacts (mode) | Outcome | "
        "Connected at end | Stopped by | Breaks lasting / transient | Joint breaks | "
        "Solver warnings | Evidence |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    definitions = {run["label"]: run for run in sweep["runs"]}
    for run in runs:
        overrides = definitions[run["label"]].get("environment", {})
        breaks = "<br>".join(describe_break(b) for b in run["breaks"])
        evidence = []
        if run["media"]:
            evidence.append(f"[media](../../../{run['media']}.mp4)")
        if run["video"]:
            evidence.append(f"`{run['video']}`")
        warnings = run["solver_warnings"]
        lines.append(
            f"| {run['label']} | `{Path(run['config']).name}` | "
            f"{' '.join(f'{k}={v}' for k, v in overrides.items()) or ''} | "
            f"{'on' if run['breakage_enabled'] else 'off'} | "
            f"{run['gripper_contacts']} ({run['contact_mode']}) | {run['outcome']} | "
            f"{run['bricks_connected_end']}/{run['bricks_total']} | "
            f"{run['failure_class']} | "
            f"{run['lasting_breaks']} / {run['transient_breaks']}"
            f"{'' if run['event_log_complete'] else ' (log incomplete)'} | "
            f"{breaks or '—'} | "
            f"{warnings['not_converged']} / {warnings['high_slack']} | "
            f"{' '.join(evidence) or '—'} |"
        )
    lines += [
        "",
        "Columns: *Contacts (mode)* counts gripper contacts with other bricks;",
        "`log` mode records them and lets the run continue, `fail` mode stops the",
        "run (`gripper_contact_abort`). *Stopped by* is the controller's first",
        "failure. *Breaks*: a lasting break leaves the joint removed; a transient",
        "one is re-formed within 1 s (the structure survives in ground truth, but",
        "BrickSim broke the joint). For each brick's joint to its planned support,",
        "the recording decides; for other joints, the console's next event does.",
        "*Joint breaks* lists each removed joint",
        "(support → brick, `Part_0` is the baseplate), the phase it was last seen",
        "in, and what the telemetry shows before it: `overload seen` (utilization",
        "of at least 1 sampled within 0.5 s) or `sudden` (only the unsampled",
        "breaking step reached 1), `after solver warnings` when the breakage",
        "solver failed to converge or reported high slack since the previous",
        "joint event, and the peak sampled utilization in that window (`exhausted`",
        "is BrickSim's 1e6 sentinel for no remaining capacity). Every break is",
        "BrickSim's selector acting on a converged solve with utilization of at",
        "least 1; see the docstring of `summarize_sweep.py`. *Solver warnings* are",
        "breakage-solver non-convergence / high-slack counts over the run.",
        "*log incomplete*: the console lost BrickSim's last events (Kit flushes",
        "its log asynchronously and the run exits at once), so breaks and solver",
        "warnings are lower bounds for that run. Raw outputs (run folders,",
        "recordings, utilization CSVs, full-resolution videos) stay local.",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    """Write the JSON and Markdown summaries of each sweep given."""
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("sweeps", nargs="+", type=Path, help="Sweep definitions.")
    args = parser.parse_args()
    for path in args.sweeps:
        sweep = json.loads(path.read_text())
        runs = [summarize_run(sweep, run) for run in sweep["runs"] if run.get("run")]
        stem = path.with_suffix("")
        stem.with_suffix(".summary.json").write_text(
            json.dumps({"sweep": sweep["name"], "runs": runs}, indent=2) + "\n"
        )
        stem.with_suffix(".summary.md").write_text(markdown(sweep, runs))
        for run in runs:
            print(
                f"{run['label']}: {run['outcome']} {run['bricks_connected_end']}/"
                f"{run['bricks_total']} {run['failure_class']} "
                f"breaks={[b['cause'] for b in run['breaks']]}"
            )


if __name__ == "__main__":
    main()
