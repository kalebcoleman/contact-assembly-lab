"""Tests for the showcase specs, the design renderer and the catalog details."""

import json
import tempfile
import unittest
from pathlib import Path

from experiments.ur5e_structures.catalog import ENTRIES, config_path, details
from experiments.ur5e_structures.render import draw, footprints
from experiments.ur5e_structures.specs import SHOWCASE

STRUCTURES = Path(__file__).parent


class Showcase(unittest.TestCase):
    """The showcase configs place every brick where the absolute spec says."""

    def test_footprints_match_the_absolute_specs(self) -> None:
        """Generated offsets and yaws reproduce each footprint corner."""
        for name, parts in SHOWCASE.items():
            config = json.loads((STRUCTURES / f"{name}.json").read_text())
            corners = [(x0, y0) for x0, y0, *_ in footprints(config)]
            self.assertEqual(corners, [part[2] for part in parts], name)

    def test_spans_land_on_two_supports(self) -> None:
        """Deck, lintel and cabin courses rest on two bricks each."""
        expected = {"bridge": 1, "house": 1, "log_cabin": 6}
        for name, multi in expected.items():
            config = json.loads((STRUCTURES / f"{name}.json").read_text())
            self.assertEqual(details(config)["multi"], multi, name)


class Catalog(unittest.TestCase):
    """Every structure config has a catalog entry and renders."""

    def test_every_config_has_an_entry(self) -> None:
        """No structure is missing from the catalog."""
        names = {p.stem for p in STRUCTURES.glob("*.json")} - {"trials"}
        self.assertEqual(names - set(ENTRIES), set())

    def test_render_writes_a_png(self) -> None:
        """The design renderer writes an image for the house."""
        with tempfile.TemporaryDirectory() as folder:
            out = Path(folder) / "house.png"
            draw(json.loads(config_path("house").read_text()), out)
            self.assertGreater(out.stat().st_size, 10_000)


if __name__ == "__main__":
    unittest.main()
