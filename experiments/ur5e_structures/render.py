"""Draw a structure's design (its target layout) as a brick picture.

The picture is an oblique view from the front left and above, like the video
camera: the baseplate around the structure, then every brick as unit cells drawn
far to near, with outlines only at brick edges and studs on exposed tops. It is
the design from the config, not a simulation result.

    .venv/bin/python -m experiments.ur5e_structures.render <config.json> <out.png>
"""

import json
import math
import sys
from itertools import count
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from experiments.ur5e_dog.validate import validate
from matplotlib.patches import Polygon

# One brick is 9.6 mm tall and one stud 8 mm: height in stud units per layer.
LAYER_HEIGHT = 1.2
# Receding (y) axis drawn up and to the left, as seen from the front left.
DEPTH_X = -0.35
DEPTH_Y = 0.35
PLATE_COLOR = (0.80, 0.81, 0.80)
# Matplotlib draws all lines above all patches unless told otherwise; every
# shape gets the next z-order so later (nearer) shapes cover earlier ones.
ORDER = count()
EDGE_COLOR = (0.12, 0.12, 0.12)


def project(x: float, y: float, z: float) -> tuple[float, float]:
    """Project plate studs (x, y) and layer height z (stud units) to the page.

    Args:
        x: Stud x (to the right).
        y: Stud y (away from the viewer).
        z: Height in stud units.

    Returns:
        Page coordinates (u, v).
    """
    return x + DEPTH_X * y, z + DEPTH_Y * y


def shade(color: tuple[float, ...], factor: float) -> tuple[float, ...]:
    """Scale an RGB color (0-1) toward black.

    Args:
        color: RGB in 0-1.
        factor: Brightness factor.

    Returns:
        The shaded RGB.
    """
    return tuple(min(1.0, channel * factor) for channel in color)


def footprints(config: dict) -> list[tuple[int, int, int, int, int]]:
    """Return each brick's footprint (x0, y0, x1, y1) and layer, in plate studs.

    Args:
        config: Assembly config (validated with the dog recipe checker).

    Returns:
        (x0, y0, x1, y1, layer) per brick in build order.
    """
    origins = validate(config)
    yaws = config.get("placement_yaws", [0] * len(origins))
    turns: list[int] = []
    result = []
    for i, (size, origin) in enumerate(
        zip(config["brick_dimensions"], origins, strict=True)
    ):
        support = config["support_bricks"][i]
        turn = ((0 if support is None else turns[support]) + yaws[i]) % 4
        turns.append(turn)
        sx, sy = (size[0], size[1]) if turn % 2 == 0 else (size[1], size[0])
        result.append(
            (origin[0], origin[1], origin[0] + sx, origin[1] + sy, origin[2] // 3)
        )
    return result


def draw(config: dict, out: Path, width_px: int = 640) -> None:
    """Draw the design of `config` to a PNG.

    Args:
        config: Assembly config.
        out: Output PNG path.
        width_px: Image width in pixels.
    """
    bricks = footprints(config)
    colors = [tuple(c / 255 for c in color) for color in config["brick_colors"]]
    owner: dict[tuple[int, int, int], int] = {}
    for index, (x0, y0, x1, y1, layer) in enumerate(bricks):
        for x in range(x0, x1):
            for y in range(y0, y1):
                owner[(x, y, layer)] = index
    margin = 2
    px0 = max(0, min(b[0] for b in bricks) - margin)
    py0 = max(0, min(b[1] for b in bricks) - margin)
    px1 = min(20, max(b[2] for b in bricks) + margin)
    py1 = min(20, max(b[3] for b in bricks) + margin)
    top = max(b[4] for b in bricks) + 1

    fig, ax = plt.subplots(figsize=(6.4, 4.8), dpi=width_px / 6.4)
    ax.set_aspect("equal")
    ax.axis("off")
    plate = [
        project(px0, py0, 0),
        project(px1, py0, 0),
        project(px1, py1, 0),
        project(px0, py1, 0),
    ]
    ax.add_patch(
        Polygon(
            plate,
            closed=True,
            fc=PLATE_COLOR,
            ec=EDGE_COLOR,
            lw=0.6,
            zorder=next(ORDER),
        )
    )
    plate_front = [
        project(px0, py0, 0),
        project(px1, py0, 0),
        project(px1, py0, -0.4),
        project(px0, py0, -0.4),
    ]
    ax.add_patch(
        Polygon(
            plate_front,
            closed=True,
            fc=shade(PLATE_COLOR, 0.8),
            ec=EDGE_COLOR,
            lw=0.6,
            zorder=next(ORDER),
        )
    )
    for x in range(px0, px1):
        for y in range(py1 - 1, py0 - 1, -1):
            if (x, y, 0) not in owner:
                stud(ax, x + 0.5, y + 0.5, 0.0, PLATE_COLOR, small=True)

    # Far to near (y descending), right to left, bottom to top.
    cells = sorted(owner, key=lambda c: (-c[1], -c[0], c[2]))
    for x, y, layer in cells:
        index = owner[(x, y, layer)]
        color = colors[index]
        z0, z1 = layer * LAYER_HEIGHT, (layer + 1) * LAYER_HEIGHT

        def same(dx: int, dy: int, dz: int) -> bool:
            return owner.get((x + dx, y + dy, layer + dz)) == index

        faces = []
        if not same(0, -1, 0) and (x, y - 1, layer) not in owner:
            faces.append(
                (
                    [(x, y, z0), (x + 1, y, z0), (x + 1, y, z1), (x, y, z1)],
                    shade(color, 0.82),
                    [(0, 1), (2, 3)],
                    [
                        (1, 2) if not same(1, 0, 0) else None,
                        (3, 0) if not same(-1, 0, 0) else None,
                    ],
                )
            )
        if not same(-1, 0, 0) and (x - 1, y, layer) not in owner:
            faces.append(
                (
                    [(x, y, z0), (x, y + 1, z0), (x, y + 1, z1), (x, y, z1)],
                    shade(color, 0.62),
                    [(0, 1), (2, 3)],
                    [
                        (3, 0) if not same(0, -1, 0) else None,
                        (1, 2) if not same(0, 1, 0) else None,
                    ],
                )
            )
        if (x, y, layer + 1) not in owner:
            faces.append(
                (
                    [(x, y, z1), (x + 1, y, z1), (x + 1, y + 1, z1), (x, y + 1, z1)],
                    shade(color, 1.08),
                    [(0, 1) if not same(0, -1, 0) else None],
                    [
                        (1, 2) if not same(1, 0, 0) else None,
                        (2, 3) if not same(0, 1, 0) else None,
                        (3, 0) if not same(-1, 0, 0) else None,
                    ],
                )
            )
        for corners, fill, edges_a, edges_b in faces:
            points = [project(*corner) for corner in corners]
            ax.add_patch(
                Polygon(
                    points, closed=True, fc=fill, ec=fill, lw=0.3, zorder=next(ORDER)
                )
            )
            for edge in [*edges_a, *edges_b]:
                if edge is not None:
                    a, b = points[edge[0]], points[edge[1]]
                    ax.plot(
                        [a[0], b[0]],
                        [a[1], b[1]],
                        color=EDGE_COLOR,
                        lw=0.8,
                        solid_capstyle="round",
                        zorder=next(ORDER),
                    )
        if (x, y, layer + 1) not in owner:
            stud(ax, x + 0.5, y + 0.5, z1, color)

    corners = [
        project(px0, py0, -0.4),
        project(px1, py1, top * LAYER_HEIGHT + 0.4),
        project(px0, py1, top * LAYER_HEIGHT + 0.4),
        project(px1, py0, -0.4),
    ]
    us = [c[0] for c in corners]
    vs = [c[1] for c in corners]
    ax.set_xlim(min(us) - 0.5, max(us) + 0.5)
    ax.set_ylim(min(vs) - 0.5, max(vs) + 0.5)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, bbox_inches="tight", pad_inches=0.05, facecolor="white")
    plt.close(fig)


def stud(
    ax: plt.Axes,
    x: float,
    y: float,
    z: float,
    color: tuple[float, ...],
    small: bool = False,
) -> None:
    """Draw one stud (a short cylinder) centred on a top face.

    Args:
        ax: Axes to draw on.
        x: Stud centre x (plate studs).
        y: Stud centre y (plate studs).
        z: Top face height (stud units).
        color: Brick color.
        small: Draw a flatter, fainter stud (for the baseplate).
    """
    radius = 0.3
    height = 0.12 if small else 0.2
    ring = [
        (x + radius * math.cos(t), y + radius * math.sin(t))
        for t in (2 * math.pi * k / 20 for k in range(20))
    ]
    base = [project(px, py, z) for px, py in ring]
    cap = [project(px, py, z + height) for px, py in ring]
    edge = shade(color, 0.55) if not small else shade(color, 0.85)
    ax.add_patch(
        Polygon(base, closed=True, fc=shade(color, 0.7), ec="none", zorder=next(ORDER))
    )
    # Side: the band between the two ellipses, approximated by their hull.
    left = min(range(20), key=lambda k: base[k][0])
    right = max(range(20), key=lambda k: base[k][0])
    band = [base[left], base[right], cap[right], cap[left]]
    ax.add_patch(
        Polygon(band, closed=True, fc=shade(color, 0.75), ec="none", zorder=next(ORDER))
    )
    ax.add_patch(
        Polygon(
            cap,
            closed=True,
            fc=shade(color, 1.15),
            ec=edge,
            lw=0.4 if small else 0.6,
            zorder=next(ORDER),
        )
    )


def main() -> None:
    """Render the config given on the command line."""
    config = json.loads(Path(sys.argv[1]).read_text())
    draw(config, Path(sys.argv[2]))


if __name__ == "__main__":
    main()
