# Ubuntu workstation setup

Configured on 2026-10-26.

## Machine

- Ubuntu 24.04.5, x86-64; Ryzen 7 9850X3D; 62 GiB usable RAM.
- NVIDIA RTX 5080, 16 GB VRAM; working NVIDIA driver 580.173.02.
- Approximately 423 GB free before dependency installation.
- Git, wget, unzip, and uv already installed.

## Environment

Python 3.11 is managed by uv in `.venv`. The environment includes Isaac Sim
5.1.0, Isaac Lab 2.3.2.post1, LeRobot 0.4.4, and the development dependencies.
The prebuilt native extension matches checkout `cbd5de3`; its SHA256 was verified
against `.prebuilt-native/manifest.env`. Pixi is only needed to rebuild C++.

The local dependency configuration selects PyTorch 2.7.0, torchvision 0.22.0,
and torchaudio 2.7.0 from the official CUDA 12.8 index. The previous CUDA 12.6
build failed a GPU calculation with `no kernel image is available` on this GPU.
OpenCV is pinned to 4.11.0.86 to retain NumPy 1.x compatibility.

To synchronize this configuration:

```bash
cd <repository root>
uv sync --locked
```

## Launch

Run these commands in a normal desktop terminal with network access:

```bash
cd <repository root>
uv run bricksim
```

For the assembly demo, close the first instance, then run:

```bash
uv run bricksim demos/demo_assembly.py
```

For this workstation's vertically stacked displays, use the desktop launcher:

```bash
./scripts/run_desktop.sh
```

It selects HDMI-0 as primary without changing monitor resolutions or positions,
then opens the assembly demo at 1280×720. Press **Play** in the left toolbar to
start motion: the demo deliberately pauses after scene setup. To open another
demo, pass its path to the launcher. This monitor selection is specific to this
workstation; rerunning the launcher reapplies it if the desktop resets it.

The first start may compile shaders and fetch assets. Review any NVIDIA license
prompt when it appears. Python modules that depend on Omniverse must run through
the launcher, rather than a plain Python interpreter.

`demos/demo_keyboard_teleop.py` provides keyboard interaction. Physical leader
teleoperation in `demos/demo_teleop.py` additionally needs a connected device,
its serial path, permissions, and device-specific LeRobot extras.

## Validation and limitations

- Launcher `--help` and native extension checksum passed.
- PyTorch 2.7.0+cu128 completed a CUDA tensor calculation on the RTX 5080;
  torchvision and torchaudio imported successfully.
- `uv sync --locked --dry-run` confirmed the environment needs no further changes.
- OpenCV image conversion and `rerun` import passed.
- Full simulator startup and the four-step assembly sequence passed headlessly.
  A temporary harness pressed Play after the demo's intentional pause, awaited
  completion, and verified all four adjacent brick pairs with
  `are_parts_connected`: `[True, True, True, True]`.
- Desktop rendering works with HDMI-0 as primary. The lower DP-4 monitor starts
  at y=2160, but X11 reports a work area ending at y=2192. Its 32-pixel usable
  height becomes negative after window decorations, producing height 65510 and
  Vulkan swapchain initialization failure. Selecting the upper monitor before
  startup avoids this GLFW work-area calculation. Explicit dimensions alone,
  fullscreen, borderless mode, and resizing after startup did not resolve it.
  A captured desktop frame is saved as `assembly-desktop.png`.
  The visible run completed all four assembly steps and verified all four
  connections, with no Vulkan swapchain errors. The viewport reported approximately 60 FPS.
- The optional ROS2 bridge reports startup failure and disables itself; this
  did not prevent the headless assembly from passing. ROS2 integration is untested.
- The upstream configuration deliberately overrides packaging and NumPy and
  excludes opencv-python-headless. `uv pip check` therefore reports metadata
  mismatches for Isaac Sim, Isaac Lab, and LeRobot. The installed rerun-sdk
  0.26.2 also declares NumPy >=2, conflicting with the simulator's NumPy 1.x
  requirement; importing it succeeds, but its recording workflows remain untested.
  Do not upgrade NumPy to 2 in this environment.
- Gurobi is installed for the stablelego extra. Larger optimization tasks may
  need a separate Gurobi license.
- No system driver changes were required. The existing untracked
  `run_teleop.py` was preserved.

## References

- [Upstream quickstart](https://github.com/intelligent-control-lab/BrickSim#quickstart)
- [Isaac Sim 5.1 requirements](https://docs.isaacsim.omniverse.nvidia.com/5.1.0/installation/requirements.html)
- [Official PyTorch version-specific installation commands](https://pytorch.org/get-started/previous-versions/)
