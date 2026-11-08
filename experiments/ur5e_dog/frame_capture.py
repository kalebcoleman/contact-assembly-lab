"""Write rendered viewport frames to disk while a run plays, for demo videos.

Frames follow simulation time (one every `every` app updates), so a video made
from them plays smoothly regardless of how fast the machine renders.
"""

from asyncio import sleep
from pathlib import Path

import numpy as np
from isaacsim.core.utils.viewports import set_camera_view
from omni.kit.app import get_app
from omni.kit.viewport.utility import capture_viewport_to_file, get_active_viewport
from omni.timeline import get_timeline_interface
from omni.usd import get_context


class FrameCapture:
    """Capture the active viewport every `every` app updates once playing.

    From the first update with the timeline playing, the viewport renders at
    `resolution`; before each frame the camera is set to `eye` looking at `target`
    (world meters) and the selection is cleared so no outline is drawn. Frames
    are `frame_000000.png`, ... in `directory`.
    """

    def __init__(
        self,
        directory: Path,
        every: int,
        eye: np.ndarray,
        target: np.ndarray,
        resolution: tuple[int, int],
    ) -> None:
        """Subscribe to app updates.

        Args:
            directory: Output folder, created if missing.
            every: Capture one frame per this many app updates.
            eye: Camera position in world meters.
            target: Point the camera looks at, world meters.
            resolution: Render resolution (width, height) in pixels.
        """
        directory.mkdir(parents=True, exist_ok=True)
        self.directory = directory
        self.every = every
        self.eye = eye
        self.target = target
        self.resolution = resolution
        self.updates = 0
        self.frames = 0
        self.started = False
        self.subscription = (
            get_app()
            .get_update_event_stream()
            .create_subscription_to_pop(self.on_update, name="dog frame capture")
        )

    def on_update(self, _event: object) -> None:
        """Set up the camera once playing, then capture every `every` updates.

        Args:
            _event: Kit update event (unused).
        """
        if not self.started:
            if not get_timeline_interface().is_playing():
                return
            get_active_viewport().resolution = self.resolution
            self.started = True
        self.updates += 1
        if self.updates % self.every:
            return
        # The run sets its own camera and selects prims after playing starts, so
        # re-apply both before every frame (the selection outline would show).
        set_camera_view(eye=self.eye, target=self.target)
        get_context().get_selection().clear_selected_prim_paths()
        capture_viewport_to_file(
            get_active_viewport(),
            str(self.directory / f"frame_{self.frames:06d}.png"),
        )
        self.frames += 1

    async def stills(
        self, shots: list[tuple[str, np.ndarray, np.ndarray]], settle_s: float = 1.0
    ) -> None:
        """Stop the periodic frames and save one still per camera view.

        Args:
            shots: (file stem, eye, target) per still, world meters; each is saved
                as `<stem>.png` in `<capture directory>_stills`, which is kept
                when the frames are deleted after encoding.
            settle_s: Seconds to wait after moving the camera, so the renderer
                converges, and again after each capture so the file is written.
        """
        self.subscription = None
        folder = self.directory.with_name(f"{self.directory.name}_stills")
        folder.mkdir(parents=True, exist_ok=True)
        for stem, eye, target in shots:
            set_camera_view(eye=eye, target=target)
            get_context().get_selection().clear_selected_prim_paths()
            await sleep(settle_s)
            capture_viewport_to_file(get_active_viewport(), str(folder / f"{stem}.png"))
            await sleep(settle_s)
