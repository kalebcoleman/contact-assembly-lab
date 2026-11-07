"""Check stud-grid geometry without Isaac Sim. This is not a dynamics test."""

import json
from pathlib import Path


def validate(config: dict) -> list[tuple[int, int, int]]:
    """Validate ordered, yaw-zero brick boxes and return grid origins.

    Args:
        config: Dog JSON configuration. XY uses stud units (8 mm), Z uses plate
            units (3.2 mm); all parts must have height three plate units.

    Returns:
        Integer XYZ footprint minimum corners relative to the 20-by-20 anchored
        baseplate top. `placement_yaws` (optional, default zeros) gives each part's
        quarter turns relative to its support, counter-clockwise about +Z with the
        part's hole origin at `placement_offsets` on the support's stud grid.

    Raises:
        ValueError: Invalid lengths, unsupported parts, overlap, plate overflow
            or a source brick within 30 mm of the baseplate.
    """
    count = len(config["brick_dimensions"])
    for key in (
        "part_names",
        "brick_colors",
        "brick_positions_xy_m",
        "support_bricks",
        "placement_offsets",
    ):
        if len(config[key]) != count:
            raise ValueError(f"Length mismatch: {key}")
    yaws = config.get("placement_yaws", [0] * count)
    if len(yaws) != count or any(type(y) is not int or not 0 <= y < 4 for y in yaws):
        raise ValueError("placement_yaws must be one quarter-turn count (0-3) per part")

    def rotate(quarter_turns: int, x: int, y: int) -> tuple[int, int]:
        """Rotate a stud-grid vector counter-clockwise by quarter turns.

        Args:
            quarter_turns: Number of 90-degree counter-clockwise turns.
            x: Stud-grid x component.
            y: Stud-grid y component.

        Returns:
            The rotated (x, y) vector.
        """
        for _ in range(quarter_turns):
            x, y = -y, x
        return x, y

    # Per part: absolute hole-origin position (studs), accumulated quarter turns and
    # axis-aligned footprint (x0, y0, x1, y1). The plate is part -1.
    plate = ((0, 0), 0, (0, 0, 20, 20))
    placed = []
    origins = []
    for i, (size, parent, offset, yaw) in enumerate(
        zip(
            config["brick_dimensions"],
            config["support_bricks"],
            config["placement_offsets"],
            yaws,
            strict=True,
        )
    ):
        if len(size) != 3 or any(type(v) is not int or v <= 0 for v in size):
            raise ValueError(f"Invalid dimensions: {i}")
        if size[2] != 3 or len(offset) != 2 or any(type(v) is not int for v in offset):
            raise ValueError(f"Unsupported height or offset: {i}")
        if parent is not None and (type(parent) is not int or not 0 <= parent < i):
            raise ValueError(f"Invalid support order: {i}")
        parent_size = (
            [20, 20, 0] if parent is None else config["brick_dimensions"][parent]
        )
        (px, py), parent_turns, (bx0, by0, bx1, by1) = (
            plate if parent is None else placed[parent]
        )
        dx, dy = rotate(parent_turns, *offset)
        x, y = px + dx, py + dy
        turns = (parent_turns + yaw) % 4
        ex, ey = rotate(turns, size[0], size[1])
        footprint = (min(x, x + ex), min(y, y + ey), max(x, x + ex), max(y, y + ey))
        z = origins[parent][2] + parent_size[2] if parent is not None else 0
        overlap = max(0, min(bx1, footprint[2]) - max(bx0, footprint[0])) * max(
            0, min(by1, footprint[3]) - max(by0, footprint[1])
        )
        if overlap < 4:
            raise ValueError(f"Fewer than four supporting studs: {i}")
        if min(footprint[:2]) < 0 or max(footprint[2:]) > 20:
            raise ValueError(f"Outside baseplate footprint: {i}")
        for j, (_, _, previous) in enumerate(placed):
            if origins[j][2] == z and all(
                max(footprint[a], previous[a]) < min(footprint[a + 2], previous[a + 2])
                for a in (0, 1)
            ):
                raise ValueError(f"Solid collision between {j} and {i}")
            gap = max(
                footprint[0] - previous[2],
                previous[0] - footprint[2],
                footprint[1] - previous[3],
                previous[1] - footprint[3],
            )
            if origins[j][2] == z and gap < config.get("min_same_layer_gap_studs", 0):
                raise ValueError(f"Same-layer gap too small between {j} and {i}")
        placed.append(((x, y), turns, footprint))
        origins.append((footprint[0], footprint[1], z))
    for i, position in enumerate(config["brick_positions_xy_m"]):
        for j in range(i):
            previous = config["brick_positions_xy_m"][j]
            if all(
                abs(position[a] - previous[a])
                < 0.004
                * (config["brick_dimensions"][i][a] + config["brick_dimensions"][j][a])
                + 0.02
                for a in (0, 1)
            ):
                raise ValueError(f"Insufficient source spacing: {j}, {i}")
    plate = config["baseplate_xy_m"]
    for i, (position, size) in enumerate(
        zip(config["brick_positions_xy_m"], config["brick_dimensions"], strict=True)
    ):
        # A closing finger needs 30 mm of free table beside the plate's footprint.
        if all(
            abs(position[a] - plate[a]) < 0.08 + 0.004 * size[a] + 0.03 for a in (0, 1)
        ):
            raise ValueError(f"Source too close to baseplate: {i}")
    return origins


if __name__ == "__main__":
    data = json.loads(Path(__file__).with_name("dog.json").read_text())
    print(
        json.dumps(
            {"geometry_valid": True, "origins_stud_plate_units": validate(data)},
            indent=2,
        )
    )
