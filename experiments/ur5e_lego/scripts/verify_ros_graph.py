#!/usr/bin/env python3
"""Sample a running simulator's ROS 2 graph from a separate client process.

Run with the system ROS 2 Python after sourcing ROS and the simulator's DDS
settings. Prints one JSON report to stdout. Rates are host-clock message rates;
TF translations are meters, quaternions are xyzw (ROS order), and clock values
are simulation seconds.

    python3 verify_ros_graph.py --seconds 12 --output report.json
"""

import json
import time
from argparse import ArgumentParser
from pathlib import Path

import rclpy
from rclpy.duration import Duration
from rclpy.parameter import Parameter
from rclpy.qos import DurabilityPolicy, QoSProfile
from rclpy.time import Time
from rosgraph_msgs.msg import Clock
from sensor_msgs.msg import JointState
from tf2_msgs.msg import TFMessage
from tf2_ros import Buffer, TransformListener


def main() -> None:
    """Sample the clock, joint-state and TF topics, then print a JSON report."""
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=float, default=12.0)
    parser.add_argument("--fixed-frame", default="world")
    parser.add_argument("--target-frame", default="wrist_3_link")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    rclpy.init()
    node = rclpy.create_node(
        "bricksim_ros_verifier",
        parameter_overrides=[Parameter("use_sim_time", value=True)],
    )
    clock_stamps: list[float] = []
    joint_messages: dict[str, list[JointState]] = {
        "/joint_states": [],
        "/rg2/joint_states": [],
    }
    tf_children: set[str] = set()
    tf_count = {"/tf": 0, "/tf_static": 0}
    tf_static_edges: set[tuple[str, str]] = set()

    def on_clock(message: Clock) -> None:
        """Store one simulation-time stamp in seconds.

        Args:
            message: Received /clock message.
        """
        clock_stamps.append(message.clock.sec + message.clock.nanosec * 1e-9)

    def on_tf(message: TFMessage) -> None:
        """Count one dynamic TF message and remember its child frames.

        Args:
            message: Received /tf message.
        """
        tf_count["/tf"] += 1
        tf_children.update(item.child_frame_id for item in message.transforms)

    def on_tf_static(message: TFMessage) -> None:
        """Count one static TF message and remember its edges.

        Args:
            message: Received /tf_static message.
        """
        tf_count["/tf_static"] += 1
        tf_static_edges.update(
            (item.header.frame_id, item.child_frame_id) for item in message.transforms
        )

    node.create_subscription(Clock, "/clock", on_clock, 50)
    for topic, messages in joint_messages.items():
        node.create_subscription(JointState, topic, messages.append, 50)
    node.create_subscription(TFMessage, "/tf", on_tf, 50)
    node.create_subscription(
        TFMessage,
        "/tf_static",
        on_tf_static,
        QoSProfile(depth=50, durability=DurabilityPolicy.TRANSIENT_LOCAL),
    )
    tf_buffer = Buffer()
    TransformListener(tf_buffer, node)

    start = time.monotonic()
    while time.monotonic() - start < args.seconds:
        rclpy.spin_once(node, timeout_sec=0.05)
    elapsed = time.monotonic() - start

    joints = {}
    for topic, messages in joint_messages.items():
        if not messages:
            joints[topic] = {"messages": 0}
            continue
        first, last = messages[0], messages[-1]
        joints[topic] = {
            "messages": len(messages),
            "rate_hz": len(messages) / elapsed,
            "names": list(last.name),
            "first_position_rad": list(first.position),
            "last_position_rad": list(last.position),
            "largest_change_rad": max(
                abs(after - before)
                for before, after in zip(first.position, last.position, strict=True)
            ),
        }
    transform = None
    try:
        stamped = tf_buffer.lookup_transform(
            args.fixed_frame, args.target_frame, Time(), Duration(seconds=2.0)
        )
    except Exception as exc:  # noqa: BLE001 - the failed lookup is the measurement.
        lookup_error = f"{type(exc).__name__}: {exc}"
    else:
        lookup_error = None
        translation = stamped.transform.translation
        rotation = stamped.transform.rotation
        transform = {
            "translation_m": [translation.x, translation.y, translation.z],
            "rotation_xyzw": [rotation.x, rotation.y, rotation.z, rotation.w],
            "stamp_s": stamped.header.stamp.sec + stamped.header.stamp.nanosec * 1e-9,
        }
    report = {
        "client": "separate rclpy process",
        "topics": sorted(name for name, _ in node.get_topic_names_and_types()),
        "publishers": {
            topic: [info.node_name for info in node.get_publishers_info_by_topic(topic)]
            for topic in ("/clock", "/joint_states", "/rg2/joint_states", "/tf")
        },
        "sampled_seconds": elapsed,
        "clock": {
            "messages": len(clock_stamps),
            "rate_hz": len(clock_stamps) / elapsed,
            "first_s": clock_stamps[0] if clock_stamps else None,
            "last_s": clock_stamps[-1] if clock_stamps else None,
            "monotonic": all(
                after >= before
                for before, after in zip(clock_stamps, clock_stamps[1:], strict=False)
            ),
        },
        "joint_states": joints,
        "tf": {
            "counts": tf_count,
            "dynamic_child_frames": sorted(tf_children),
            "static_edges": sorted(tf_static_edges),
            "lookup": {
                "fixed_frame": args.fixed_frame,
                "target_frame": args.target_frame,
                "transform": transform,
                "error": lookup_error,
            },
        },
    }
    text = json.dumps(report, indent=2)
    if args.output:
        args.output.write_text(text + "\n")
    print(text)
    node.destroy_node()
    rclpy.shutdown()


if __name__ == "__main__":
    main()
