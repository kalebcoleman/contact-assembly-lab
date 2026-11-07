"""Stack three bricks with the lab UR5e."""

from experiments.ur5e_lego.rise_ur5e_baseplate import main as assemble


async def main() -> None:
    """Run the stacking configuration in the baseplate assembly scene.

    Returns:
        None. The simulation pauses after assembly; Stop resets the scene.
    """
    await assemble("experiments/ur5e_lego/configs/ur5e_stack.json")
