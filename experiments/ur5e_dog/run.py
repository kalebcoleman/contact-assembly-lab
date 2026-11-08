"""Run one simulated dog assembly; never connects to hardware."""

import json
from asyncio import sleep
from os import _exit, environ
from pathlib import Path
from sys import stderr, stdout
from traceback import print_exc

import numpy as np
from experiments.ur5e_dog.controller import main as assemble
from experiments.ur5e_dog.frame_capture import FrameCapture


def close_ups(config_path: str) -> list[tuple[str, np.ndarray, np.ndarray]]:
    """Camera views for close-up stills of the finished structure.

    Args:
        config_path: Repository-relative assembly config (for the baseplate).

    Returns:
        (file stem, eye, target) for a front three-quarter and a front view,
        aimed just above the baseplate centre, world meters.
    """
    plate = json.loads(Path(config_path).read_text())["baseplate_xy_m"]
    target = np.array([plate[0], plate[1], -0.05])
    return [
        ("closeup_three_quarter", target + np.array([-0.14, -0.24, 0.12]), target),
        ("closeup_front", target + np.array([0.02, -0.29, 0.07]), target),
    ]


async def main() -> None:
    """Run one dog attempt and exit the process: status 0 on success, 1 on failure.

    Kit otherwise stays alive after the run (scene reset on timeline stop).
    With DOG_CAPTURE_DIR set, rendered frames are written there for a video
    (DOG_CAPTURE_EVERY app updates apart, default 2), and the scene is held for
    DOG_HOLD_S after a failure as well, so the collapse is captured. After the
    hold, two close-up stills are saved to `<DOG_CAPTURE_DIR>_stills`.
    """
    config = environ.get("DOG_CONFIG", "experiments/ur5e_dog/dog.json")
    capture = None
    if environ.get("DOG_CAPTURE_DIR"):
        capture = FrameCapture(
            Path(environ["DOG_CAPTURE_DIR"]),
            int(environ.get("DOG_CAPTURE_EVERY", "2")),
            np.array([-0.36, -0.90, 0.25]),
            np.array([-0.37, -0.40, -0.04]),
            (1920, 1080),
        )
    try:
        await assemble(config, autoplay=True)
    except BaseException:
        print_exc()
        stderr.flush()
        if capture is not None:
            await sleep(float(environ.get("DOG_HOLD_S", "10")))
            await capture.stills(close_ups(config))
        _exit(1)
    # Keep the finished structure on screen for a screenshot or recording.
    await sleep(float(environ.get("DOG_HOLD_S", "10")))
    if capture is not None:
        await capture.stills(close_ups(config))
    stdout.flush()
    stderr.flush()
    _exit(0)
