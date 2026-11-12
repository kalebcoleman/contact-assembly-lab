# Validation — 2026-11-12

The coordinator independently ran these checks after integrating four DeepSeek
workstreams. The executor child had uncommitted code; its run was cancelled and
the coordinator finished the backend, live mock gates, launch integration and
regression fixes. No child test claim was accepted as parent verification.

## Environment and commands

Ubuntu 22.04, Python 3.10.12, ROS Humble. Official extracted packages:
UR driver 2.15.0, description 2.14.0, controller manager 2.54.3,
control_msgs 4.9.0 and ur_msgs 2.6.0. The overlay excludes socat.
Max risl_ur source at 011539abcacca4da7252227c6723f786e41317e3 was copied into
private build storage and built without changing the original checkout.

From the repository root, with the local dependency overlays sourced:

    colcon --log-base .agents/private-plans/ros-log build --base-paths ros2 --build-base .agents/private-plans/ros-build --install-base .agents/private-plans/ros-install
    source .agents/private-plans/ros-install/local_setup.bash
    colcon --log-base .agents/private-plans/ros-log test --base-paths ros2 --build-base .agents/private-plans/ros-build --install-base .agents/private-plans/ros-install
    colcon --log-base .agents/private-plans/ros-log test-result --test-result-base .agents/private-plans/ros-build --verbose
    uv tool run --offline ruff check ros2

Build passed; **46 tests, zero failures, errors or skips**. Logs:
[colcon-build.txt](colcon-build.txt), [colcon-test.txt](colcon-test.txt).
Ruff passed. Scoped ty passed using system Python 3.10 with the package, Humble
Python directories, extracted control_msgs and installed risl_ur search paths.
The simulator's Python 3.12 environment and native C++ were not changed or tested.

Independent offline checks: all 206 targets across 29 repository structures
matched the existing footprint validator at a 37-degree plate yaw. Max DH
`base → tool0` matched the official URDF at two joint poses (position residuals
below 7e-11 m). These establish nominal math agreement, not physical calibration.

## Official mock dry runs

Both launches used the package's hardcoded `use_fake_hardware=true`, loopback
IP, disabled tool communication/dashboard and localhost domain 83. Live
`list_hardware_components` reported `mock_components/GenericSystem`.
Each run terminated its own launch processes after collecting the evidence.
The final single-brick controller did not exit within the launch system's five-second
SIGINT grace period and was terminated by its SIGTERM escalation (exit -15);
that shutdown behavior is preserved in the launch log. No task process remains.

The single-brick run wrote 10 planned steps, zero executed steps, 133 joint
samples with zero displacement, and zero observed gripper-command publishers.
See [summary](single_brick-dry-summary.json), [steps](single_brick-dry-steps.jsonl),
[launch](single_brick-dry-launch.log), and the losslessly compressed
[joint trace](single_brick-dry-joints.jsonl.gz).

The three-brick run wrote 30 planned steps, zero executed steps, 1417 joint
samples with zero displacement, and zero observed gripper-command publishers.
See [summary](three_bricks-dry-summary.json), [steps](three_bricks-dry-steps.jsonl),
[launch](three_bricks-dry-launch.log), and the compressed
[joint trace](three_bricks-dry-joints.jsonl.gz).
Summaries contain the exact launch arguments and uncompressed trace SHA256.
Unit tests independently check dry-run command absence; sampled graph counts
alone would not prove absence of transient messages.

An earlier infrastructure-only probe verified the live robot description's sole
hardware plugin, active standard trajectory controller and fake-gripper query
response of 110 mm. Its [summary](initial-mock-verification.json) explicitly
separates that query from the assembly dry runs. No trajectory was commanded.

A final rerun exposed floating-point subtraction at the exact seating travel cap.
The comparison now uses `approach_z > target_z + cap`, matching planner addition
without enlarging the cap. The integration regression validates all three layers
and rejects a 1e-10 m excess; the final evidence above is from the corrected code.

## Limits and incident

These are plan rehearsals on a running official mock stack. They do not validate
moving trajectories, contact, force mode, physical seating, collision avoidance,
or lab calibration. The optional moving executor path remains unverified against
live action goals; hardware execution is disabled. Mock force requests are never
sent. Physical TCP/payload, camera/baseplate transforms, force sensing/limits and
release clearance remain unverified.

The [incident note](research-launch-incident.md) and
[recovered original log](research-launch-attempt.log) disclose the separate
research child's unauthorized launch attempt, wrong flag and argument-validation
failure. No historical socket audit exists; the report does not claim otherwise.
No Max repository was pushed, no network settings were changed, and no merge was
performed.
