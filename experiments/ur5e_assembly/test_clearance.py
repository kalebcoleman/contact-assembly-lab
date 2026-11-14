"""Check the RG2 release-opening geometry without Isaac Sim."""

from unittest import TestCase, main

import numpy as np
from experiments.ur5e_assembly.clearance import (
    DEPTH_BIN,
    DEPTH_START,
    FingerFaces,
    Neighbour,
    neighbours,
    outer_faces,
    release_opening,
)


def synthetic_finger(angle: float, side: int) -> np.ndarray:
    """Points of a finger that is 24 mm thick near the palm and 10 mm at the tip.

    Args:
        angle: RG2 angle (rad); the inner face is at 8 mm + 20 mm/rad from -0.35.
        side: -1 for the left finger, +1 for the right finger.

    Returns:
        Points (depth, closing, width) in meters, depth 0 to 65 mm.
    """
    inner = 0.008 + 0.02 * (angle + 0.35)
    points = []
    for depth in np.arange(0.0, 0.065, 0.001):
        thickness = 0.024 if depth < 0.045 else 0.010
        for closing in (inner, inner + thickness):
            points.append((depth, side * closing, 0.0))
    return np.array(points)


PROFILE = [
    FingerFaces(
        angle,
        -(0.008 + 0.02 * (angle + 0.35)),
        0.008 + 0.02 * (angle + 0.35),
        outer_faces(synthetic_finger(angle, -1), -1),
        outer_faces(synthetic_finger(angle, 1), 1),
    )
    for angle in (-0.45, -0.35, 0.0, 1.0)
]
TIP = (0.050, 0.065)


class ReleaseOpeningTests(TestCase):
    """Choose openings with and without neighbouring bricks."""

    def test_free_space_opens_to_target_clearance(self) -> None:
        """Without neighbours the fingers stop once 3 mm clear of the brick."""
        release = release_opening(PROFILE, -0.35, [])
        if release is None:
            self.fail("release is blocked")
        angle, clearance = release
        self.assertAlmostEqual(clearance, 0.003, delta=0.0002)
        self.assertAlmostEqual(angle, -0.35 + 0.15, delta=0.01)

    def test_neighbour_at_tip_height_limits_the_opening(self) -> None:
        """A neighbour 21.5 mm away at tip height allows 1.5 mm with 2 mm margin."""
        release = release_opening(PROFILE, -0.35, [Neighbour(1, 0.0215, TIP)])
        if release is None:
            self.fail("release is blocked")
        angle, clearance = release
        self.assertAlmostEqual(clearance, 0.0015, delta=0.0002)
        self.assertLess(angle, -0.35 + 0.15)

    def test_only_the_neighbours_height_counts(self) -> None:
        """The thick upper finger does not matter for a brick at tip height."""
        thick_reach = 0.008 + 0.024
        self.assertIsNotNone(
            release_opening(PROFILE, -0.35, [Neighbour(-1, thick_reach - 0.004, TIP)])
        )
        self.assertIsNone(
            release_opening(
                PROFILE, -0.35, [Neighbour(-1, thick_reach - 0.004, (0.0, 0.065))]
            )
        )

    def test_blocked_release_is_rejected(self) -> None:
        """A neighbour 20.5 mm away at tip height leaves less than 1 mm."""
        self.assertIsNone(
            release_opening(PROFILE, -0.35, [Neighbour(-1, 0.0205, TIP)])
        )


class NeighbourTests(TestCase):
    """Find bricks beside the fingers, with their depth in the grasp frame."""

    def test_sides_distances_and_depths(self) -> None:
        """Boxes across the finger width count; depth is measured downward."""
        center = np.array([0.0, 0.0, 0.10])
        boxes = [
            np.array([[0.024, -0.01, 0.0], [0.04, 0.01, 0.06]]),
            np.array([[-0.05, -0.01, 0.0], [-0.03, 0.01, 0.06]]),
            np.array([[0.012, 0.05, 0.0], [0.02, 0.07, 0.06]]),
        ]
        found = neighbours(
            boxes, center, np.array([1.0, 0.0, 0.0]), np.array([0.0, 1.0, 0.0]), 0.02
        )
        sides = [(n.side, round(n.distance, 6)) for n in found]
        self.assertEqual(sides, [(1, 0.024), (-1, 0.03)])
        np.testing.assert_allclose(found[0].depth_range, (0.04, 0.10))

    def test_depth_bins(self) -> None:
        """Outer faces land in the bin of their depth."""
        faces = outer_faces(synthetic_finger(-0.35, 1), 1)
        tip_bin = int((0.06 - DEPTH_START) / DEPTH_BIN)
        palm_bin = int((0.01 - DEPTH_START) / DEPTH_BIN)
        self.assertAlmostEqual(faces[tip_bin], 0.018)
        self.assertAlmostEqual(faces[palm_bin], 0.032)


if __name__ == "__main__":
    main()
