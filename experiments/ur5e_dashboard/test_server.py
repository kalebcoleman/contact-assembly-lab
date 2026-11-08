"""Test recorded run summaries and the read-only HTTP interface."""

import zlib
from gzip import compress
from gzip import open as open_gzip
from hashlib import sha256
from http.client import HTTPConnection
from json import dumps, loads
from os import fsdecode
from pathlib import Path
from sys import getrecursionlimit
from tempfile import TemporaryDirectory
from threading import Thread
from unittest import TestCase, main
from unittest.mock import patch

from server import DashboardServer, RunCollection


class ResultsViewerTests(TestCase):
    """Exercise completed, interrupted, and incomplete recordings."""

    def setUp(self) -> None:
        """Create a small recording and its matching compressed evidence."""
        temporary_root = Path.cwd() / "outputs" / "ur5e-dashboard-tests"
        temporary_root.mkdir(parents=True, exist_ok=True)
        self.temporary = TemporaryDirectory(dir=temporary_root)
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.outputs = self.root / "outputs/ur5e_lego"
        self.evidence = self.root / "experiments/ur5e_lego/docs/evidence"
        self.outputs.mkdir(parents=True)
        self.evidence.mkdir(parents=True)
        metadata = {
            "kind": "metadata",
            "experiment": "stack_four",
            "created_utc": "2026-10-31T23:46:58+00:00",
            "source": "simulation",
            "gripper_joint_names": ["other", "rg2_gripper_joint"],
        }
        placement: dict[str, object] = {
            "stud_path": "/part0",
            "hole_path": "/part1",
            "position_error_m": [0.0003, 0.0004, 0.0017],
            "connected": False,
            "connected_offset_studs": None,
            "connected_yaw": None,
        }
        sample = {
            "kind": "sample",
            "simulation_elapsed_s": 1.0,
            "phase": "press",
            "brick_index": 1,
            "placements": [placement],
            "robot": {
                "position_rad": [0.1],
                "command_position_rad": [0.2],
                "velocity_rad_s": [0.3],
                "effort_nm": [0.4],
            },
            "gripper": {"position_rad": [1.0, 0.5], "command_position_rad": 0.6},
            "tool_pose_world": {"position_m": [0.1, 0.2, 0.3]},
            "tool_target_world": {"position_m": [0.4, 0.5, 0.6]},
            "assembly_settings": {"required_force_n": 1.0},
            "breakage_settings": {"enabled": False},
            "simulation_contacts": [{"projected_force_n": -2.0}],
        }
        connected = dict(placement)
        connected.update(connected=True, connected_offset_studs=[3, 8], connected_yaw=0)
        final_sample = dict(sample)
        final_sample.update(simulation_elapsed_s=2.0, placements=[connected])
        self.records = [
            metadata,
            sample,
            final_sample,
            {"kind": "end", "status": "completed"},
        ]
        self.content = "".join(dumps(record) + "\n" for record in self.records)
        self.raw = self.outputs / "sample-stack-four.jsonl"
        self.raw.write_text(self.content)
        with open_gzip(self.evidence / "ur5e-stack-four-run.jsonl.gz", "wt") as stream:
            stream.write(self.content)
        (self.evidence / "ur5e-stack-four-room.mp4").write_bytes(b"0123456789")
        (self.evidence / "ur5e-stack-four-result.png").write_bytes(b"image")
        self.collection = RunCollection(self.root)

    def test_completed_run_contains_recorded_values(self) -> None:
        """A complete run retains its event and simulated motion values."""
        runs = self.collection.refresh()
        self.assertEqual(len(runs), 1)
        run = runs[0]
        self.assertEqual(run["filename"], self.raw.name)
        self.assertEqual(
            (run["status"], run["samples"], run["duration_s"]), ("completed", 2, 2.0)
        )
        self.assertTrue(run["placements"][0]["connected"])
        self.assertEqual(run["events"][0]["error_m"], [0.0003, 0.0004, 0.0017])
        self.assertEqual(run["events"][0]["offset"], [3, 8])
        self.assertEqual(run["chart"][0]["gripper"], 0.5)
        self.assertEqual(run["chart"][0]["joint_commands"], [0.2])
        self.assertEqual(run["chart"][0]["tool_target"], [0.4, 0.5, 0.6])
        self.assertEqual(run["chart"][0]["force"], 2.0)
        self.assertIn("this run", run["video_label"])
        self.assertTrue(run["poster"])

    def test_incomplete_and_failed_runs_are_not_completed(self) -> None:
        """A partial final line and a failure end record stay distinct."""
        metadata = dict(self.records[0])
        metadata.update(experiment="stack", created_utc="2026-10-31T22:00:00+00:00")
        partial = self.outputs / "partial.jsonl"
        partial.write_text(
            dumps(metadata) + "\n" + dumps(self.records[1]) + '\n{"kind":'
        )
        metadata.update(created_utc="2026-10-31T22:01:00+00:00")
        failed = self.outputs / "failed.jsonl"
        failed.write_text(
            dumps(metadata)
            + "\n"
            + dumps(self.records[1])
            + "\n"
            + dumps({"kind": "end", "status": "interrupted_or_failed"})
            + "\n"
        )
        statuses = {run["filename"]: run["status"] for run in self.collection.refresh()}
        self.assertEqual(statuses[partial.name], "incomplete")
        self.assertEqual(statuses[failed.name], "interrupted_or_failed")

    def test_recordings_are_deduplicated_and_cache_refreshes(self) -> None:
        """Identical raw and compressed logs count once; changes are reread."""
        first = self.collection.refresh()
        self.assertEqual(len(first), 1)
        self.raw.write_text(self.content.replace('"completed"', '"stopped"'))
        second = self.collection.refresh()
        self.assertEqual(len(second), 1)
        self.assertEqual(second[0]["status"], "stopped")

    def test_empty_collection_has_no_invented_runs(self) -> None:
        """An empty experiment root produces an empty library."""
        self.assertEqual(RunCollection(self.root / "empty").refresh(), [])

    def test_truncated_gzip_does_not_disable_other_runs(self) -> None:
        """A truncated gzip with readable metadata is marked invalid in the API."""
        metadata = dict(self.records[0])
        metadata.update(experiment="stack", created_utc="2026-11-01T00:00:00+00:00")
        lines = [dumps(metadata)]
        for index in range(800):
            lines.append(
                dumps(
                    {
                        "kind": "sample",
                        "simulation_elapsed_s": index / 120,
                        "padding": sha256(str(index).encode()).hexdigest(),
                    }
                )
            )
        lines.append(dumps({"kind": "end", "status": "completed"}))
        archive = self.outputs / "truncated.jsonl.gz"
        compressed = compress(("\n".join(lines) + "\n").encode())
        archive.write_bytes(compressed[:-8])
        self.assertGreater(archive.stat().st_size, 8192)
        self.assertEqual(self.collection.read_metadata(archive)["experiment"], "stack")

        server = DashboardServer(0, self.collection)
        worker = Thread(target=server.serve_forever, daemon=True)
        worker.start()
        connection = HTTPConnection("127.0.0.1", server.server_port, timeout=5)
        try:
            connection.request("GET", "/api/runs")
            response = connection.getresponse()
            self.assertEqual(response.status, 200)
            runs = {run["filename"]: run for run in loads(response.read())}
            self.assertEqual(runs[archive.name]["status"], "invalid")
            self.assertEqual(runs[self.raw.name]["status"], "completed")

            connection.request("GET", f"/api/run?id={runs[archive.name]['id']}")
            response = connection.getresponse()
            self.assertEqual(response.status, 200)
            self.assertTrue(loads(response.read())["error"])

            archive.write_bytes(compressed)
            connection.request("GET", "/api/runs")
            response = connection.getresponse()
            self.assertEqual(response.status, 200)
            statuses = {
                run["filename"]: run["status"] for run in loads(response.read())
            }
            self.assertEqual(statuses[archive.name], "completed")
        finally:
            connection.close()
            server.shutdown()
            worker.join(timeout=5)
            server.server_close()

    def test_truncated_gzip_metadata_is_skipped_for_discovery_and_video(self) -> None:
        """An unreadable gzip header does not hide the valid uncompressed run."""
        archive = self.evidence / "ur5e-stack-four-run.jsonl.gz"
        archive.write_bytes(compress((dumps(self.records[0]) + "\n").encode())[:15])
        with self.assertRaises(EOFError):
            self.collection.read_metadata(archive)

        runs = self.collection.refresh()
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0]["status"], "completed")
        self.assertIn("different run", runs[0]["video_label"])

    def test_corrupt_gzip_does_not_disable_other_runs(self) -> None:
        """A decompression error after metadata marks only that run invalid."""
        metadata = dict(self.records[0])
        metadata.update(experiment="stack", created_utc="2026-11-01T00:00:00+00:00")
        content = dumps(metadata) + "\n" + (dumps(self.records[1]) + "\n") * 400
        compressor = zlib.compressobj(wbits=31)
        compressed = compressor.compress(content.encode())
        # Start a reserved deflate block after a valid metadata and sample prefix.
        compressed += compressor.flush(zlib.Z_SYNC_FLUSH) + b"\x07"
        archive = self.outputs / "corrupt.jsonl.gz"
        archive.write_bytes(compressed)
        self.assertEqual(self.collection.read_metadata(archive)["experiment"], "stack")
        with self.assertRaises(zlib.error):
            self.collection.read_run(archive, metadata)

        server = DashboardServer(0, self.collection)
        worker = Thread(target=server.serve_forever, daemon=True)
        worker.start()
        connection = HTTPConnection("127.0.0.1", server.server_port, timeout=5)
        try:
            connection.request("GET", "/api/runs")
            response = connection.getresponse()
            self.assertEqual(response.status, 200)
            runs = {run["filename"]: run for run in loads(response.read())}
            self.assertEqual(runs[archive.name]["status"], "invalid")
            self.assertEqual(runs[self.raw.name]["status"], "completed")
        finally:
            connection.close()
            server.shutdown()
            worker.join(timeout=5)
            server.server_close()

    def test_corrupt_gzip_metadata_is_skipped_for_discovery_and_video(self) -> None:
        """Unreadable compressed metadata does not hide runs or claim a video match."""
        archive = self.evidence / "ur5e-stack-four-run.jsonl.gz"
        compressed = bytearray(compress(self.content.encode()))
        # Set the first deflate block type to the reserved value 0b11.
        compressed[10] = (compressed[10] & 0xF9) | 0x06
        archive.write_bytes(compressed)
        with self.assertRaises(zlib.error):
            self.collection.read_metadata(archive)

        runs = self.collection.refresh()
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0]["status"], "completed")
        self.assertIn("different run", runs[0]["video_label"])

    def test_malformed_records_do_not_disable_other_runs(self) -> None:
        """Malformed JSON records and nested fields are isolated in the API."""
        depth = max(10000, getrecursionlimit() + 100)
        deep = "[" * depth + "0" + "]" * depth
        records = {
            "null": "null",
            "array": "[]",
            "missing_kind": "{}",
            "invalid_kind": dumps({"kind": []}),
            "robot": dumps({"kind": "sample", "robot": []}),
            "robot_vector": dumps({"kind": "sample", "robot": {"position_rad": 1}}),
            "gripper_vector": dumps({"kind": "sample", "gripper": {"position_rad": 1}}),
            "tool_pose": dumps({"kind": "sample", "tool_pose_world": []}),
            "tool_target": dumps({"kind": "sample", "tool_target_world": [1]}),
            "placements": dumps({"kind": "sample", "placements": [None]}),
            "connected": dumps(
                {"kind": "sample", "placements": [{"connected": "false"}]}
            ),
            "contacts": dumps({"kind": "sample", "simulation_contacts": [None]}),
            "settings": dumps({"kind": "sample", "assembly_settings": []}),
            "assembly_enabled": dumps(
                {"kind": "sample", "assembly_settings": {"enabled": "false"}}
            ),
            "breakage_enabled": dumps(
                {"kind": "sample", "breakage_settings": {"enabled": "false"}}
            ),
            "phase": dumps({"kind": "sample", "phase": []}),
            "brick_index": dumps({"kind": "sample", "brick_index": "1"}),
            "boolean_time": dumps({"kind": "sample", "simulation_elapsed_s": True}),
            "end_status": dumps({"kind": "end", "status": []}),
            "overflow": '{"kind":"sample","simulation_elapsed_s":1e999}',
            "large_force": dumps(
                {
                    "kind": "sample",
                    "simulation_contacts": [{"projected_force_n": 10**400}],
                }
            ),
            "deep": '{"kind":"sample","extra":' + deep + "}",
        }
        filenames = []
        for index, (name, record) in enumerate(records.items()):
            metadata = dict(self.records[0])
            metadata.update(
                experiment="stack", created_utc=f"2026-11-01T00:00:{index:02d}+00:00"
            )
            archive = self.outputs / f"malformed-{name}.jsonl"
            archive.write_text(dumps(metadata) + "\n" + record + "\n")
            filenames.append(archive.name)

        server = DashboardServer(0, self.collection)
        worker = Thread(target=server.serve_forever, daemon=True)
        worker.start()
        connection = HTTPConnection("127.0.0.1", server.server_port, timeout=5)
        try:
            connection.request("GET", "/api/runs")
            response = connection.getresponse()
            self.assertEqual(response.status, 200)
            statuses = {
                run["filename"]: run["status"] for run in loads(response.read())
            }
            self.assertEqual(statuses[self.raw.name], "completed")
            for filename in filenames:
                with self.subTest(filename=filename):
                    self.assertEqual(statuses[filename], "invalid")
        finally:
            connection.close()
            server.shutdown()
            worker.join(timeout=5)
            server.server_close()

    def test_malformed_metadata_is_skipped_for_discovery_and_video(self) -> None:
        """Bad metadata cannot hide valid runs or imply a matching video."""
        depth = max(10000, getrecursionlimit() + 100)
        deep = "[" * depth + "0" + "]" * depth
        metadata_records = [
            "null",
            "[]",
            dumps({"kind": "metadata", "experiment": []}),
            dumps({"kind": "metadata", "created_utc": 123}),
            dumps({"kind": "metadata", "robot_joint_names": [None]}),
            dumps({"kind": "metadata", "gripper_joint_names": {}}),
            '{"kind":"metadata","config":{"value":1e999}}',
            '{"kind":"metadata","extra":' + deep + "}",
        ]
        for index, metadata in enumerate(metadata_records):
            (self.outputs / f"invalid-metadata-{index}.jsonl").write_text(
                metadata + "\n"
            )
        evidence = self.evidence / "ur5e-stack-four-run.jsonl.gz"
        with open_gzip(evidence, "wt") as stream:
            stream.write("null\n")

        missing_time = self.outputs / "missing-time.jsonl"
        missing_time.write_text(
            dumps(
                {
                    "kind": "metadata",
                    "experiment": "custom",
                    "created_utc": None,
                    "gripper_joint_names": None,
                }
            )
            + "\n"
            + dumps(self.records[1])
            + "\n"
            + dumps({"kind": "end", "status": "completed"})
            + "\n"
        )
        runs = self.collection.refresh()
        statuses = {run["filename"]: run["status"] for run in runs}
        self.assertEqual(
            statuses, {self.raw.name: "completed", missing_time.name: "completed"}
        )
        self.assertIn(
            "different run",
            next(run for run in runs if run["filename"] == self.raw.name)[
                "video_label"
            ],
        )

    def test_deleted_recording_does_not_disable_other_runs(self) -> None:
        """A log removed after metadata discovery does not hide other runs."""
        removed = self.outputs / "removed.jsonl"
        metadata = dict(self.records[0])
        metadata["created_utc"] = "2026-11-01T00:00:00+00:00"
        (self.evidence / "ur5e-stack-four-run.jsonl.gz").unlink()
        with (
            patch.object(Path, "glob", side_effect=[[removed, self.raw], [], []]),
            patch.object(
                self.collection,
                "read_metadata",
                side_effect=[metadata, self.records[0]],
            ),
        ):
            runs = self.collection.refresh()
        self.assertEqual([run["filename"] for run in runs], [self.raw.name])

    def test_symlink_loop_does_not_disable_other_runs(self) -> None:
        """A broken symbolic-link cycle does not hide a valid recording."""
        loop = self.outputs / "loop.jsonl"
        loop.symlink_to(loop.name)
        runs = self.collection.refresh()
        self.assertEqual([run["filename"] for run in runs], [self.raw.name])

    def test_non_utf8_filename_does_not_disable_other_runs(self) -> None:
        """A Linux filename containing non-UTF-8 bytes remains discoverable."""
        other = self.outputs / fsdecode(b"recording-\xff.jsonl")
        metadata = dict(self.records[0])
        metadata["created_utc"] = "2026-11-01T00:00:00+00:00"
        other.write_text(dumps(metadata) + "\n" + dumps(self.records[-1]) + "\n")
        runs = self.collection.refresh()
        self.assertEqual({run["filename"] for run in runs}, {other.name, self.raw.name})
        dumps(runs, allow_nan=False)

        server = DashboardServer(0, self.collection)
        worker = Thread(target=server.serve_forever, daemon=True)
        worker.start()
        connection = HTTPConnection("127.0.0.1", server.server_port, timeout=5)
        try:
            run = next(run for run in runs if run["filename"] == other.name)
            connection.request("GET", f"/download?id={run['id']}")
            response = connection.getresponse()
            self.assertEqual(response.status, 200)
            self.assertEqual(response.read(), other.read_bytes())
            self.assertIn(
                "filename*=UTF-8''recording-%3F.jsonl",
                response.getheader("Content-Disposition") or "",
            )
        finally:
            connection.close()
            server.shutdown()
            worker.join(timeout=5)
            server.server_close()

    def test_download_encodes_special_filename(self) -> None:
        """Unicode and line breaks cannot break or inject download headers."""
        other = self.outputs / "brick-雪\r\nX-Injected: yes.jsonl"
        metadata = dict(self.records[0])
        metadata["created_utc"] = "2026-11-01T00:00:00+00:00"
        other.write_text(dumps(metadata) + "\n" + dumps(self.records[-1]) + "\n")
        runs = self.collection.refresh()
        run = next(run for run in runs if run["filename"] == other.name)
        server = DashboardServer(0, self.collection)
        worker = Thread(target=server.serve_forever, daemon=True)
        worker.start()
        connection = HTTPConnection("127.0.0.1", server.server_port, timeout=5)
        try:
            connection.request("GET", f"/download?id={run['id']}")
            response = connection.getresponse()
            self.assertEqual(response.status, 200)
            self.assertEqual(response.read(), other.read_bytes())
            self.assertIsNone(response.getheader("X-Injected"))
            self.assertIn("%0D%0A", response.getheader("Content-Disposition") or "")
        finally:
            connection.close()
            server.shutdown()
            worker.join(timeout=5)
            server.server_close()

    def test_nonfinite_values_are_unavailable(self) -> None:
        """Invalid numeric measurements do not break the browser JSON response."""
        self.raw.write_text(
            self.content.replace('"position_rad": [0.1]', '"position_rad": [NaN]')
        )
        run = self.collection.refresh()[0]
        self.assertIsNone(run["chart"][0]["joints"][0])
        dumps(run, allow_nan=False)

    def test_chart_preserves_brief_peaks_and_contact_gaps(self) -> None:
        """A short force and effort spike remains visible between sampled points."""
        with self.raw.open("w") as stream:
            stream.write(dumps(self.records[0]) + "\n")
            for index in range(2000):
                sample = dict(self.records[1])
                sample["simulation_elapsed_s"] = index / 120
                sample["robot"] = {"effort_nm": [123.0 if index == 5 else 0.0]}
                sample["simulation_contacts"] = (
                    [{"projected_force_n": -9.0}] if index == 5 else []
                )
                stream.write(dumps(sample) + "\n")
            stream.write(dumps({"kind": "end", "status": "completed"}) + "\n")
        run = self.collection.refresh()[0]
        self.assertFalse(any(sample["force"] == 9.0 for sample in run["chart"]))
        force = run["chart_series"]["force"][0]
        self.assertIn([5 / 120, 9.0], force)
        self.assertTrue(any(value is None for _, value in force))
        effort = run["chart_series"]["joint_efforts"][0]
        self.assertIn([5 / 120, 123.0], effort)

    def test_new_compressed_run_can_use_a_matching_video(self) -> None:
        """A new compressed output discovers its matching named video."""
        metadata = dict(self.records[0])
        metadata.update(experiment="custom", created_utc="2026-11-01T01:00:00+00:00")
        compressed = self.outputs / "custom.jsonl.gz"
        with open_gzip(compressed, "wt") as stream:
            for record in [metadata, *self.records[1:]]:
                stream.write(dumps(record) + "\n")
        (self.outputs / "custom.mp4").write_bytes(b"video")
        run = next(
            item
            for item in self.collection.refresh()
            if item["filename"] == compressed.name
        )
        self.assertTrue(run["video"])
        self.assertIn("matching filename", run["video_label"])

    def test_other_run_does_not_claim_example_video_is_exact(self) -> None:
        """An experiment's example video is clearly labeled for another run."""
        other_metadata = dict(self.records[0])
        other_metadata["created_utc"] = "2026-11-01T01:00:00+00:00"
        other = self.outputs / "another.jsonl"
        other.write_text(
            "".join(
                dumps(record) + "\n" for record in [other_metadata, *self.records[1:]]
            )
        )
        run = next(
            item for item in self.collection.refresh() if item["filename"] == other.name
        )
        self.assertIn("different run", run["video_label"])

    def test_http_run_video_range_and_path_restriction(self) -> None:
        """The local API returns the run and only serves allowlisted files."""
        server = DashboardServer(0, self.collection)
        worker = Thread(target=server.serve_forever, daemon=True)
        worker.start()
        connection = HTTPConnection("127.0.0.1", server.server_port, timeout=5)
        try:
            connection.request("GET", "/api/runs")
            response = connection.getresponse()
            self.assertEqual(response.status, 200)
            run_id = loads(response.read())[0]["id"]
            connection.request("GET", f"/api/run?id={run_id}")
            response = connection.getresponse()
            self.assertEqual(loads(response.read())["samples"], 2)
            connection.request("GET", f"/download?id={run_id}")
            response = connection.getresponse()
            self.assertEqual(response.status, 200)
            self.assertEqual(response.read(), self.raw.read_bytes())
            connection.request("GET", f"/poster?id={run_id}")
            response = connection.getresponse()
            self.assertEqual(response.read(), b"image")
            connection.request(
                "GET", f"/video?id={run_id}", headers={"Range": "bytes=2-5"}
            )
            response = connection.getresponse()
            self.assertEqual(response.status, 206)
            self.assertEqual(response.getheader("Content-Range"), "bytes 2-5/10")
            self.assertEqual(response.read(), b"2345")
            connection.request(
                "GET", f"/video?id={run_id}", headers={"Range": "bytes=20-30"}
            )
            response = connection.getresponse()
            self.assertEqual(response.status, 416)
            response.read()
            connection.request("GET", "/video?id=../../etc/passwd")
            response = connection.getresponse()
            self.assertEqual(response.status, 404)
            response.read()
        finally:
            connection.close()
            server.shutdown()
            worker.join(timeout=5)
            server.server_close()

    def test_case_results_and_video_labels_match_only_their_recording(self) -> None:
        """Case results and own videos attach only to the exact recorded run."""
        created = "2026-11-03T12:00:00+00:00"
        for case_id, stamp, representative in (
            ("C01", created, None),
            ("C02", created, "C01"),
            ("C03", "2026-11-03T13:00:00+00:00", "C01"),
        ):
            case = {
                "id": case_id,
                "title": f"Test {case_id}",
                "expected_outcome": "connected",
            }
            if representative:
                case["representative_video_case"] = representative
            metadata = dict(self.records[0])
            metadata.update(
                experiment=f"case_{case_id}",
                created_utc=stamp,
                config={"assembly": {"case": case}},
            )
            lines = [metadata, *self.records[1:]]
            (self.outputs / f"{case_id}.jsonl").write_text(
                "".join(dumps(record) + "\n" for record in lines)
            )
        (self.evidence / "ur5e-case-C01-run.mp4").write_bytes(b"video")
        (self.evidence / "ur5e-case-C01-console.txt").write_text("console")
        suite = {
            "suite_id": "suite",
            "cases": [
                {
                    "id": case_id,
                    "created_utc": created,
                    "observed_outcome": "connected",
                    "as_predicted": True,
                    "console_log": f"ur5e-case-{case_id}-console.txt",
                }
                for case_id in ("C01", "C02", "C03")
            ],
        }
        (self.evidence / "ur5e-cases-suite.json").write_text(dumps(suite))

        runs = {run["filename"]: run for run in self.collection.refresh()}
        own = runs["C01.jsonl"]
        self.assertTrue(own["case_result"]["as_predicted"])
        self.assertIn("this C01 run", own["video_label"])
        self.assertTrue(own["case_log"])
        borrowed = runs["C02.jsonl"]
        self.assertIn("does not show this run", borrowed["video_label"])
        self.assertFalse(borrowed["case_log"])
        # C03's recording is not the one the suite measured.
        rerun = runs["C03.jsonl"]
        self.assertIsNone(rerun["case_result"])
        self.assertIsNone(rerun["case_suite"])
        self.assertIn("does not show this run", rerun["video_label"])

        server = DashboardServer(0, self.collection)
        worker = Thread(target=server.serve_forever, daemon=True)
        worker.start()
        connection = HTTPConnection("127.0.0.1", server.server_port, timeout=5)
        try:
            connection.request("GET", "/api/runs")
            listed = {
                run["case_id"]: run for run in loads(connection.getresponse().read())
            }
            self.assertTrue(listed["C01"]["case_as_predicted"])
            self.assertIsNone(listed["C03"]["case_observed"])
            connection.request("GET", f"/case-log?id={own['id']}")
            response = connection.getresponse()
            self.assertEqual(response.read(), b"console")
            connection.request("GET", f"/case-log?id={borrowed['id']}")
            response = connection.getresponse()
            response.read()
            self.assertEqual(response.status, 404)
        finally:
            connection.close()
            server.shutdown()
            worker.join(timeout=5)
            server.server_close()

    def test_malformed_case_suite_does_not_disable_runs(self) -> None:
        """An unreadable suite manifest leaves recordings available."""
        (self.evidence / "ur5e-cases-suite.json").write_text("{not json")
        self.assertEqual(self.collection.refresh()[0]["status"], "completed")

    def test_structures_report_layout_and_link_trials_to_runs(self) -> None:
        """Recipes become stud-grid layouts; trials link to their recordings."""
        dog = self.root / "experiments/ur5e_dog"
        dog.mkdir(parents=True)
        source = Path(__file__).resolve().parents[1] / "ur5e_dog/validate.py"
        (dog / "validate.py").write_text(source.read_text())
        structures = self.root / "experiments/ur5e_structures"
        structures.mkdir(parents=True)
        recipe = {
            "baseplate_xy_m": [-0.25, -0.33],
            "part_names": ["a", "b"],
            "brick_dimensions": [[2, 4, 3], [2, 4, 3]],
            "brick_colors": [[200, 30, 30], [30, 30, 200]],
            "brick_positions_xy_m": [[-0.52, -0.55], [-0.52, -0.48]],
            "support_bricks": [None, 0],
            "placement_offsets": [[9, 8], [2, 1]],
            "placement_yaws": [0, 1],
        }
        (structures / "turn.json").write_text(dumps(recipe))
        broken = dict(recipe, support_bricks=[None, None], placement_yaws=[0, 0])
        broken["placement_offsets"] = [[9, 8], [9, 8]]
        (structures / "broken.json").write_text(dumps(broken))
        trials = [
            {
                "structure": "turn",
                "kind": "simulation",
                "recording": self.raw.name,
                "bricks_connected": 2,
                "bricks_total": 2,
            },
            {"structure": "turn", "kind": "real", "recording": None},
        ]
        (structures / "trials.json").write_text(dumps(trials))
        runs = self.collection.refresh()
        by_name = {item["name"]: item for item in self.collection.structures()}
        turn = by_name["turn"]
        self.assertIsNone(turn["error"])
        self.assertEqual(turn["layers"], 2)
        # The quarter-turned 2x4 lies along x on the second layer.
        layout = [
            (b["x"], b["y"], b["layer"], b["width"], b["depth"]) for b in turn["bricks"]
        ]
        self.assertEqual(layout, [(9, 8, 0, 2, 4), (7, 9, 1, 4, 2)])
        self.assertEqual(
            [trial["run_id"] for trial in turn["trials"]], [runs[0]["id"], None]
        )
        self.assertIn("Solid collision", by_name["broken"]["error"])
        self.assertEqual(by_name["broken"]["bricks"], [])
        self.assertNotIn("trials", by_name)


if __name__ == "__main__":
    main()
