from isaacsim import SimulationApp

# Initialize Kit app window
simulation_app = SimulationApp({"headless": False})

import asyncio
import demos.demo_keyboard_teleop as demo

# Schedule the demo's coroutine on Kit's existing running event loop
teleop_task = asyncio.ensure_future(demo.main())

# Step the simulation and rendering loop
try:
    while simulation_app.is_running():
        simulation_app.update()
        if teleop_task.done():
            if teleop_task.exception():
                raise teleop_task.exception()
            break
except KeyboardInterrupt:
    pass
finally:
    simulation_app.close()
