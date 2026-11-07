"""Reject experiment settings that cannot describe the intended two-arm scene."""

import json
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("physics_dt_s", 0, "physics_dt_s must be finite and positive"),
        ("dynamic_friction", -0.1, "dynamic_friction must be finite and nonnegative"),
        ("static_friction", 0.1, "static_friction must be >= dynamic_friction"),
        ("robots", [], "requires exactly two robots"),
    ],
)
def test_invalid_physical_configuration(
    tmp_path: Path, field: str, value: float | list[object], message: str
) -> None:
    """Check that invalid experiment settings fail before Kit imports.

    Args:
        tmp_path: Temporary directory supplied by pytest.
        field: Configuration field to replace.
        value: Invalid value for that field.
        message: Expected explanatory error text.

    Returns:
        None.
    """
    root = Path(__file__).resolve().parents[2]
    config = json.loads((root / "research/configs/dual_ur5e.json").read_text())
    config[field] = value
    path = tmp_path / "invalid.json"
    path.write_text(json.dumps(config))
    result = subprocess.run(
        [
            sys.executable,
            str(root / "experiments/rise_dual_ur5e.py"),
            "--config",
            str(path),
            "--check",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert message in result.stderr
    assert "No module named" not in result.stderr
