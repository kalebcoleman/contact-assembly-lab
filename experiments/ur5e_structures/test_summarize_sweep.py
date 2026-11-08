"""Tests for the sweep summarizer (no simulator needed)."""

import re
import tempfile
import unittest
from pathlib import Path

from experiments.ur5e_structures.summarize_sweep import (
    CONTROLLER_DEFAULTS,
    ROOT,
    classify_failure,
    describe_breaks,
    read_console,
    reconcile_with_recording,
)

PREFIX = "2026-11-08T00:00:00Z [1ms] "
PARTS = "/World/managed/Parts"


def joint(kind: str, step: int, conn: int, parent: int, child: int) -> str:
    """Return a BrickSim joint event log line."""
    return (
        f"{PREFIX}[Info] [bricksim] {kind} at t={step} Connection #{conn} at [-1]:"
        f"/World/managed/Conns/Conn_{conn} between {PARTS}/Part_{parent} #1 -> "
        f"{PARTS}/Part_{child} #0"
    )


class ControllerDefaults(unittest.TestCase):
    """The summarizer agrees with the controller."""

    def test_defaults_match_the_controller(self) -> None:
        """The summarizer's defaults are the ones the controller uses."""
        controller = (ROOT / "experiments/ur5e_assembly/controller.py").read_text()
        run = (ROOT / "experiments/ur5e_assembly/run.py").read_text()
        found = {
            name: float(value)
            for name, _, value in re.findall(
                r'"(ASSEMBLY_[A-Z_]+)": \("([a-z_]+)", ([0-9.e-]+)\)', controller
            )
        }
        found.update(
            (f"ASSEMBLY_{name}", float(value))
            for name, value in re.findall(
                r'setting\("([A-Z_]+)", "([0-9.e-]+)"\)', controller + run
            )
        )
        for name, default in CONTROLLER_DEFAULTS.items():
            if name == "ASSEMBLY_GRIPPER_CONTACT":
                self.assertIn(f'setting("GRIPPER_CONTACT", "{default}")', controller)
                continue
            self.assertEqual(found.get(name), float(default), name)


class Classify(unittest.TestCase):
    """Failure messages map to failure classes."""

    def test_classes(self) -> None:
        """Each controller failure message has its class."""
        cases = {
            None: "none",
            "Gripper touched /World/x during release of 2": "gripper_contact_abort",
            "No gripper clearance to release brick 4: nearest": "no_release_clearance",
            "Brick 2 detached from its support": "joint_lost",
            "Brick 7 did not complete the press: connected=False, held=0.00 s, "
            "brick=[-0.2510 -0.3464 -0.0630], tool=[-0.2469 -0.3460 0.1]": "not_seated",
            "Brick 3 did not complete the press: connected=False, held=0.00 s, "
            "brick=[-0.3588 -0.4135 -0.0774], tool=[-0.1030 -0.3200 0.1]": (
                "lost_from_grasp"
            ),
            "Isaac Sim assets root is unavailable": "other",
        }
        for message, expected in cases.items():
            self.assertEqual(classify_failure(message), expected, message)


class Breaks(unittest.TestCase):
    """Joint breaks are attributed from the console and utilization."""

    def console(self, lines: list[str]) -> dict:
        """Parse a synthetic console log.

        Args:
            lines: Console lines.

        Returns:
            The result of `read_console`.
        """
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "attempt-1.txt"
            path.write_text("\n".join(lines) + "\n")
            return read_console(path)

    def test_attribution(self) -> None:
        """Transient and lasting breaks, warnings and the 1e6 sentinel."""
        console = self.console(
            [
                "UR5e baseplate: finger profile (rad, mm) -0.45: inner",
                joint("Assembled", 10, 0, 0, 1),
                "UR5e baseplate: brick 1/2 connected offset=[0, 0]",
                joint("Assembled", 20, 1, 1, 2),
                "UR5e baseplate: brick 2/2 connected offset=[0, 0]",
                # Transient break, nothing logged before it.
                joint("Disassembled", 30, 1, 1, 2),
                joint("Assembled", 31, 2, 1, 2),
                f"{PREFIX}[Error] [bricksim] BreakageChecker: "
                "solver failed to converge",
                f"{PREFIX}[Warning] [bricksim] BreakageChecker: abnormally high slack "
                "fraction 22.1%",
                joint("Disassembled", 40, 0, 0, 1),
                "UR5e baseplate: gripper touched /World/x during retreat of brick 2",
            ]
        )
        self.assertTrue(console["event_log_complete"])
        self.assertEqual(console["gripper_contacts"], 1)
        self.assertEqual(
            console["solver_warnings"], {"not_converged": 1, "high_slack": 1}
        )
        conn = "/World/managed/Conns/Conn_{}"
        utilization = {
            conn.format(1): [(1.0, "release", 0.4), (1.1, "release", 0.6)],
            conn.format(0): [(0.5, "press", 2.0), (2.0, "release", 1e6)],
        }
        transient, lasting = describe_breaks(console["events"], utilization)
        self.assertEqual(transient["cause"], "sudden")
        self.assertTrue(transient["rejoined"])
        self.assertEqual(transient["peak_utilization_before_break"], 0.6)
        self.assertEqual(lasting["cause"], "overload seen, after solver warnings")
        self.assertFalse(lasting["rejoined"])
        self.assertEqual(lasting["solver_warnings"]["max_slack_pct"], 22.1)
        # The 2.0 at 0.5 s is outside the 0.5 s window before the last sample.
        self.assertEqual(lasting["peak_utilization_before_break"], 1e6)

    def test_truncated_log(self) -> None:
        """A connected brick without an Assembled event marks the log incomplete."""
        console = self.console(
            [
                joint("Assembled", 10, 0, 0, 1),
                "UR5e baseplate: brick 1/2 connected offset=[0, 0]",
                "UR5e baseplate: brick 2/2 connected offset=[0, 0]",
            ]
        )
        self.assertFalse(console["event_log_complete"])
        self.assertIsNone(console["gripper_contacts"])

    def test_recording_overrides_a_truncated_log(self) -> None:
        """A re-connection only the recording saw marks a break transient."""
        console = self.console(
            [
                joint("Assembled", 10, 0, 0, 1),
                "UR5e baseplate: brick 1/1 connected offset=[0, 0]",
                joint("Disassembled", 20, 0, 0, 1),
            ]
        )
        breaks = describe_breaks(console["events"], {})
        self.assertFalse(breaks[0]["rejoined"])
        primary = {
            "Part_0>Part_1": [
                (1.0, True, "press"),
                (2.0, False, "release"),
                (2.02, True, "release"),
                (5.0, False, "retreat"),
            ]
        }
        complete = reconcile_with_recording(breaks, console["events"], primary)
        self.assertFalse(complete)
        self.assertTrue(breaks[0]["rejoined"])
        self.assertEqual(breaks[0]["rejoined_source"], "recording")
        self.assertEqual(breaks[0]["broken_at_s"], 2.0)
        # The second disconnection was not logged: added from the recording.
        self.assertEqual(len(breaks), 2)
        self.assertEqual(breaks[1]["cause"], "not in console log")
        self.assertEqual(breaks[1]["phase"], "retreat")
        self.assertFalse(breaks[1]["rejoined"])


if __name__ == "__main__":
    unittest.main()
