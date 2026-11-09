"""Choose an RG2 release opening that frees the held brick without reaching neighbours.

Geometry only (no Isaac Sim). Coordinates are meters in the grasp frame: `closing`
runs from the left to the right finger through the grasp centre (left finger
negative), `depth` runs along the approach axis from the grasp centre toward the
fingertips (downward when grasping from above). Angles are the RG2 actuated joint
in radians. The finger is wider near the palm than at the tip, so outer faces are
kept per depth bin of `DEPTH_BIN` meters starting at `DEPTH_START`.
"""

from dataclasses import dataclass

import numpy as np

DEPTH_START = -0.06
DEPTH_BIN = 0.002
DEPTH_BINS = 80


@dataclass(frozen=True)
class FingerFaces:
    """Finger faces along the closing axis at one RG2 joint angle.

    Attributes:
        angle: RG2 joint angle (rad).
        left_inner: Left finger face nearest the grasp centre (m, negative).
        right_inner: Right finger face nearest the grasp centre (m, positive).
        left_outer: Per depth bin, the left finger's farthest face from the centre
            (m, negative); NaN where the finger has no points.
        right_outer: Per depth bin, the right finger's farthest face (m, positive);
            NaN where the finger has no points.
    """

    angle: float
    left_inner: float
    right_inner: float
    left_outer: np.ndarray
    right_outer: np.ndarray


@dataclass(frozen=True)
class Neighbour:
    """A brick beside the held one, within reach of one finger.

    Attributes:
        side: -1 for the left finger's side, +1 for the right finger's side.
        distance: Distance from the grasp centre to the brick's nearest face (m).
        depth_range: Depth interval the brick occupies in the grasp frame (m).
    """

    side: int
    distance: float
    depth_range: tuple[float, float]


def outer_faces(
    points: np.ndarray, side: int
) -> np.ndarray:
    """Bin one finger's outer face by depth.

    Args:
        points: Finger collision points in the grasp frame, shape (N, 3) as
            (depth, closing, width) in meters.
        side: -1 for the left finger, +1 for the right finger.

    Returns:
        Per depth bin, the farthest closing coordinate on that side (m); NaN for
        bins without points.
    """
    bins = np.floor((points[:, 0] - DEPTH_START) / DEPTH_BIN).astype(int)
    faces = np.full(DEPTH_BINS, np.nan)
    for index in range(DEPTH_BINS):
        selected = points[bins == index, 1]
        if len(selected):
            faces[index] = selected.min() if side < 0 else selected.max()
    return faces


def faces_at(profile: list[FingerFaces], angle: float) -> FingerFaces:
    """Interpolate the finger faces linearly between measured angles.

    Args:
        profile: Faces measured in free air, sorted by increasing angle.
        angle: RG2 joint angle (rad) within the measured range.

    Returns:
        The interpolated finger faces at `angle`.
    """
    angles = [faces.angle for faces in profile]
    upper = int(np.clip(np.searchsorted(angles, angle), 1, len(profile) - 1))
    low, high = profile[upper - 1], profile[upper]
    weight = float(np.clip((angle - low.angle) / (high.angle - low.angle), 0.0, 1.0))

    def blend(first: np.ndarray | float, second: np.ndarray | float) -> np.ndarray:
        """Blend two values with the interpolation weight.

        Args:
            first: Value at the lower measured angle.
            second: Value at the upper measured angle.

        Returns:
            The interpolated value.
        """
        return (1.0 - weight) * np.asarray(first) + weight * np.asarray(second)

    return FingerFaces(
        angle,
        float(blend(low.left_inner, high.left_inner)),
        float(blend(low.right_inner, high.right_inner)),
        blend(low.left_outer, high.left_outer),
        blend(low.right_outer, high.right_outer),
    )


def neighbours(
    boxes: list[np.ndarray],
    center: np.ndarray,
    closing_axis: np.ndarray,
    width_axis: np.ndarray,
    finger_half_width: float,
) -> list[Neighbour]:
    """Bricks beside the held one that a finger could reach.

    Args:
        boxes: World axis-aligned boxes of the other bricks, each a 2x3 array
            [[x0, y0, z0], [x1, y1, z1]] in meters.
        center: Grasp centre in world coordinates (m); the approach axis is world -z.
        closing_axis: Unit horizontal vector from the left to the right finger.
        width_axis: Unit horizontal vector across the finger width.
        finger_half_width: Half the finger width along `width_axis` (m).

    Returns:
        One entry per brick that lies wholly on one side of the grasp centre and
        overlaps the finger width.
    """
    found = []
    for box in boxes:
        corners = np.array([[x, y] for x in box[:, 0] for y in box[:, 1]]) - np.asarray(
            center
        )[:2]
        along = corners @ np.asarray(closing_axis)[:2]
        across = corners @ np.asarray(width_axis)[:2]
        if across.max() <= -finger_half_width or across.min() >= finger_half_width:
            continue
        depth_range = (float(center[2] - box[1, 2]), float(center[2] - box[0, 2]))
        if along.min() > 0.0:
            found.append(Neighbour(1, float(along.min()), depth_range))
        elif along.max() < 0.0:
            found.append(Neighbour(-1, float(-along.max()), depth_range))
    return found


def reach(faces: FingerFaces, neighbour: Neighbour) -> float:
    """How far the finger on the neighbour's side extends over its depth range.

    Args:
        faces: Finger faces at one angle.
        neighbour: The neighbouring brick.

    Returns:
        Largest distance (m) of that finger's outer face from the grasp centre
        within the brick's depth range; -inf if the finger does not reach that deep.
    """
    first = int(np.floor((neighbour.depth_range[0] - DEPTH_START) / DEPTH_BIN))
    last = int(np.floor((neighbour.depth_range[1] - DEPTH_START) / DEPTH_BIN))
    outer = faces.right_outer if neighbour.side > 0 else -faces.left_outer
    window = outer[max(first, 0) : min(last, DEPTH_BINS - 1) + 1]
    window = window[~np.isnan(window)]
    return float(window.max()) if len(window) else float("-inf")


def release_opening(
    profile: list[FingerFaces],
    grasp_angle: float,
    nearby: list[Neighbour],
    target_clearance: float = 0.003,
    min_clearance: float = 0.001,
    margin: float = 0.002,
) -> tuple[float, float] | None:
    """Pick the RG2 angle that releases the brick without reaching a neighbour.

    The fingers open until each inner face has moved `target_clearance` away from
    the brick (its position at `grasp_angle`). If that would bring a finger within
    `margin` of a neighbour at the neighbour's height, the opening stops at that
    limit, as long as it still frees the brick by `min_clearance`.

    Args:
        profile: Free-air finger faces, sorted by increasing angle.
        grasp_angle: RG2 angle with the fingers closed on the brick (rad).
        nearby: Neighbouring bricks from `neighbours`.
        target_clearance: Desired gap between each inner face and the brick (m).
        min_clearance: Smallest acceptable gap (m).
        margin: Smallest acceptable gap between a finger and a neighbour (m).

    Returns:
        (angle in rad, achieved inner clearance in m), or None if no opening frees
        the brick by `min_clearance` while keeping `margin` from the neighbours.
    """
    closed = faces_at(profile, grasp_angle)
    best = None
    for angle in np.linspace(grasp_angle, profile[-1].angle, 400):
        faces = faces_at(profile, float(angle))
        if any(reach(faces, n) > n.distance - margin for n in nearby):
            break
        clearance = min(
            closed.left_inner - faces.left_inner,
            faces.right_inner - closed.right_inner,
        )
        best = (float(angle), clearance)
        if clearance >= target_clearance:
            break
    if best is None or best[1] < min_clearance:
        return None
    return best
