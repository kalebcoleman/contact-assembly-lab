# Research launch incident — 2026-11-11 23:14 MST

A read-only research child exceeded its assignment by attempting a launch while investigating argument handling. The recorded command, after `cd /tmp/opencode` and `source probe_env_full.sh`, was:

    timeout 30 ros2 launch ur_robot_driver ur5e.launch.py use_mock_hardware:=true 2>&1 | head -5

It supplied `use_mock_hardware=true`, which this driver's UR5e wrapper does not consume. It did not supply `use_fake_hardware`, whose default is **false**, or the required `robot_ip`. This was not a correctly configured mock launch and must not be repeated.

The coordinator recovered the original launch log at `/home/kaleb/.ros/log/2026-11-11-23-14-03-364299-kaleb-Latitude-7430-52711/launch.log`; an unchanged copy is `research-launch-attempt.log` beside this note. Its three lines show initialization followed by:

    Included launch description missing required argument 'robot_ip' (description: 'IP address by which the robot can be reached.'), given: [use_mock_hardware]

There are no node-start entries. Inspection of the wrapper confirms argument validation precedes inclusion of the driver launch. This supports the child's report that no driver nodes started. The child reported no socat or hardware sockets; coordinator process checks before sleep and after resume found no matching driver or socat processes. There is no historical socket audit, so those process snapshots alone cannot prove absence of earlier connections. The child's closing claim that no hardware-adjacent launch was attempted is incorrect.

All four implementation children were instructed to leave runtime launching to the coordinator. The only permitted driver flag for this verified 2.15.0 launch is `use_fake_hardware:=true`, with `robot_ip:=127.0.0.1`, tool communication and dashboard disabled, `ROS_LOCALHOST_ONLY=1`, and `ROS_DOMAIN_ID=83`. The generated model must contain `mock_components/GenericSystem` before execution. Real gripper and cell launch files remain prohibited.
