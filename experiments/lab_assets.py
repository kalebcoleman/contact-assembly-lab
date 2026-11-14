"""Find the lab assets: the UR5e with its `tool0` frame, the RG2 gripper and the bench.

They are not in Git. They live in `<asset root>/ur5e-dt/`, where the asset root is
the one twinsmith uses: `$TWINSMITH_ASSET_ROOT`, else
`$TWINSMITH_WORKSPACE/assets`, else `~/robotics-workspace/assets`. Only local
files are used; their hashes are pinned in
`experiments/ur5e_lego/assets/lab_assets_sha256.json`.
"""

from os import environ
from pathlib import Path


def lab_asset_dir() -> Path:
    """Return the folder that holds the lab assets.

    Returns:
        `<asset root>/ur5e-dt`, whether or not it exists.
    """
    root = environ.get("TWINSMITH_ASSET_ROOT", "").strip()
    if not root:
        workspace = environ.get("TWINSMITH_WORKSPACE", "").strip()
        root = str(Path(workspace or "~/robotics-workspace") / "assets")
    return Path(root).expanduser() / "ur5e-dt"


def lab_asset(reference: str) -> Path:
    """Return the local file for a lab asset reference.

    Args:
        reference: Path relative to the lab asset folder, as written in the
            workstation scene (for example `robot/ur5e.usd`).

    Returns:
        The file in the lab asset folder.

    Raises:
        FileNotFoundError: The file is not there.
    """
    path = lab_asset_dir() / reference
    if not path.is_file():
        raise FileNotFoundError(
            f"Lab asset {reference} not found at {path}; "
            "set TWINSMITH_ASSET_ROOT to the asset root that holds ur5e-dt/"
        )
    return path
