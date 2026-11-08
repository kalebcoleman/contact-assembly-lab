"""Write docs/STRUCTURES.md: every structure with its design, result and video.

For each structure this draws the design (`render.py`) to
`docs/structures/<name>.png` and writes one catalog entry:
- its description;
- brick counts and layers;
- how many bricks land on two or more supports;
- the weakest planned joint;
- the simulation picture and video when there are any;
- the latest simulation result at the default settings (breakage on, 1 N
  press) from `trials.json`.

All results are simulation.

    .venv/bin/python -m experiments.ur5e_structures.catalog
"""

import json
from collections import Counter
from pathlib import Path

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
    "figures": ("Figures", "Small animals and characters, one or two bricks a layer."),
    "complex": (
        "Complex builds that failed",
        "Attempts at harder structures. Each failure is a documented test case.",
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
        "B: release load on an 8-stud wall joint at the default 1 s release",
    ),
    "log_cabin": (
        "showcase",
        "Log cabin",
        "Courses alternate direction, and every brick above the first interlocks "
        "two corners below. It is planned on one corner and lands on both.",
        "",
    ),
    "human": (
        "figures",
        "Human",
        "Two legs two bricks high, hips, torso, shoulders and a head.",
        "",
    ),
    "robot": (
        "figures",
        "Robot",
        "Wide feet, a body across them, shoulders, a head and a hat.",
        "",
    ),
    "cat": ("figures", "Sitting cat", "A two-high body, chest, head and an ear.", ""),
    "giraffe": (
        "figures",
        "Giraffe",
        "A two-high leg, a body reaching forward, a two-high neck and a head with "
        "a snout.",
        "A: the neck is pressed onto the far end of the body and pries the 4-stud "
        "base joint",
    ),
    "tree": (
        "figures",
        "Tree",
        "A three-high 2x2 trunk under a crown of 2x6, 4x2 and 2x2 bricks.",
        "B: the trunk's 4-stud base joint breaks on the releases, transiently, "
        "then for good",
    ),
    "duck": (
        "figures",
        "Duck",
        "A foot, a long body, a neck at the front and a head with a beak.",
        "F: the 2x2 neck slipped out of the grasp during transfer",
    ),
    "table": (
        "complex",
        "Table",
        "Four 2x2 legs two bricks high under two 2x6 tops.",
        "C: legs 2 studs apart leave no room for the RG2 fingers to let go",
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
    "human": "human_breakage_on",
    "cantilever": "cantilever_failure",
}


def config_path(name: str) -> Path:
    """Return the config of a structure (the dog lives with its controller).

    Args:
        name: Structure name.

    Returns:
        Path to its JSON config.
    """
    return (
        ROOT / "experiments/ur5e_dog/dog.json"
        if name == "dog"
        else (STRUCTURES / f"{name}.json")
    )


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


def latest_trial(trials: list[dict], name: str) -> tuple[dict | None, int, int]:
    """Find a structure's latest simulation trial at the default settings.

    Args:
        trials: Entries of `trials.json`.
        name: Structure name.

    Returns:
        The latest breakage-on, 1 N trial with no other changed controller
        settings (or None), and the number of all simulation trials and of
        completed ones.
    """
    simulated = [
        t for t in trials if t["structure"] == name and t["kind"] == "simulation"
    ]
    default = [
        t
        for t in simulated
        if t["breakage"]
        and t.get("required_force_n") in (None, 1.0)
        and not t.get("controller_settings")
    ]
    latest = max(default, key=lambda t: t["date_utc"]) if default else None
    completed = sum(t["outcome"] == "completed" for t in simulated)
    return latest, len(simulated), completed


def entry(name: str, trials: list[dict]) -> tuple[str, str]:
    """Render one structure's catalog entry and draw its design.

    Args:
        name: Structure name.
        trials: Entries of `trials.json`.

    Returns:
        The Markdown entry and a one-line result for the summary table.
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
    latest, runs, completed = latest_trial(trials, name)
    if latest is None:
        result = "not run yet"
    elif latest["outcome"] == "completed":
        result = (
            f"completed, {latest['bricks_connected']}/{latest['bricks_total']} "
            "connected"
        )
    else:
        result = (
            f"failed, {latest['bricks_connected']}/{latest['bricks_total']} "
            "connected at the end"
        )
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
        f"- **Latest simulation (breakage on, 1 N press):** {result}.",
        f"- **Simulation runs:** {runs} ({completed} completed).",
    ]
    if name in NOTES:
        lines.append(f"- **Note:** {NOTES[name]}")
    if mechanism:
        lines.append(
            f"- **Failure mechanism:** {mechanism}. See "
            "[FAILURES.md](../experiments/ur5e_structures/FAILURES.md#mechanisms)."
        )
    lines += [f"- **Media:** {' · '.join(links)}", ""]
    status = result.split(",")[0] + (" (see note)" if name in NOTES else "")
    return "\n".join(lines), status


def main() -> None:
    """Draw every design and write docs/STRUCTURES.md."""
    trials = json.loads((STRUCTURES / "trials.json").read_text())
    missing = [
        path.stem
        for path in STRUCTURES.glob("*.json")
        if path.stem not in ENTRIES and path.stem != "trials"
    ]
    if missing:
        raise ValueError(f"No catalog entry for {missing}")
    body = []
    summary = [
        "| Structure | Section | Bricks | Latest simulation |",
        "|---|---|---|---|",
    ]
    for section, (heading, blurb) in SECTIONS.items():
        body += [f"## {heading}", "", blurb, ""]
        for name, values in ENTRIES.items():
            if values[0] != section:
                continue
            text, status = entry(name, trials)
            body.append(text)
            bricks = len(json.loads(config_path(name).read_text())["part_names"])
            summary.append(
                f"| [{values[1]}](#{name}) | {heading} | {bricks} | {status} |"
            )
    header = [
        "# Structure catalog (simulation)",
        "",
        "Generated by `experiments/ur5e_structures/catalog.py`; do not edit by hand.",
        "",
        "Every structure the UR5e builds in Isaac Sim 6.2. Each entry shows:",
        "- the design, drawn from the config;",
        "- the simulated build at the end of its latest captured run, if any;",
        "- the bricks and joints;",
        "- the latest simulation result at the default settings.",
        "",
        "These are simulation results judged by simulator ground truth. Nothing here",
        "ran on hardware. Per-run details are in the",
        "[sweep summaries](../experiments/ur5e_structures/sweeps/README.md), and",
        "the failure mechanisms are explained in",
        "[FAILURES.md](../experiments/ur5e_structures/FAILURES.md).",
        "",
        *summary,
        "",
    ]
    (DOCS / "STRUCTURES.md").write_text("\n".join(header + body))
    print(f"wrote docs/STRUCTURES.md with {len(ENTRIES)} structures")


if __name__ == "__main__":
    main()
