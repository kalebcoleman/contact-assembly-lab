"""Run one simulated dog assembly; never connects to hardware."""

from asyncio import sleep
from os import _exit, environ
from sys import stderr, stdout
from traceback import print_exc

from experiments.ur5e_dog.controller import main as assemble


async def main() -> None:
    """Run one dog attempt and exit the process: status 0 on success, 1 on failure.

    Kit otherwise stays alive after the run (scene reset on timeline stop).
    """
    try:
        await assemble(
            environ.get("DOG_CONFIG", "experiments/ur5e_dog/dog.json"), autoplay=True
        )
    except BaseException:
        print_exc()
        stderr.flush()
        _exit(1)
    # Keep the finished structure on screen for a screenshot or recording.
    await sleep(float(environ.get("DOG_HOLD_S", "10")))
    stdout.flush()
    stderr.flush()
    _exit(0)
