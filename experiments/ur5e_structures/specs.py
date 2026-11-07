"""Store-bought-brick structure library, validated with the dog recipe checker.

Bricks: 2x4, 2x6 and 2x2 (studs along x, y; height 3 plate units). `yaw` is the
quarter-turn count relative to the support. Same-layer bricks keep a gap of at
least 2 studs (16 mm) so the gripper never touches a neighbor while placing.
"""

import json
from pathlib import Path

from experiments.ur5e_dog.validate import validate

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
    # Legs two bricks high, then full-width 2x6 hips, torso and shoulders, 2x2 head.
    "human": [
        (A, None, (8, 8), 0),
        (A, None, (12, 8), 0),
        (A, 0, (0, 0), 0),
        (A, 1, (0, 0), 0),
        (W, 2, (0, 1), 0),
        (W, 4, (0, 0), 0),
        (W, 5, (0, 0), 0),
        (D, 6, (2, 0), 0),
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
    # Mixed 2x2, 2x4 and 2x6 bricks, each centered on the one below.
    "mixed_tower": [(D, None, (9, 9), 0)]
    + [(size, i, None, 0) for i, size in enumerate([A, W, B, D, A, W, D])],
}


def main() -> None:
    """Resolve offsets, validate every spec and write one JSON recipe per structure.

    Pickup positions are a placeholder grid (x -0.52/-0.43 m, y from -0.55 m in
    0.07 m steps) satisfying the validator's spacing and plate clearance.
    """
    for name, parts in SPECS.items():
        config = {
            "experiment_name": f"structure_{name}",
            "baseplate_xy_m": [-0.25, -0.33],
            "part_names": [f"{name}_{i}" for i in range(len(parts))],
            "brick_dimensions": [p[0] for p in parts],
            "brick_colors": [
                [200 - 12 * i, 30 + 10 * i, 30] for i in range(len(parts))
            ],
            "brick_positions_xy_m": [
                [round(-0.52 + 0.09 * (i // 5), 3), round(-0.55 + 0.07 * (i % 5), 3)]
                for i in range(len(parts))
            ],
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
        Path(__file__).with_name(f"{name}.json").write_text(
            json.dumps(config, indent=2) + "\n"
        )
        layers = max(o[2] for o in origins) // 3 + 1
        print(f"{name}: {len(parts)} bricks, {layers} layers valid")


if __name__ == "__main__":
    main()
