"""Write docs/STRUCTURES.md: every structure with its design, result and video.

For each structure this draws the design (`render.py`) to
`docs/structures/<name>.png` and writes one catalog entry:
- its description;
- brick counts and layers;
- how many bricks land on two or more supports;
- the weakest planned joint;
- the simulation picture and video when there are any;
- how many sweep runs at the default settings completed, the latest result,
  and the runs at other settings, all from the sweep summaries.

It also writes `docs/structures/index.json` for the dashboard, and rewrites
the results table between the `<!-- results:start -->` and
`<!-- results:end -->` markers in `FAILURES.md`.

All results are simulation.

    .venv/bin/python -m experiments.ur5e_structures.catalog
"""

import json
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from typing import TypedDict

from experiments.ur5e_structures.render import draw, footprints

ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / "docs"
MEDIA = DOCS / "media"
STRUCTURES = Path(__file__).parent

SECTIONS = {
    "showcase": (
        "Showcase builds",
        "Recognisable structures that need distinctive steps.",
    ),
    "figures": ("Figures", "Smaller recognisable builds."),
    "complex": (
        "Complex builds",
        "Harder structures, some failing, with the variants tried to build them.",
    ),
    "break": (
        "Break tests (failures on purpose)",
        "Each pushes one failure mechanism, some with a matched control.",
    ),
    "basics": (
        "Basics",
        "Simple builds used to check the controller and the breakage model.",
    ),
}

# name: (section, title, description, failure mechanism in FAILURES.md or "").
ENTRIES = {
    "dog": (
        "showcase",
        "Dog",
        "Ten bricks: four legs, a wide body bridging them, a neck, head and tail.",
        "",
    ),
    "bridge": (
        "showcase",
        "Arch bridge",
        "A corbel arch: each pier steps one stud inward, then a 2x10 deck closes "
        "the arch by landing on both piers. Two parapets finish the deck.",
        "",
    ),
    "house": (
        "showcase",
        "House",
        "A facade with a doorway. Two walls stand two courses high, a 2x10 lintel "
        "spans the door and lands on both walls, and a stepped gable roof and a "
        "chimney finish it.",
        "B: release load on an 8-stud wall joint",
    ),
    "log_cabin": (
        "showcase",
        "Log cabin",
        "Courses alternate direction, and every brick above the first interlocks "
        "two corners below. It is planned on one corner and lands on both.",
        "",
    ),
    "locomotive": (
        "showcase",
        "Steam locomotive",
        "Three wheels, a 2x10 chassis that rests on all three, a cab with an "
        "overhanging roof, a boiler and a chimney.",
        "",
    ),
    "lighthouse": (
        "showcase",
        "Lighthouse",
        "A 4x6 rock, a tower striped red and white, a yellow lamp and a red cap: "
        "seven layers, the tallest showcase build.",
        "",
    ),
    "castle_gate": (
        "showcase",
        "Castle gate",
        "Two towers flank the gate, a 2x10 lintel spans it and lands on both "
        "towers, and three battlements line the top.",
        "",
    ),
    "tree": (
        "figures",
        "Tree",
        "A three-high 2x2 trunk under a crown of 2x6, 4x2 and 2x2 bricks.",
        "B: the trunk's 4-stud base joint breaks on the releases, transiently, "
        "then for good",
    ),
    "table": (
        "complex",
        "Table",
        "Four 2x2 legs two bricks high under two 2x6 tops.",
        "C: legs 2 studs apart leave no room for the RG2 fingers to let go",
    ),
    "table_grip": (
        "complex",
        "Table, grip-aware",
        "The table's ten bricks, with each grip chosen for room. The legs are "
        "gripped across the axis where they are 4 studs apart, and the 2x8 tops "
        "are gripped end to end, so no finger enters a 2-stud gap.",
        "",
    ),
    "table_wide": (
        "complex",
        "Table, wide gaps",
        "Four 2x2 legs two bricks high, 4 studs apart both ways, under two 2x8 tops "
        "gripped across their width.",
        "",
    ),
    "trestle_table": (
        "complex",
        "Trestle table",
        "Two slab legs of 2x4 bricks gripped end to end under a 4x6 top.",
        "",
    ),
    "mixed_tower": (
        "complex",
        "Mixed tower",
        "Eight bricks of three sizes stacked with offsets.",
        "D: a brick stops on the studs and does not seat",
    ),
    "cross_tower": (
        "complex",
        "Cross-bonded tower",
        "Ten 2x4 bricks alternating +90 and -90 degrees.",
        "E: the second joint breaks after four breakage-solver non-convergences",
    ),
    "spiral_tower": (
        "complex",
        "Spiral tower",
        "Ten 2x4 bricks, each a quarter turn from the one below.",
        "E: the second joint breaks after four breakage-solver non-convergences",
    ),
    "l_corner": (
        "complex",
        "L corner",
        "Two posts joined by a corner brick.",
        "A: press load through a 4-stud joint",
    ),
    "tower": (
        "complex",
        "Offset tower",
        "Six 2x4 bricks alternating direction, each shifted by a stud.",
        "B: release load on a 4-stud joint",
    ),
    "cantilever": (
        "break",
        "Cantilever",
        "A 2x6 rests by one end on a 2x2 column, with a 2x2 pressed onto its free tip.",
        "A: press on the overhang",
    ),
    "cantilever_tip2": (
        "break",
        "Cantilever, two bricks at the tip",
        "Two 2x2 bricks pressed onto the free tip of the cantilever.",
        "A: the press pries the column's base joint off before the brick seats",
    ),
    "cantilever_root2": (
        "break",
        "Cantilever, two bricks over the support (control)",
        "The same two bricks pressed over the support instead of the tip.",
        "",
    ),
    "lean_ladder": (
        "break",
        "Leaning ladder",
        "Eight 4x2 bricks, each shifted one stud: the lean grows with every layer.",
        "B: growing overturning moment on the low joints",
    ),
    "tower_2x2": (
        "break",
        "2x2 tower",
        "Ten 2x2 bricks: every joint has only 4 studs.",
        "B: the base joint breaks transiently on each release, then for good",
    ),
    "lean_6": (
        "break",
        "Lean 6",
        "Six 2x4 bricks, each shifted 2 studs (4-stud joints).",
        "B: release load on a 4-stud joint",
    ),
    "zigzag_6": (
        "break",
        "Zigzag 6",
        "Six 2x4 bricks shifted +2 and -2 studs in turn.",
        "A: press load through a 4-stud joint",
    ),
    "column_10": (
        "break",
        "Column of ten",
        "Ten aligned 2x4 bricks: the load on the base grows with height.",
        "B: release load accumulated over ten layers",
    ),
    "column_turned": (
        "break",
        "Column, turned 90 degrees",
        "The 4-brick column with every brick laid along x: the same 8-stud joints, "
        "gripped with the wrist turned 90 degrees. It is a control for the house "
        "wall.",
        "",
    ),
    "single": ("basics", "Single brick", "One 2x4 on the baseplate.", ""),
    "column": (
        "basics",
        "Column",
        "Four aligned 2x4 bricks (8-stud joints). It is also the press-force "
        "sweep: it holds at 1 and 2 N and loses its base joint at 3 and 5 N.",
        "",
    ),
    "stairs": ("basics", "Stairs", "A staircase of 2x4, 2x2 and 2x6 bricks.", ""),
}

# Facts a reader needs that the trials do not show.
NOTES = {
    "house": "At the default 1 s gripper release, the first wall joint (8 studs) "
    "breaks during a release with no visible motion. With a 2 s release the "
    "house completes; the picture and video are that run.",
}

# Committed media are named after the run that made them.
MEDIA_STEM = {
    "dog": "dog_breakage_on",
    "cantilever": "cantilever_failure",
}


def config_path(name: str) -> Path:
    """Return the config of a structure.

    Args:
        name: Structure name.

    Returns:
        Path to its JSON config.
    """
    return STRUCTURES / f"{name}.json"


def details(config: dict) -> dict[str, object]:
    """Count bricks, layers, multi-support bricks and the weakest planned joint.

    Args:
        config: Assembly config.

    Returns:
        Brick mix text, brick count, layers, number of bricks resting on two or
        more bricks below, and the fewest studs on a planned support joint.
    """
    prints = footprints(config)
    mix = Counter(
        "x".join(str(v) for v in sorted(size[:2]))
        for size in config["brick_dimensions"]
    )
    multi = 0
    weakest = None
    for i, (x0, y0, x1, y1, layer) in enumerate(prints):
        below = []
        for j, (a0, b0, a1, b1, other) in enumerate(prints[:i]):
            overlap = max(0, min(x1, a1) - max(x0, a0)) * max(
                0, min(y1, b1) - max(y0, b0)
            )
            if other == layer - 1 and overlap:
                below.append((j, overlap))
        multi += len(below) >= 2
        support = config["support_bricks"][i]
        studs = (x1 - x0) * (y1 - y0) if support is None else dict(below).get(support)
        if studs is not None and (weakest is None or studs < weakest):
            weakest = studs
    return {
        "mix": ", ".join(f"{count}× {size}" for size, count in sorted(mix.items())),
        "bricks": len(prints),
        "layers": max(p[4] for p in prints) + 1,
        "multi": multi,
        "weakest": weakest,
    }


# What each structure tests, for the results table.
TESTS = {
    "dog": "wide bricks bridging legs; ten-brick figure",
    "bridge": "a deck landing on two piers (corbel arch)",
    "house": "a lintel over a doorway; stepped roof",
    "log_cabin": "courses alternating direction; interlocking corners",
    "locomotive": "a chassis resting on three wheels",
    "table_grip": "the table with grips chosen for room",
    "trestle_table": "slab legs gripped end to end",
    "table_wide": "4-stud gaps on both axes",
    "lighthouse": "a seven-layer tower on a wide base",
    "castle_gate": "a lintel over a gate; battlements",
    "tree": "a crown on a 2x2 trunk (4-stud joints)",
    "table": "four legs, then tops spanning them",
    "mixed_tower": "three brick sizes with offsets",
    "cross_tower": "alternating quarter turns (4-stud overlaps)",
    "spiral_tower": "repeated quarter turns (4-stud overlaps)",
    "l_corner": "a corner brick joining two posts",
    "tower": "alternating directions with 1-stud shifts",
    "cantilever": "a press on a cantilever tip",
    "cantilever_tip2": "two bricks at a cantilever tip",
    "cantilever_root2": "the same bricks over the support (control)",
    "lean_ladder": "a lean that grows every layer",
    "tower_2x2": "ten 4-stud joints",
    "lean_6": "2-stud shifts (4-stud joints)",
    "zigzag_6": "shear at every joint",
    "column_10": "load on the base growing with height",
    "column_turned": "the column with bricks turned 90 degrees",
    "single": "one brick (sanity check)",
    "column": "aligned 8-stud joints",
    "stairs": "mixed sizes stepping up",
}
STOP = {
    "none": "",
    "joint_lost": "a joint broke",
    "joint_lost_in_press": "a joint broke during a press",
    "not_seated": "a brick did not seat",
    "lost_from_grasp": "a brick slipped from the grasp",
    "no_release_clearance": "no room to release",
    "gripper_contact_abort": "gripper touched a brick (abort)",
    "grasp": "grasp failed",
    "misplaced": "a brick seated in the wrong place",
    "other": "other",
}
# Settings that only change logging or presentation, not the build.
COSMETIC = {"ASSEMBLY_GRIPPER_CONTACT", "ASSEMBLY_HOLD_S"}


def sweep_runs() -> dict[str, list[dict]]:
    """Collect every summarized sweep run by structure.

    Returns:
        Structure name to its runs (oldest first). Each run has the sweep, label,
        run id, outcome, connected/total, failure class, and `changed`: the
        settings that differ from the controller defaults (empty at defaults).
    """
    from experiments.ur5e_structures.summarize_sweep import CONTROLLER_DEFAULTS

    runs: dict[str, list[dict]] = {}
    for path in sorted((STRUCTURES / "sweeps").glob("*.summary.json")):
        summary = json.loads(path.read_text())
        for run in summary["runs"]:
            changed = {
                key: value["value"]
                for key, value in run["settings"].items()
                if key not in COSMETIC
                and float(value["value"]) != float(CONTROLLER_DEFAULTS[key])
            }
            structure = Path(run["config"]).stem
            if Path(run["config"]).parent.name == "attempts":
                variant = json.loads((ROOT / run["config"]).read_text())
                structure = variant["variant_of"]
                changed = {"variant": variant["variant"], **changed}
            runs.setdefault(structure, []).append(
                {
                    "sweep": summary["sweep"],
                    "label": run["label"],
                    "run": run["run"],
                    "outcome": run["outcome"],
                    "connected": run["bricks_connected_end"],
                    "total": run["bricks_total"],
                    "failure_class": run["failure_class"],
                    "changed": changed,
                }
            )
    for entries in runs.values():
        entries.sort(key=lambda r: r["run"])
    return runs


class Results(TypedDict):
    """A structure's runs at the default settings and at other settings."""

    runs: int
    completed: int
    latest: dict | None
    other: list[dict]


def results(runs: list[dict]) -> Results:
    """Summarize a structure's runs at default settings.

    Args:
        runs: The structure's runs from `sweep_runs`.

    Returns:
        Number of default runs, completed ones, the latest default run (or
        None), and the runs at other settings.
    """
    default = [r for r in runs if not r["changed"]]
    return {
        "runs": len(default),
        "completed": sum(r["outcome"] == "completed" for r in default),
        "latest": default[-1] if default else None,
        "other": [r for r in runs if r["changed"]],
    }


def describe_settings(changed: dict[str, str]) -> str:
    """Name changed controller settings in words, e.g. "2 s gripper release".

    Args:
        changed: Setting name to value, as in a run's `changed`.

    Returns:
        A comma-separated description.
    """
    words: dict[str, Callable[[str], str]] = {
        "ASSEMBLY_RELEASE_RAMP_S": lambda v: f"{float(v):g} s gripper release",
        "ASSEMBLY_PRESS_DEPTH_M": lambda v: (
            f"press {float(v) * 1000:g} mm below seated"
        ),
        "ASSEMBLY_REQUIRED_FORCE_N": lambda v: f"{float(v):g} N press",
        "ASSEMBLY_BREAKAGE": lambda v: "breakage off" if v == "0" else "breakage on",
        "ASSEMBLY_PRESS_HOLD_S": lambda v: f"{float(v):g} s press hold",
        "ASSEMBLY_TIP_CLEARANCE_M": lambda v: f"{float(v) * 1000:g} mm tip clearance",
        "ASSEMBLY_FREEZE_ON_CONNECTION": lambda v: f"freeze on connection {v}",
        "ASSEMBLY_RELEASE_MARGIN_M": lambda v: f"{float(v) * 1000:g} mm release margin",
        "ASSEMBLY_RELEASE_LIFT_M": lambda v: (
            f"ease off {float(v) * 1000:g} mm before letting go"
        ),
        "ASSEMBLY_RELEASE_MIN_CLEARANCE_M": lambda v: (
            f"{float(v) * 1000:g} mm minimum release clearance"
        ),
    }
    words["variant"] = str
    return ", ".join(
        words[k](v) if k in words else f"{k}={v}" for k, v in changed.items()
    )


def describe_result(run: dict) -> str:
    """Render one run's outcome, e.g. "completed, 7/7 connected".

    Args:
        run: A run from `sweep_runs`.

    Returns:
        A short outcome text.
    """
    if run["outcome"] == "completed":
        return f"completed, {run['connected']}/{run['total']} connected"
    return (
        f"failed ({STOP[run['failure_class']]}), "
        f"{run['connected']}/{run['total']} connected at the end"
    )


def entry(name: str, runs: list[dict]) -> tuple[str, Results]:
    """Render one structure's catalog entry and draw its design.

    Args:
        name: Structure name.
        runs: The structure's runs from `sweep_runs`.

    Returns:
        The Markdown entry and its results (from `results`).
    """
    _, title, description, mechanism = ENTRIES[name]
    config = json.loads(config_path(name).read_text())
    draw(config, DOCS / "structures" / f"{name}.png")
    info = details(config)
    stem = MEDIA_STEM.get(name, name)
    still = next(
        (
            f"media/{stem}{suffix}"
            for suffix in ("_closeup.jpg", "_final.png")
            if (MEDIA / f"{stem}{suffix}").exists()
        ),
        None,
    )
    found = results(runs)
    latest = found["latest"]
    result = describe_result(latest) if latest else "not run at default settings"
    links = []
    if (MEDIA / f"{stem}.mp4").exists():
        links.append(f"[video (MP4)](media/{stem}.mp4)")
    if (MEDIA / f"{stem}.gif").exists():
        links.append(f"[GIF](media/{stem}.gif)")
    relative = config_path(name).relative_to(ROOT).as_posix()
    links.append(f"[config](../{relative})")
    lines = [
        f'### <a id="{name}"></a>{title}',
        "",
        description,
        "",
        "| Design | Simulation |" if still else "| Design |",
        "|---|---|" if still else "|---|",
        (
            f"| ![{title} design](structures/{name}.png) | "
            f"![{title} in simulation]({still}) |"
            if still
            else f"| ![{title} design](structures/{name}.png) |"
        ),
        "",
        f"- **Bricks:** {info['bricks']} ({info['mix']}).",
        f"- **Layers:** {info['layers']}.",
        f"- **Bricks resting on two or more bricks:** {info['multi']}.",
        f"- **Weakest planned joint:** {info['weakest']} studs.",
        f"- **Runs at default settings:** {found['runs']}, "
        f"{found['completed']} completed. Latest: {result}.",
    ]
    for other in found["other"]:
        settings = describe_settings(other["changed"])
        lines.append(f"- **Also tried ({settings}):** {describe_result(other)}.")
    if name in NOTES:
        lines.append(f"- **Note:** {NOTES[name]}")
    if mechanism:
        lines.append(
            f"- **Failure mechanism:** {mechanism}. See "
            "[FAILURES.md](../experiments/ur5e_structures/FAILURES.md#mechanisms)."
        )
    lines += [f"- **Media:** {' · '.join(links)}", ""]
    return "\n".join(lines), found


def media_for(name: str) -> tuple[str | None, str | None]:
    """Find a structure's committed still and video, relative to docs/.

    Args:
        name: Structure name.

    Returns:
        (still, video) paths such as "media/bridge_closeup.jpg", or None.
    """
    stem = MEDIA_STEM.get(name, name)
    still = next(
        (
            f"media/{stem}{suffix}"
            for suffix in ("_closeup.jpg", "_final.png")
            if (MEDIA / f"{stem}{suffix}").exists()
        ),
        None,
    )
    video = f"media/{stem}.mp4" if (MEDIA / f"{stem}.mp4").exists() else None
    return still, video


def run_summary(run: dict) -> dict[str, object]:
    """Reduce a run to what the dashboard shows.

    Args:
        run: A run from `sweep_runs`.

    Returns:
        Outcome, connected and total bricks, and the stop reason in words.
    """
    return {
        "outcome": run["outcome"],
        "connected": run["connected"],
        "total": run["total"],
        "stop": STOP[run["failure_class"]],
        "run": run["run"],
    }


def index(all_runs: dict[str, list[dict]]) -> dict[str, object]:
    """Build docs/structures/index.json, which the dashboard reads.

    Args:
        all_runs: Runs by structure from `sweep_runs`.

    Returns:
        Sections in order, and per structure its catalog text, media and
        results at the default settings and at other settings.
    """
    items = {}
    for name, (section, title, description, mechanism) in ENTRIES.items():
        found = results(all_runs.get(name, []))
        still, video = media_for(name)
        latest = found["latest"]
        items[name] = {
            "title": title,
            "section": section,
            "section_title": SECTIONS[section][0],
            "description": description,
            "tests": TESTS[name],
            "mechanism": mechanism,
            "note": NOTES.get(name, ""),
            "still": still,
            "video": video,
            "default_runs": found["runs"],
            "default_completed": found["completed"],
            "latest": run_summary(latest) if latest else None,
            "attempts": [
                {"settings": describe_settings(r["changed"]), **run_summary(r)}
                for r in found["other"]
            ],
        }
    return {
        "sections": [
            {"key": key, "title": title, "blurb": blurb}
            for key, (title, blurb) in SECTIONS.items()
        ],
        "structures": items,
    }


def results_table(all_runs: dict[str, list[dict]]) -> list[str]:
    """Build the results table: what each structure tests and how it went.

    Args:
        all_runs: Runs by structure from `sweep_runs`.

    Returns:
        Markdown table lines (default settings only).
    """
    lines = [
        "| Structure | What it tests | Runs | Completed | What stopped it | "
        "Mechanism |",
        "|---|---|---|---|---|---|",
    ]
    for name, (section, title, _, mechanism) in ENTRIES.items():
        found = results(all_runs.get(name, []))
        if not found["runs"]:
            continue
        stops = sorted(
            {
                STOP[r["failure_class"]]
                for r in all_runs[name]
                if not r["changed"] and r["outcome"] != "completed"
            }
        )
        letter = mechanism.split(":")[0] if mechanism else ""
        lines.append(
            f"| [{title}](../../docs/STRUCTURES.md#{name}) | {TESTS[name]} | "
            f"{found['runs']} | {found['completed']} | {'; '.join(stops) or '—'} | "
            f"{letter or '—'} |"
        )
    return lines


def main() -> None:
    """Draw every design, write docs/STRUCTURES.md and the FAILURES.md table."""
    missing = [
        path.stem
        for path in STRUCTURES.glob("*.json")
        if path.stem not in ENTRIES and path.stem != "trials"
    ]
    if missing:
        raise ValueError(f"No catalog entry for {missing}")
    all_runs = sweep_runs()
    body = []
    summary = [
        "| Structure | Bricks | Runs | Completed | Latest |",
        "|---|---|---|---|---|",
    ]
    for section, (heading, blurb) in SECTIONS.items():
        body += [f"## {heading}", "", blurb, ""]
        summary.append(f"| **{heading}** | | | | |")
        for name, values in ENTRIES.items():
            if values[0] != section:
                continue
            text, found = entry(name, all_runs.get(name, []))
            body.append(text)
            bricks = len(json.loads(config_path(name).read_text())["part_names"])
            latest = found["latest"]
            status = latest["outcome"] if latest else "—"
            summary.append(
                f"| [{values[1]}](#{name}) | {bricks} | {found['runs']} | "
                f"{found['completed']} | {status} |"
            )
    header = [
        "# Structure catalog (simulation)",
        "",
        "Generated by `experiments/ur5e_structures/catalog.py`; do not edit by hand.",
        "",
        "Every structure the UR5e builds in Isaac Sim 6.2. Each entry shows:",
        "- the design, drawn from the config;",
        "- the structure in simulation at the end of its latest captured run;",
        "- its bricks and joints;",
        "- its results.",
        "",
        "**Runs** counts the sweep runs at the default settings: breakage on, 1 N",
        "press, 1 s release, gripper contacts logged. Runs at other settings are",
        "listed in each entry. Repeated runs of a structure give the same result,",
        "because the simulation is deterministic. These are simulation results",
        "judged by simulator ground truth; nothing here ran on hardware.",
        "",
        "The failures are explained in",
        "[FAILURES.md](../experiments/ur5e_structures/FAILURES.md), and every",
        "run's settings are in the",
        "[sweep summaries](../experiments/ur5e_structures/sweeps/README.md).",
        "",
        *summary,
        "",
    ]
    (DOCS / "STRUCTURES.md").write_text("\n".join(header + body))
    (DOCS / "structures" / "index.json").write_text(
        json.dumps(index(all_runs), indent=2) + "\n"
    )
    failures = STRUCTURES / "FAILURES.md"
    text = failures.read_text()
    start, end = "<!-- results:start -->", "<!-- results:end -->"
    if start in text and end in text:
        head, rest = text.split(start, 1)
        _, tail = rest.split(end, 1)
        table = "\n".join(results_table(all_runs))
        failures.write_text(f"{head}{start}\n{table}\n{end}{tail}")
    print(f"wrote docs/STRUCTURES.md with {len(ENTRIES)} structures")


if __name__ == "__main__":
    main()
