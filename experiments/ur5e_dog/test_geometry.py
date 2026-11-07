"""Regression tests for the dog recipe, independent of simulator imports."""

import json
import unittest
from copy import deepcopy
from pathlib import Path

from experiments.ur5e_dog.validate import validate


class GeometryTests(unittest.TestCase):
    """Reject invalid construction plans before any simulator is launched."""

    def test_recipe(self) -> None:
        """Accept ten parts at their expected stud/plate origins."""
        data = json.loads(Path(__file__).with_name("dog.json").read_text())
        origins = validate(data)
        self.assertEqual(len(origins), 10)
        self.assertEqual(origins[8], (6, 10, 12))

    def test_rejections(self) -> None:
        """Reject invalid order, collisions, detachment, bounds and height."""
        data = json.loads(Path(__file__).with_name("dog.json").read_text())
        cases = [
            ("support_bricks", 0, 2),
            ("placement_offsets", 1, [4, 4]),
            ("placement_offsets", 9, [0, -8]),
            ("placement_offsets", 0, [21, 4]),
            ("brick_dimensions", 0, [2, 4, 2]),
            ("brick_positions_xy_m", 8, [-0.34, -0.38]),
        ]
        for key, index, value in cases:
            with self.subTest(key=key, index=index):
                invalid = deepcopy(data)
                invalid[key][index] = value
                with self.assertRaises(ValueError):
                    validate(invalid)


if __name__ == "__main__":
    unittest.main()
