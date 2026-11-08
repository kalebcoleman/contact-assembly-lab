#!/usr/bin/env python3
"""Check that this machine matches the shared setup.

Compares the git checkout with its upstream, installed package versions with
`uv.lock`, the native extension with its prebuilt manifest, and the UR5e lab
assets with the committed reference hashes. Prints one line per check and exits
with status 1 if any check fails. OS, GPU, driver and Python are reported only.

Run from the repository root:

    .venv/bin/python scripts/check_parity.py            # check this machine
    .venv/bin/python scripts/check_parity.py --record   # rewrite the reference hashes
"""

import json
import re
import subprocess
import sys
import tomllib
from argparse import ArgumentParser
from hashlib import file_digest
from importlib.metadata import PackageNotFoundError, version
from os import environ
from pathlib import Path
from platform import node, python_version
from runpy import run_path
from urllib.parse import unquote, urlparse

ROOT = Path(__file__).resolve().parent.parent
LAB_CONFIG = ROOT / "experiments/ur5e_lego/configs/ur5e_lego.json"
SCENE = ROOT / "experiments/ur5e_lego/assets/ur5e_workstation.usda"
REFERENCE = ROOT / "experiments/ur5e_lego/assets/lab_assets_sha256.json"
PREBUILT_MANIFEST = ROOT / ".prebuilt-native/manifest.env"
PACKAGES = (
    "isaacsim",
    "isaacsim-kernel",
    "torch",
    "torchvision",
    "torchaudio",
    "numpy",
    "lerobot",
    "opencv-python",
    "bricksim",
)


def sha256(path: Path) -> str:
    """Return the SHA-256 hex digest of a file.

    Args:
        path: File to hash.

    Returns:
        Lowercase hex digest of the file contents.
    """
    with path.open("rb") as stream:
        return file_digest(stream, "sha256").hexdigest()


def run(*command: str) -> str:
    """Run a command and return its stripped stdout.

    Args:
        *command: Program and arguments.

    Returns:
        Stdout, or an empty string if the program is missing or fails.
    """
    try:
        result = subprocess.run(command, capture_output=True, text=True, cwd=ROOT)
    except FileNotFoundError:
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""


def resolve_lab_assets(mcp_root: Path) -> tuple[dict[str, Path], list[str]]:
    """Resolve the scene's asset references with the isaac-mcp resolver.

    Args:
        mcp_root: isaac-mcp checkout that provides `asset_cache.py`.

    Returns:
        Local files keyed by path relative to the asset root (the four scene
        references plus every file beside the resolved robot), and the
        references that resolved to a remote URL instead of a local file.
    """
    resolve_uri = run_path(str(mcp_root / "exts/ur5e-dt/ur5e_dt/asset_cache.py"))[
        "resolve_uri"
    ]
    local: dict[str, Path] = {}
    remote: list[str] = []
    for reference in sorted(set(re.findall(r"@([^@\n]+)@", SCENE.read_text()))):
        uri = resolve_uri(reference)
        if not uri.startswith("file://"):
            remote.append(reference)
            continue
        path = Path(unquote(urlparse(uri).path))
        local[reference] = path
        if reference == "robot/ur5e.usd":
            for sibling in sorted(path.parent.rglob("*")):
                if sibling.is_file():
                    local[f"robot/{sibling.relative_to(path.parent)}"] = sibling
    return local, remote


def main() -> None:
    """Run all parity checks, or record the reference hashes with `--record`."""
    parser = ArgumentParser(description="Check this machine against the shared setup.")
    parser.add_argument("--record", action="store_true")
    record = parser.parse_args().record

    config = json.loads(LAB_CONFIG.read_text())
    mcp_root = Path(environ.get("ISAAC_MCP_ROOT", config["isaac_mcp_root"]))
    mcp_root = (ROOT / mcp_root.expanduser()).resolve()
    local_assets, remote_assets = resolve_lab_assets(mcp_root)

    if record:
        if remote_assets:
            sys.exit(f"Cannot record; resolved remotely: {remote_assets}")
        hashes = {name: sha256(path) for name, path in sorted(local_assets.items())}
        REFERENCE.write_text(json.dumps(hashes, indent=2) + "\n")
        print(f"Recorded {len(hashes)} asset hashes in {REFERENCE.relative_to(ROOT)}")
        return

    failures = 0

    def report(status: str, name: str, detail: str) -> None:
        nonlocal failures
        failures += status == "FAIL"
        print(f"{status:4} {name}: {detail}")

    # Git checkout.
    branch = run("git", "branch", "--show-current") or "(detached)"
    dirty = run("git", "status", "--porcelain", "--untracked-files=no")
    counts = run("git", "rev-list", "--left-right", "--count", "HEAD...@{upstream}")
    ahead, behind = counts.split() if counts else ("?", "?")
    head = run("git", "rev-parse", "--short", "HEAD")
    report(
        "PASS" if counts and not dirty and (ahead, behind) == ("0", "0") else "FAIL",
        "git",
        f"{branch} @ {head}, ahead {ahead} behind {behind}"
        + (", tracked files modified" if dirty else "")
        + (" (no upstream; run git fetch)" if not counts else ""),
    )

    # Installed packages against uv.lock.
    locked: dict[str, set[str]] = {}
    for package in tomllib.loads((ROOT / "uv.lock").read_text())["package"]:
        locked.setdefault(package["name"], set()).add(package.get("version", ""))
    for name in PACKAGES:
        try:
            installed = version(name)
        except PackageNotFoundError:
            report("FAIL", name, "not installed (run uv sync --locked)")
            continue
        ok = installed in locked.get(name, set())
        report(
            "PASS" if ok else "FAIL",
            name,
            f"{installed}" + ("" if ok else f", lock has {sorted(locked[name])}"),
        )

    # Native extension.
    natives = sorted((ROOT / "python/bricksim").glob("core.*.so"))
    if not natives:
        report("FAIL", "native", "python/bricksim/core.*.so missing")
    elif not PREBUILT_MANIFEST.exists():
        report(
            "INFO", "native", f"{natives[0].name}, no prebuilt manifest (local build)"
        )
    else:
        expected = dict(
            line.split("=", 1) for line in PREBUILT_MANIFEST.read_text().splitlines()
        )["SHA256"]
        actual = sha256(natives[0])
        report(
            "PASS" if actual == expected else "FAIL",
            "native",
            f"{natives[0].name} sha256 {actual[:12]}"
            + ("" if actual == expected else f", manifest {expected[:12]}"),
        )

    # Lab assets resolved through isaac-mcp.
    mcp_commit = run("git", "-C", str(mcp_root), "rev-parse", "--short", "HEAD")
    report(
        "INFO",
        "isaac-mcp",
        f"{mcp_root} @ {mcp_commit}",
    )
    for name in remote_assets:
        report("FAIL", f"asset {name}", "resolved to a remote URL, not a local file")
    reference = json.loads(REFERENCE.read_text())
    for name, expected in reference.items():
        path = local_assets.get(name)
        if path is None:
            report("FAIL", f"asset {name}", "missing")
        elif sha256(path) != expected:
            report("FAIL", f"asset {name}", f"hash differs ({path})")
    report("PASS", "assets", f"{len(reference)} reference files checked")
    # Files the scene does not reference cannot change the simulation.
    extra = sorted(set(local_assets) - set(reference))
    if extra:
        report("INFO", "assets", f"unreferenced files in the store: {extra}")

    # Reported, never compared.
    os_name = next(
        (
            line.split("=", 1)[1].strip('"')
            for line in Path("/etc/os-release").read_text().splitlines()
            if line.startswith("PRETTY_NAME=")
        ),
        "unknown",
    )
    gpu = run("nvidia-smi", "--query-gpu=name,driver_version", "--format=csv,noheader")
    report(
        "INFO",
        "machine",
        f"{node()}, {os_name}, python {python_version()}, {gpu or 'no GPU'}",
    )

    print(f"\n{'FAILED' if failures else 'OK'}: {failures} failing check(s)")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
