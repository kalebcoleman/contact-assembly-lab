"""Store-bought-brick structure library, validated with the dog recipe checker.

Bricks: 2x2, 2x4, 2x6, 2x8 and 2x10 (studs along x, y; height 3 plate units).
`yaw` is the quarter-turn count relative to the support. Same-layer bricks keep
a gap of at least 2 studs (16 mm) so the gripper never touches a neighbor while
placing.
"""

import json
from pathlib import Path

from experiments.ur5e_assembly.validate import validate

A = [2, 4, 3]  # 2x4 brick, long side along y
B = [4, 2, 3]  # 2x4 brick, long side along x (unrotated, a separate source part)
W = [6, 2, 3]  # 2x6 brick, long side along x
D = [2, 2, 3]  # 2x2 brick

# name: [(dimensions, support index or None, offset or None, yaw)]. An offset in
# studs is relative to the support's origin (plate corner if unsupported); None
# searches for the offset that centers the brick on its support. Order is build order.
SPECS = {
    "single": [(A, None, (9, 8), 0)],
    # Four 2x4 bricks stacked aligned: 8 studs of contact per joint.
    "column": [(A, None, (9, 8), 0)] + [(A, i, (0, 0), 0) for i in range(3)],
    "tower": [
        (A, None, (9, 8), 0),
        (B, 0, (-1, 1), 0),
        (A, 1, (1, -1), 0),
        (B, 2, (-1, 1), 0),
        (A, 3, (1, -1), 0),
        (B, 4, (-1, 1), 0),
    ],
    "l_corner": [
        (A, None, (6, 6), 0),
        (A, None, (6, 12), 0),
        (A, 0, (0, 2), 0),
        (B, 1, (0, 2), 0),
    ],
    "stairs": [
        (A, None, (9, 2), 0),
        (A, None, (9, 8), 0),
        (A, None, (9, 14), 0),
        (A, 0, (0, 2), 0),
        (A, 1, (0, 2), 0),
        (A, 2, (0, 2), 0),
        (A, 3, (0, 2), 0),
        (A, 4, (0, 2), 0),
    ],
    # Ten 2x4 bricks, each turned a quarter turn from the one below (a spiral).
    "spiral_tower": [(A, None, (9, 8), 0)] + [(A, i, None, 1) for i in range(9)],
    # Ten 2x4 bricks alternating +90 and -90 degrees: a cross-bonded tower.
    "cross_tower": [(A, None, (9, 8), 0)]
    + [(A, i, None, 1 if i % 2 == 0 else 3) for i in range(9)],
    # Four 2x2 legs two bricks high, two 2x6 tops bridging a 2-stud gap.
    "table": [
        (D, None, (6, 6), 0),
        (D, None, (10, 6), 0),
        (D, None, (6, 10), 0),
        (D, None, (10, 10), 0),
        (D, 0, (0, 0), 0),
        (D, 1, (0, 0), 0),
        (D, 2, (0, 0), 0),
        (D, 3, (0, 0), 0),
        (W, 4, (0, 0), 0),
        (W, 6, (0, 0), 0),
    ],
    # Ten 2x4 bricks stacked aligned: joint load grows with height.
    "column_10": [(A, None, (9, 8), 0)] + [(A, i, (0, 0), 0) for i in range(9)],
    # Each 2x4 shifted 2 studs along y (4-stud joints): the overturning moment on
    # the lower joints grows with every brick.
    "lean_6": [(A, None, (9, 4), 0)] + [(A, i, (0, 2), 0) for i in range(5)],
    # Alternating +2 / -2 stud shifts: shear at every joint, little net moment.
    "zigzag_6": [(A, None, (9, 6), 0)]
    + [(A, i, (0, 2 if i % 2 == 0 else -2), 0) for i in range(5)],
    # A 2x6 resting on one 2x2 by its end (4 studs), a 2x2 load at the free tip.
    "cantilever": [
        (D, None, (9, 9), 0),
        (D, 0, (0, 0), 0),
        (W, 1, (0, 0), 0),
        (D, 2, (4, 0), 0),
    ],
    # Mixed 2x2, 2x4 and 2x6 bricks; offsets auto-found (smallest valid, not centered).
    "mixed_tower": [(D, None, (9, 9), 0)]
    + [(size, i, None, 0) for i, size in enumerate([A, W, B, D, A, W, D])],
    # Figures, one brick per layer (side profiles), so no finger meets a neighbour.
    # Tree: three-high 2x2 trunk, crown of 2x6, 4x2 and 2x2.
    "tree": [
        (D, None, (9, 9), 0),
        (D, 0, (0, 0), 0),
        (D, 1, (0, 0), 0),
        (W, 2, (-2, 0), 0),
        (B, 3, (1, 0), 0),
        (D, 4, (1, 0), 0),
    ],
    # Break tests: each pushes one mechanism on purpose.
    # 4x2 bricks each shifted 1 stud along x (6-stud joints): the overturning
    # moment on the lowest joints grows with every layer.
    "lean_ladder": [(B, None, (6, 9), 0)] + [(B, i, (1, 0), 0) for i in range(7)],
    # Two-brick load at the free tip of a 2x6 resting by one end on a 2x2 column...
    "cantilever_tip2": [
        (D, None, (8, 9), 0),
        (D, 0, (0, 0), 0),
        (W, 1, (0, 0), 0),
        (D, 2, (4, 0), 0),
        (D, 3, (0, 0), 0),
    ],
    # ...and the same load over the support, as the control.
    "cantilever_root2": [
        (D, None, (8, 9), 0),
        (D, 0, (0, 0), 0),
        (W, 1, (0, 0), 0),
        (D, 2, (0, 0), 0),
        (D, 3, (0, 0), 0),
    ],
    # Ten 2x2 bricks: every joint has only 4 studs.
    "tower_2x2": [(D, None, (9, 9), 0)] + [(D, i, (0, 0), 0) for i in range(9)],
}

# Showcase builds, written in absolute plate studs: (dimensions, support index or
# None, footprint corner (x, y), turns). Turns 1 lays a brick along world x; the
# RG2 always closes across a brick's own x side, so a turned 2-wide brick is
# gripped by its long faces and gaps along a wall (doors, spans) leave the
# fingers free. The camera looks along +y, so these read from the side.
L6 = [2, 6, 3]  # 2x6 brick, gripped across its 2-stud width
L8 = [2, 8, 3]  # 2x8 brick
L10 = [2, 10, 3]  # 2x10 brick
Q = [6, 4, 3]  # 4x6 brick, as in the dog
L8X = [8, 2, 3]  # 2x8 brick gripped end to end (fingers on its short ends)
STONE = [150, 150, 158]
# (dimensions, support index or None, footprint corner, turns, RGB color)
AbsolutePart = tuple[list[int], int | None, tuple[int, int], int, list[int]]
SHOWCASE: dict[str, list[AbsolutePart]] = {
    # Corbel arch: each pier steps one stud inward, then a 2x10 deck closes the
    # arch by landing on both piers; two parapets finish the deck.
    "bridge": [
        (L6, None, (1, 9), 1, STONE),
        (L6, None, (13, 9), 1, STONE),
        (A, 0, (4, 9), 1, STONE),
        (A, 1, (12, 9), 1, STONE),
        (L10, 2, (5, 9), 1, [120, 78, 45]),
        (A, 4, (5, 9), 1, [175, 40, 35]),
        (A, 4, (11, 9), 1, [175, 40, 35]),
    ],
    # Facade with a doorway: two walls two courses high, a 2x10 lintel across
    # the door landing on both walls, a stepped gable roof and a chimney.
    "house": [
        (A, None, (2, 9), 1, [235, 225, 195]),
        (A, None, (10, 9), 1, [235, 225, 195]),
        (A, 0, (2, 9), 1, [235, 225, 195]),
        (A, 1, (10, 9), 1, [235, 225, 195]),
        (L10, 2, (3, 9), 1, [110, 70, 40]),
        (L8, 4, (4, 9), 1, [160, 30, 30]),
        (A, 5, (6, 9), 1, [160, 30, 30]),
        (D, 6, (8, 9), 0, [110, 110, 115]),
    ],
    # Steam locomotive: three wheels, a 2x10 chassis resting on all three, a
    # two-brick cab under an overhanging roof, a boiler and a tall smokestack.
    "locomotive": [
        (D, None, (3, 9), 1, [60, 60, 66]),
        (D, None, (7, 9), 1, [60, 60, 66]),
        (D, None, (11, 9), 1, [60, 60, 66]),
        (L10, 0, (3, 9), 1, [170, 30, 30]),
        (A, 3, (3, 9), 1, [30, 95, 55]),
        (A, 3, (9, 9), 1, [30, 95, 55]),
        (A, 4, (3, 9), 1, [30, 95, 55]),
        (D, 5, (11, 9), 1, [45, 45, 50]),
        (L6, 6, (2, 9), 1, [170, 30, 30]),
        (D, 7, (11, 9), 1, [45, 45, 50]),
    ],
    # Lighthouse: a 4x6 rock, a tower striped red and white, a lamp and a cap.
    "lighthouse": [
        (Q, None, (7, 8), 0, [110, 105, 100]),
        (A, 0, (8, 9), 1, [190, 30, 30]),
        (A, 1, (8, 9), 1, [240, 240, 235]),
        (A, 2, (8, 9), 1, [190, 30, 30]),
        (A, 3, (8, 9), 1, [240, 240, 235]),
        (D, 4, (9, 9), 1, [245, 200, 40]),
        (A, 5, (8, 9), 1, [190, 30, 30]),
    ],
    # Castle gate: two towers two courses high, a 2x10 lintel over the gate and
    # three battlements along the top.
    "castle_gate": [
        (A, None, (3, 9), 1, STONE),
        (A, None, (11, 9), 1, STONE),
        (A, 0, (3, 9), 1, STONE),
        (A, 1, (11, 9), 1, STONE),
        (L10, 2, (4, 9), 1, [95, 95, 102]),
        (D, 4, (4, 9), 1, STONE),
        (D, 4, (8, 9), 1, STONE),
        (D, 4, (12, 9), 1, STONE),
    ],
    # Four-legged table built with grip directions chosen for room: each 2x2 leg
    # is gripped across x, where the legs are 4 studs apart, and each 2x8 top is
    # gripped end to end, on its free ends. (The original table has 2-stud gaps
    # on both axes, so its last leg has no free grip axis.)
    "table_grip": [
        (D, None, (5, 6), 0, [150, 95, 50]),
        (D, None, (11, 6), 0, [150, 95, 50]),
        (D, None, (5, 10), 0, [150, 95, 50]),
        (D, None, (11, 10), 0, [150, 95, 50]),
        (D, 0, (5, 6), 0, [150, 95, 50]),
        (D, 1, (11, 6), 0, [150, 95, 50]),
        (D, 2, (5, 10), 0, [150, 95, 50]),
        (D, 3, (11, 10), 0, [150, 95, 50]),
        (L8X, 4, (5, 6), 0, [120, 75, 40]),
        (L8X, 6, (5, 10), 0, [120, 75, 40]),
    ],
    # Four-legged table with 4-stud gaps on both axes, every brick gripped across
    # its width: no finger has to fit a 2-stud gap, and no grip spans a 2x8.
    "table_wide": [
        (D, None, (5, 6), 0, [150, 95, 50]),
        (D, None, (11, 6), 0, [150, 95, 50]),
        (D, None, (5, 12), 0, [150, 95, 50]),
        (D, None, (11, 12), 0, [150, 95, 50]),
        (D, 0, (5, 6), 0, [150, 95, 50]),
        (D, 1, (11, 6), 0, [150, 95, 50]),
        (D, 2, (5, 12), 0, [150, 95, 50]),
        (D, 3, (11, 12), 0, [150, 95, 50]),
        (L8, 4, (5, 6), 1, [120, 75, 40]),
        (L8, 6, (5, 12), 1, [120, 75, 40]),
    ],
    # Trestle table: two slab legs of 2x4 bricks gripped end to end, so no finger
    # enters the gap between the legs, under a 4x6 top.
    "trestle_table": [
        (B, None, (6, 6), 1, [150, 95, 50]),
        (B, None, (10, 6), 1, [150, 95, 50]),
        (B, 0, (6, 6), 1, [150, 95, 50]),
        (B, 1, (10, 6), 1, [150, 95, 50]),
        (Q, 2, (6, 6), 0, [120, 75, 40]),
    ],
    # The 4-brick column with every brick turned to lie along x: the same 8-stud
    # joints, with the gripper rotated 90 degrees (a control for the house wall).
    "column_turned": [
        (A, None, (8, 9), 1, [200, 30, 30]),
        (A, 0, (8, 9), 1, [188, 40, 30]),
        (A, 1, (8, 9), 1, [176, 50, 30]),
        (A, 2, (8, 9), 1, [164, 60, 30]),
    ],
    # Log cabin: courses alternate direction and every brick above the first
    # course interlocks two corners below (planned on one, landing on both).
    "log_cabin": [
        (L8, None, (6, 6), 0, [125, 80, 45]),
        (L8, None, (12, 6), 0, [125, 80, 45]),
        (L8, 0, (6, 6), 1, [150, 100, 55]),
        (L8, 0, (6, 12), 1, [150, 100, 55]),
        (L8, 2, (6, 6), 0, [125, 80, 45]),
        (L8, 2, (12, 6), 0, [125, 80, 45]),
        (L8, 4, (6, 6), 1, [150, 100, 55]),
        (L8, 4, (6, 12), 1, [150, 100, 55]),
    ],
}


def rotate(quarter_turns: int, x: int, y: int) -> tuple[int, int]:
    """Rotate a stud vector counter-clockwise by quarter turns, as `validate` does.

    Args:
        quarter_turns: Number of 90-degree counter-clockwise turns.
        x: Stud x component.
        y: Stud y component.

    Returns:
        The rotated (x, y) vector.
    """
    for _ in range(quarter_turns % 4):
        x, y = -y, x
    return x, y


def from_absolute(
    parts: list[AbsolutePart],
) -> list[tuple[list[int], int | None, tuple[int, int], int]]:
    """Convert absolute footprints to the support-relative offsets and yaws.

    Args:
        parts: (dimensions, support, footprint corner, turns, color) in plate
            studs, turns 0 or 1.

    Returns:
        (dimensions, support, offset, yaw) entries as in `SPECS`.
    """
    origins: list[tuple[int, int, int]] = []
    result = []
    for size, support, (x0, y0), turns, _ in parts:
        # Hole origin: the footprint corner, shifted by the turned brick's extent.
        x, y = (x0 + size[1], y0) if turns == 1 else (x0, y0)
        px, py, parent_turns = (0, 0, 0) if support is None else origins[support]
        offset = rotate(4 - parent_turns, x - px, y - py)
        result.append((size, support, offset, (turns - parent_turns) % 4))
        origins.append((x, y, turns))
    return result


def packed_sources(sizes: list[list[int]], plate: list[float]) -> list[list[float]]:
    """Lay out pickup positions for long bricks, tighter along y than the grid.

    Bricks are gripped across x, so neighbours along x keep a 70 mm edge gap
    for the open fingers (the dog's spacing); along y, where the fingers are
    narrower than the gap, a 30 mm edge gap. Positions stay within 0.76 m of
    the robot base (the dog's farthest pickup) and clear of the baseplate.

    Args:
        sizes: Brick dimensions in build order.
        plate: Baseplate centre (x, y) in meters.

    Returns:
        One (x, y) pickup position per brick, in meters.
    """
    candidates = [
        (round(-0.56 + 0.005 * i, 3), round(-0.66 + 0.005 * j, 3))
        for i in range(53)
        for j in range(97)
    ]
    candidates = [
        c for c in candidates if 0.35 <= (c[0] ** 2 + c[1] ** 2) ** 0.5 <= 0.76
    ]
    candidates.sort(key=lambda c: abs(c[0] + 0.47) + abs(c[1] + 0.45))
    placed: list[tuple[float, float, list[int]]] = []
    for size in sizes:
        for x, y in candidates:
            half = (0.004 * size[0], 0.004 * size[1])
            if all(
                abs((x, y)[a] - plate[a]) < 0.08 + 0.004 * size[a] + 0.03
                for a in (0, 1)
            ):
                continue
            if any(
                all(
                    abs((x, y)[a] - (px, py)[a]) < 0.004 * (size[a] + other[a]) + 0.02
                    for a in (0, 1)
                )
                or (
                    abs(y - py) < half[1] + 0.004 * other[1] + 0.03
                    and abs(x - px) < half[0] + 0.004 * other[0] + 0.07
                )
                for px, py, other in placed
            ):
                continue
            placed.append((x, y, size))
            break
        else:
            raise ValueError(f"No pickup position for a {size} brick")
    return [[x, y] for x, y, _ in placed]


def grip_over_support(
    config: dict, finger_half_width_m: float = 0.010, margin_m: float = 0.002
) -> list[list[float]]:
    """Grasp offsets that put the grip (and so the press) over each support.

    The grip moves along the brick's own y axis (the fingers close across x)
    toward the centre of the area the brick shares with its support, as far as
    the fingers stay on the brick.

    Args:
        config: Assembly config.
        finger_half_width_m: Half the RG2 finger width along the brick (m).
        margin_m: Distance kept between a finger edge and the brick end (m).

    Returns:
        Per brick, [x, y] in meters in the brick's own frame at the source.
    """
    from experiments.ur5e_structures.render import footprints

    prints = footprints(config)
    yaws = config.get("placement_yaws", [0] * len(prints))
    turns: list[int] = []
    offsets = []
    for i, (x0, y0, x1, y1, _) in enumerate(prints):
        support = config["support_bricks"][i]
        turn = ((0 if support is None else turns[support]) + yaws[i]) % 4
        turns.append(turn)
        if support is None:
            offsets.append([0.0, 0.0])
            continue
        a0, b0, a1, b1, _ = prints[support]
        cx = (max(x0, a0) + min(x1, a1)) / 2 - (x0 + x1) / 2
        cy = (max(y0, b0) + min(y1, b1)) / 2 - (y0 + y1) / 2
        dx, dy = cx, cy
        for _ in range((4 - turn) % 4):
            dx, dy = -dy, dx
        half = 0.004 * config["brick_dimensions"][i][1]
        limit = max(0.0, half - finger_half_width_m - margin_m)
        offsets.append([0.0, round(max(-limit, min(limit, 0.008 * dy)), 4)])
    return offsets


# What a structure needs to build, found by the fix-attempt sweeps (see
# FAILURES.md): controller settings written into its config's "controller"
# block, and whether its half-supported bricks are gripped over their support.
NEEDS: dict[str, dict] = {
    "tree": {"controller": {"release_lift_m": 0.0005}},
    "tower": {"controller": {"release_lift_m": 0.0005}},
    "house": {"controller": {"release_lift_m": 0.0005}},
    "column_10": {"controller": {"release_ramp_s": 0.5}},
    "cross_tower": {"controller": {"release_ramp_s": 0.5}},
    "zigzag_6": {"controller": {"release_ramp_s": 0.5}},
    "lean_ladder": {"controller": {"release_ramp_s": 0.5}},
    "l_corner": {"controller": {"release_ramp_s": 0.5}},
    "castle_gate": {"controller": {"release_lift_m": 0.0005, "release_ramp_s": 0.5}},
    "mixed_tower": {"grip_over_support": True},
}


def apply_needs(name: str, config: dict) -> dict:
    """Add a structure's needed controller settings and grasp offsets.

    Args:
        name: Structure name.
        config: Its validated config.

    Returns:
        The config with its "controller" block and grasp offsets, if any.
    """
    needs = NEEDS.get(name, {})
    if "controller" in needs:
        config["controller"] = needs["controller"]
    if needs.get("grip_over_support"):
        config["grasp_offsets_m"] = grip_over_support(
            config, finger_half_width_m=0.004, margin_m=0.0
        )
    return config


def absolute_config(name: str, parts: list[AbsolutePart]) -> dict:
    """Build a validated config from absolute parts, as `main` does for showcases.

    Args:
        name: Structure name (sets the experiment name).
        parts: Absolute parts as in `SHOWCASE`.

    Returns:
        The assembly config.
    """
    relative = from_absolute(parts)
    config = {
        "experiment_name": f"structure_{name}",
        "baseplate_xy_m": [-0.25, -0.33],
        "part_names": [f"{name}_{i}" for i in range(len(parts))],
        "brick_dimensions": [p[0] for p in parts],
        "brick_colors": [p[4] for p in parts],
        "brick_positions_xy_m": packed_sources([p[0] for p in parts], [-0.25, -0.33]),
        "support_bricks": [p[1] for p in parts],
        "placement_offsets": [list(p[2]) for p in relative],
        "placement_yaws": [p[3] for p in relative],
        "min_same_layer_gap_studs": 2,
    }
    validate(config)
    return config


# Variant configs for fix attempts: name -> (structure, description, change).
ATTEMPTS = {
    "mixed_tower_grip_support": (
        "mixed_tower",
        "grip over the supported part",
        lambda config: {**config, "grasp_offsets_m": grip_over_support(config)},
    ),
    "mixed_tower_grip_support_full": (
        "mixed_tower",
        "grip 8 mm toward the support (fingertip over the brick end)",
        lambda config: {
            **config,
            "grasp_offsets_m": grip_over_support(
                config, finger_half_width_m=0.004, margin_m=0.0
            ),
        },
    ),
    "locomotive_short_stack": (
        "locomotive",
        "one-brick smokestack",
        lambda _: absolute_config("locomotive", SHOWCASE["locomotive"][:-1]),
    ),
    "locomotive_low_cab": (
        "locomotive",
        "one-brick cab under the roof, one-brick smokestack",
        lambda _: absolute_config(
            "locomotive",
            [
                *SHOWCASE["locomotive"][:6],
                (L6, 4, (2, 9), 1, [170, 30, 30]),
                (D, 5, (11, 9), 1, [45, 45, 50]),
            ],
        ),
    ),
    "castle_gate_two_battlements": (
        "castle_gate",
        "battlements over the towers only",
        lambda _: absolute_config(
            "castle_gate",
            SHOWCASE["castle_gate"][:6] + SHOWCASE["castle_gate"][7:],
        ),
    ),
}


def write_attempts() -> None:
    """Write each attempt's variant config to `attempts/<name>.json`."""
    folder = Path(__file__).with_name("attempts")
    folder.mkdir(exist_ok=True)
    for name, (structure, description, change) in ATTEMPTS.items():
        base = json.loads(Path(__file__).with_name(f"{structure}.json").read_text())
        variant = change(base)
        variant["variant_of"] = structure
        variant["variant"] = description
        validate(variant)
        (folder / f"{name}.json").write_text(json.dumps(variant, indent=2) + "\n")
        print(f"attempt {name}: {description}")


def main() -> None:
    """Resolve offsets, validate every spec and write one JSON recipe per structure.

    Pickup positions are a placeholder grid (x -0.52/-0.43 m, y from -0.55 m in
    0.07 m steps) satisfying the validator's spacing and plate clearance.
    """
    showcase = {name: from_absolute(parts) for name, parts in SHOWCASE.items()}
    for name, parts in {**SPECS, **showcase}.items():
        colors = (
            [p[4] for p in SHOWCASE[name]]
            if name in SHOWCASE
            else [[200 - 12 * i, 30 + 10 * i, 30] for i in range(len(parts))]
        )
        sources = (
            packed_sources([p[0] for p in parts], [-0.25, -0.33])
            if name in SHOWCASE
            else [
                [round(-0.52 + 0.09 * (i // 5), 3), round(-0.55 + 0.07 * (i % 5), 3)]
                for i in range(len(parts))
            ]
        )
        config = {
            "experiment_name": f"structure_{name}",
            "baseplate_xy_m": [-0.25, -0.33],
            "part_names": [f"{name}_{i}" for i in range(len(parts))],
            "brick_dimensions": [p[0] for p in parts],
            "brick_colors": colors,
            "brick_positions_xy_m": sources,
            "support_bricks": [p[1] for p in parts],
            "placement_offsets": [],
            "placement_yaws": [p[3] for p in parts],
            "min_same_layer_gap_studs": 2,
        }
        for i, (_, _, offset, _) in enumerate(parts):
            if offset is None:
                # Smallest offset (by distance from the support's origin) that
                # validates with at least 4 supporting studs.
                best = None
                for dx in range(-10, 11):
                    for dy in range(-10, 11):
                        trial = {
                            k: (v[: i + 1] if isinstance(v, list) else v)
                            for k, v in config.items()
                        }
                        trial["placement_offsets"] = [
                            *config["placement_offsets"],
                            [dx, dy],
                        ]
                        try:
                            validate(trial)
                        except ValueError:
                            continue
                        score = abs(dx) + abs(dy)
                        if best is None or score < best[0]:
                            best = (score, (dx, dy))
                if best is None:
                    raise ValueError(f"{name}: no valid offset for part {i}")
                offset = best[1]
            config["placement_offsets"].append(list(offset))
        origins = validate(config)
        config = apply_needs(name, config)
        Path(__file__).with_name(f"{name}.json").write_text(
            json.dumps(config, indent=2) + "\n"
        )
        layers = max(o[2] for o in origins) // 3 + 1
        print(f"{name}: {len(parts)} bricks, {layers} layers valid")


if __name__ == "__main__":
    main()
    write_attempts()
