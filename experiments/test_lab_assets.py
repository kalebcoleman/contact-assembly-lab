"""Check where the lab assets are looked up, without Isaac Sim."""

from os import environ
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase, main
from unittest.mock import patch

from experiments.lab_assets import lab_asset, lab_asset_dir

UNSET = {
    "TWINSMITH_ASSET_ROOT": "",
    "ISAAC_MCP_ASSET_ROOT": "",
    "TWINSMITH_WORKSPACE": "",
}


class LabAssetDirTest(TestCase):
    """The asset root follows twinsmith's order."""

    def test_twinsmith_root_wins(self) -> None:
        """`TWINSMITH_ASSET_ROOT` is used before its alias."""
        values = {**UNSET, "TWINSMITH_ASSET_ROOT": "/a", "ISAAC_MCP_ASSET_ROOT": "/b"}
        with patch.dict(environ, values):
            self.assertEqual(lab_asset_dir(), Path("/a/ur5e-dt"))

    def test_alias(self) -> None:
        """`ISAAC_MCP_ASSET_ROOT` is still read."""
        with patch.dict(environ, {**UNSET, "ISAAC_MCP_ASSET_ROOT": "/b"}):
            self.assertEqual(lab_asset_dir(), Path("/b/ur5e-dt"))

    def test_workspace(self) -> None:
        """Without a root, the workspace's `assets/` folder is used."""
        with patch.dict(environ, {**UNSET, "TWINSMITH_WORKSPACE": "/w"}):
            self.assertEqual(lab_asset_dir(), Path("/w/assets/ur5e-dt"))

    def test_default(self) -> None:
        """With nothing set, `~/robotics-workspace/assets` is used."""
        with patch.dict(environ, UNSET):
            expected = Path.home() / "robotics-workspace/assets/ur5e-dt"
            self.assertEqual(lab_asset_dir(), expected)


class LabAssetTest(TestCase):
    """Only local files resolve."""

    def test_found_and_missing(self) -> None:
        """A present file resolves; a missing one raises."""
        with TemporaryDirectory() as root:
            robot = Path(root, "ur5e-dt/robot/ur5e.usd")
            robot.parent.mkdir(parents=True)
            robot.touch()
            with patch.dict(environ, {**UNSET, "TWINSMITH_ASSET_ROOT": root}):
                self.assertEqual(lab_asset("robot/ur5e.usd"), robot)
                with self.assertRaises(FileNotFoundError):
                    lab_asset("workstation/vention.usd")


if __name__ == "__main__":
    main()
