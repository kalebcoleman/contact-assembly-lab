"""Tests for the showcase specs, the design renderer and the catalog details."""

import json
import re
import tempfile
import unittest
from pathlib import Path

from experiments.ur5e_structures.catalog import (
    ENTRIES,
    built_lines,
    config_path,
    details,
)
from experiments.ur5e_structures.render import draw, footprints
from experiments.ur5e_structures.specs import SHOWCASE

STRUCTURES = Path(__file__).parent
ROOT = STRUCTURES.parents[1]


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


class BuiltLines(unittest.TestCase):
    """The catalog claims "Builds with" only for demonstrated builds."""

    def test_completed_run_says_builds_with(self) -> None:
        """A structure with a completed standard run builds with its settings."""
        found = {"runs": 1, "completed": 1, "latest": None, "other": []}
        lines = built_lines("column", found)
        self.assertEqual(lines, ["- **Builds with:** the controller defaults."])

    def test_no_completed_run_is_only_attempted(self) -> None:
        """Without a completed run the settings are attempted, not a build."""
        found = {"runs": 2, "completed": 0, "latest": None, "other": []}
        for name in ("table", "spiral_tower", "cantilever", "column"):
            text = "\n".join(built_lines(name, found))
            self.assertNotIn("Builds with", text, name)
            self.assertIn("Standard settings (attempted)", text, name)
            self.assertIn("Not built yet", text, name)

    def test_generated_catalog_matches_the_results(self) -> None:
        """Every "Builds with" in STRUCTURES.md has a completed standard run."""
        text = (ROOT / "docs/STRUCTURES.md").read_text()
        for section in text.split('### <a id="')[1:]:
            name = section.split('"', 1)[0]
            match = re.search(
                r"Runs at these settings:\*\* (\d+), (\d+) completed", section
            )
            assert match, name
            completed = int(match.group(2))
            self.assertEqual("**Builds with:**" in section, completed > 0, name)


def slug(heading: str) -> str:
    """Return GitHub's anchor for a Markdown heading."""
    text = re.sub(r"<[^>]+>", "", heading).strip().lower()
    text = re.sub(r"[^\w\- ]", "", text)
    return text.replace(" ", "-")


def anchors(path: Path) -> set[str]:
    """Return the fragment targets a Markdown file defines."""
    text = path.read_text()
    found = set(re.findall(r'<a id="([^"]+)"', text))
    for heading in re.findall(r"^#{1,6} (.+)$", text, flags=re.MULTILINE):
        found.add(slug(heading))
    return found


class Fragments(unittest.TestCase):
    """Links with a #fragment in the docs point at an existing anchor."""

    DOCS = [
        "README.md",
        "docs/STRUCTURES.md",
        "docs/USAGE.md",
        "experiments/ur5e_structures/FAILURES.md",
        "experiments/ur5e_structures/sweeps/README.md",
        "experiments/ur5e_assembly/README.md",
    ]

    def test_fragment_links_resolve(self) -> None:
        """Every [text](file.md#anchor) or (#anchor) link has its target."""
        broken = []
        for doc in self.DOCS:
            source = ROOT / doc
            for target, fragment in re.findall(
                r"\]\(([^)#\s]*)#([^)\s]+)\)", source.read_text()
            ):
                if target.startswith(("http://", "https://")):
                    continue
                path = (source.parent / target).resolve() if target else source
                if path.suffix != ".md" or fragment not in anchors(path):
                    broken.append(f"{doc}: {target}#{fragment}")
        self.assertEqual(broken, [])
