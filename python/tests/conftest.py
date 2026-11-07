"""Shared pytest support."""

from isaacsim import SimulationApp

isaacsim_app = SimulationApp({"headless": True})

import bricksim  # noqa: E402, F401
