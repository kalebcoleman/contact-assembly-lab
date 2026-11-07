"""Run one simulation test case from `configs/cases/`."""

import sys

from experiments.ur5e_lego.rise_ur5e_baseplate import main as assemble
from omni.kit.app import get_app


async def main() -> None:
    """Assemble one case, print any failure, then quit Kit unless told to stay.

    Command-line arguments are the repository-relative case configuration and the
    optional `--manual` flag, which waits for Play and keeps Kit open for recording
    or inspection.

    Returns:
        None. A failure is reported on the console and is not an error for Kit.
    """
    manual = "--manual" in sys.argv
    try:
        await assemble(sys.argv[1], autoplay=not manual)
    except Exception as exc:
        print(f"UR5e case failure: {exc}", flush=True)
        raise
    finally:
        print("UR5e case finished", flush=True)
        if not manual:
            get_app().post_quit()
