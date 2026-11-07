"""Serve a local, read-only viewer for recorded UR5e experiments."""

import zlib
from argparse import ArgumentParser
from gzip import open as open_gzip
from hashlib import sha256
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from json import JSONDecodeError, dumps, loads
from math import ceil, isfinite
from os import fsencode
from pathlib import Path
from urllib.parse import parse_qs, quote, urlsplit

ASSETS = Path(__file__).resolve().parent
NONFINITE_VALUES = {"NaN": None, "Infinity": None, "-Infinity": None}
CASE_SUITE = "ur5e-cases-suite.json"
VIDEO_EVIDENCE = (
    (
        "stack_four",
        "ur5e-stack-four-run.jsonl.gz",
        "ur5e-stack-four-room.mp4",
        "ur5e-stack-four-result.png",
        True,
    ),
    (
        "stack",
        "ur5e-stack-rejection-run.jsonl.gz",
        "ur5e-stack-rejection-room.mp4",
        None,
        True,
    ),
    (
        "stack",
        "ur5e-stack-run.jsonl.gz",
        "ur5e-stack-room.mp4",
        "ur5e-stack-trial-01.png",
        False,
    ),
    (
        "baseplate",
        "ur5e-baseplate-run.jsonl.gz",
        "ur5e-baseplate-assembly.mp4",
        "ur5e-baseplate-result.png",
        False,
    ),
    (
        "transfer",
        "ur5e-transfer-run.jsonl.gz",
        "ur5e-transfer-room.mp4",
        "ur5e-transfer-room-result.png",
        True,
    ),
)


class RunCollection:
    """Discover and summarize recordings beneath one experiment root."""

    def __init__(self, root: Path) -> None:
        """Set the recording root and initialize a file-version cache.

        Args:
            root: Root containing outputs and experiment evidence directories.
        """
        self.root = root.resolve()
        self.evidence = self.root / "experiments/ur5e_lego/docs/evidence"
        self.cache = {}
        self.runs = {}
        self.paths = {}
        self.videos = {}
        self.posters = {}
        self.case_logs = {}

    def read_metadata(self, path: Path) -> dict:
        """Read the first record from a JSON Lines recording.

        Args:
            path: Plain or gzip-compressed recording path.

        Returns:
            The metadata record.

        Raises:
            ValueError: If metadata is not an object or has invalid fields.
        """
        opener = open_gzip if path.suffix == ".gz" else open
        with opener(path, "rt", encoding="utf-8") as stream:
            metadata = loads(stream.readline(), parse_constant=NONFINITE_VALUES.get)
        if not isinstance(metadata, dict) or metadata.get("kind") != "metadata":
            raise ValueError(f"{path.name} does not start with metadata")
        for field in ("experiment", "created_utc", "source"):
            value = metadata.get(field)
            if value is not None and not isinstance(value, str):
                raise ValueError(f"{path.name}: metadata {field} must be a string")
        for field in ("robot_joint_names", "gripper_joint_names"):
            value = metadata.get(field)
            if value is not None and (
                not isinstance(value, list)
                or any(not isinstance(name, str) for name in value)
            ):
                raise ValueError(f"{path.name}: metadata {field} must be a string list")
        # Reject numbers that overflowed to infinity while decoding JSON.
        dumps(metadata, allow_nan=False)
        return metadata

    def read_run(self, path: Path, metadata: dict) -> dict:
        """Calculate run results from every recorded physics-step sample.

        Chart samples are reduced only after connections and phases are found.
        Poses are in meters, joint angles in radians, and forces in newtons.

        Args:
            path: Plain or gzip-compressed recording path.
            metadata: The first record of the same recording.

        Returns:
            Run summary with connection events and reduced chart samples.

        Raises:
            ValueError: If a decoded record has an invalid structure.
        """
        opener = open_gzip if path.suffix == ".gz" else open
        samples = []
        phases = []
        events = []
        previous = []
        last = None
        status = "incomplete"
        incomplete_line = False
        gripper_names = metadata.get("gripper_joint_names") or []
        gripper_index = (
            gripper_names.index("rg2_gripper_joint")
            if "rg2_gripper_joint" in gripper_names
            else 0
        )
        with opener(path, "rt", encoding="utf-8") as stream:
            next(stream)
            for line_number, line in enumerate(stream, start=2):
                try:
                    record = loads(line, parse_constant=NONFINITE_VALUES.get)
                except JSONDecodeError:
                    if not line.endswith("\n"):
                        incomplete_line = True
                        break
                    raise
                if not isinstance(record, dict):
                    raise ValueError(
                        f"{path.name}: line {line_number} must be an object"
                    )
                kind = record.get("kind")
                if not isinstance(kind, str):
                    raise ValueError(
                        f"{path.name}: line {line_number} needs a string kind"
                    )
                if kind == "end":
                    status = record.get("status", "incomplete")
                    if not isinstance(status, str):
                        raise ValueError(f"{path.name}: end status must be a string")
                    continue
                if kind != "sample":
                    continue
                for field in (
                    "robot",
                    "gripper",
                    "tool_pose_world",
                    "assembly_settings",
                    "breakage_settings",
                ):
                    if not isinstance(record.get(field, {}), dict):
                        raise ValueError(f"{path.name}: {field} must be an object")
                for field in ("assembly_settings", "breakage_settings"):
                    enabled = record.get(field, {}).get("enabled")
                    if enabled is not None and not isinstance(enabled, bool):
                        raise ValueError(
                            f"{path.name}: {field}.enabled must be boolean"
                        )
                target = record.get("tool_target_world")
                if target is not None and not isinstance(target, dict):
                    raise ValueError(
                        f"{path.name}: tool_target_world must be an object or null"
                    )
                for field in ("placements", "simulation_contacts"):
                    value = record.get(field, [])
                    if not isinstance(value, list) or any(
                        not isinstance(item, dict) for item in value
                    ):
                        raise ValueError(f"{path.name}: {field} must be an object list")
                robot = record.get("robot", {})
                gripper_data = record.get("gripper", {})
                tool = record.get("tool_pose_world", {})
                target = target or {}
                for name, value in (
                    ("robot.position_rad", robot.get("position_rad")),
                    ("robot.command_position_rad", robot.get("command_position_rad")),
                    ("robot.velocity_rad_s", robot.get("velocity_rad_s")),
                    ("robot.effort_nm", robot.get("effort_nm")),
                    ("gripper.position_rad", gripper_data.get("position_rad")),
                    ("tool_pose_world.position_m", tool.get("position_m")),
                    ("tool_target_world.position_m", target.get("position_m")),
                ):
                    if value is not None and not isinstance(value, list):
                        raise ValueError(f"{path.name}: {name} must be a list or null")
                last = record
                time_s = record.get("simulation_elapsed_s", 0.0)
                if time_s is not None and (
                    isinstance(time_s, bool) or not isinstance(time_s, (int, float))
                ):
                    raise ValueError(
                        f"{path.name}: simulation_elapsed_s must be a number"
                    )
                phase = record.get("phase", "unknown")
                brick = record.get("brick_index", 0)
                if not isinstance(phase, str):
                    raise ValueError(f"{path.name}: phase must be a string")
                if isinstance(brick, bool) or not isinstance(brick, int):
                    raise ValueError(f"{path.name}: brick_index must be an integer")
                if not phases or (phases[-1]["phase"], phases[-1]["brick"]) != (
                    phase,
                    brick,
                ):
                    phases.append({"time_s": time_s, "phase": phase, "brick": brick})
                placements = record.get("placements", [])
                for index, placement in enumerate(placements):
                    before = previous[index] if index < len(previous) else None
                    connected = placement.get("connected", False)
                    if not isinstance(connected, bool):
                        raise ValueError(f"{path.name}: connected must be boolean")
                    if connected and (before is None or not before.get("connected")):
                        error = before.get("position_error_m") if before else None
                        events.append(
                            {
                                "type": "connected",
                                "brick": index + 1,
                                "time_s": time_s,
                                "error_m": error,
                                "offset": placement.get("connected_offset_studs"),
                                "yaw": placement.get("connected_yaw"),
                            }
                        )
                    elif before and before.get("connected") and not connected:
                        events.append(
                            {
                                "type": "disconnected",
                                "brick": index + 1,
                                "time_s": time_s,
                            }
                        )
                previous = placements
                contacts = record.get("simulation_contacts", [])
                forces = [
                    -contact["projected_force_n"]
                    for contact in contacts
                    if isinstance(contact.get("projected_force_n"), (int, float))
                    and isfinite(contact["projected_force_n"])
                ]
                gripper = gripper_data.get("position_rad") or []
                samples.append(
                    {
                        "t": time_s,
                        "joints": robot.get("position_rad") or [],
                        "joint_commands": robot.get("command_position_rad") or [],
                        "joint_velocities": robot.get("velocity_rad_s") or [],
                        "joint_efforts": robot.get("effort_nm") or [],
                        "tool": tool.get("position_m") or [],
                        "tool_target": target.get("position_m") or [],
                        "gripper": (
                            gripper[gripper_index]
                            if gripper and gripper_index < len(gripper)
                            else None
                        ),
                        "gripper_target": gripper_data.get("command_position_rad"),
                        "force": max(forces) if forces else None,
                        "required_force": record.get("assembly_settings", {}).get(
                            "required_force_n"
                        ),
                    }
                )
        if incomplete_line:
            status = "incomplete"
        stride = max(1, ceil(len(samples) / 800))
        chart = samples[::stride]
        if samples and chart[-1] is not samples[-1]:
            chart.append(samples[-1])
        # Keep each signal's local extrema and missing-data boundaries. Uniform
        # sampling alone can omit brief contact forces or joint-effort peaks.
        bucket_size = max(1, ceil(len(samples) / 400))
        chart_series = {}
        vector_fields = (
            "joints",
            "joint_commands",
            "joint_velocities",
            "joint_efforts",
            "tool",
            "tool_target",
        )
        for field in (
            *vector_fields,
            "gripper",
            "gripper_target",
            "force",
            "required_force",
        ):
            count = (
                max((len(sample[field]) for sample in samples), default=0)
                if field in vector_fields
                else 1
            )
            traces = []
            for component in range(count):
                values = []
                for sample in samples:
                    raw = sample[field]
                    if field in vector_fields:
                        raw = raw[component] if component < len(raw) else None
                    values.append(
                        raw if isinstance(raw, (float, int)) and isfinite(raw) else None
                    )
                trace = []
                for start in range(0, len(samples), bucket_size):
                    end = min(start + bucket_size, len(samples))
                    indexes = {start, end - 1}
                    present = [
                        index
                        for index in range(start, end)
                        if values[index] is not None
                    ]
                    if present:
                        indexes.add(min(present, key=lambda index: values[index]))
                        indexes.add(max(present, key=lambda index: values[index]))
                    for index in range(start + 1, end):
                        if (values[index] is None) != (values[index - 1] is None):
                            indexes.update((index - 1, index))
                    for index in sorted(indexes):
                        value = values[index]
                        if value is None and (not trace or trace[-1][1] is None):
                            continue
                        trace.append([samples[index]["t"], value])
                traces.append(trace)
            chart_series[field] = traces
        summary = {
            "metadata": metadata,
            "status": status,
            "samples": len(samples),
            "duration_s": last.get("simulation_elapsed_s") if last else None,
            "phases": phases,
            "events": events,
            "placements": last.get("placements", []) if last else [],
            "assembly_settings": last.get("assembly_settings", {}) if last else {},
            "breakage_settings": last.get("breakage_settings", {}) if last else {},
            "chart": chart,
            "chart_stride": stride,
            "chart_series": chart_series,
            "chart_bucket_size": bucket_size,
        }
        # Validate the final payload before it can affect an API response.
        dumps(summary, allow_nan=False)
        return summary

    def refresh(self) -> list[dict]:
        """Discover new recordings and refresh summaries for changed files.

        Returns:
            Distinct run summaries, most recent first.
        """
        output_directory = self.root / "outputs/ur5e_lego"
        candidates = list(output_directory.glob("*.jsonl"))
        candidates += list(output_directory.glob("*.jsonl.gz"))
        candidates += list(self.evidence.glob("*-run.jsonl.gz"))
        selected = {}
        for path in candidates:
            try:
                resolved = path.resolve()
            except (OSError, RuntimeError):
                continue
            if not resolved.is_relative_to(self.root):
                continue
            try:
                metadata = self.read_metadata(path)
            except (
                EOFError,
                OSError,
                ValueError,
                JSONDecodeError,
                zlib.error,
                RecursionError,
            ):
                continue
            identity = (metadata.get("experiment"), metadata.get("created_utc"))
            if None in identity:
                identity = (str(path), None)
            if identity not in selected or path.suffix == ".jsonl":
                selected[identity] = (path, metadata)
        runs = {}
        paths = {}
        videos = {}
        posters = {}
        case_logs = {}
        suite_path = self.evidence / CASE_SUITE
        try:
            suite = loads(suite_path.read_text(encoding="utf-8"))
            suite_cases = suite["cases"] if isinstance(suite["cases"], list) else []
        except (OSError, ValueError, KeyError, TypeError):
            suite = {}
            suite_cases = []
        for identity, (path, metadata) in selected.items():
            run_id = sha256(fsencode(path)).hexdigest()[:20]
            try:
                stat = path.stat()
            except OSError:
                continue
            version = (stat.st_mtime_ns, stat.st_size)
            cached = self.cache.get(path)
            if cached is None or cached[0] != version:
                try:
                    summary = self.read_run(path, metadata)
                except (
                    EOFError,
                    OSError,
                    ValueError,
                    JSONDecodeError,
                    zlib.error,
                    OverflowError,
                    RecursionError,
                ) as exc:
                    summary = {
                        "metadata": metadata,
                        "status": "invalid",
                        "error": str(exc),
                        "samples": 0,
                        "duration_s": None,
                        "phases": [],
                        "events": [],
                        "placements": [],
                        "assembly_settings": {},
                        "breakage_settings": {},
                        "chart": [],
                        "chart_stride": 1,
                        "chart_series": {},
                        "chart_bucket_size": 1,
                    }
                self.cache[path] = (version, summary)
            else:
                summary = cached[1]
            video = None
            video_label = None
            poster = None
            base_path = path.with_suffix("") if path.suffix == ".gz" else path
            sidecar = base_path.with_suffix(".mp4")
            has_sidecar = sidecar.is_file() and sidecar.resolve().is_relative_to(
                self.root
            )
            if has_sidecar:
                video = sidecar
                video_label = (
                    "Recording with matching filename; playback is not synchronized."
                )
            for (
                experiment,
                evidence_log,
                evidence_video,
                evidence_poster,
                exact,
            ) in VIDEO_EVIDENCE:
                if has_sidecar:
                    break
                if experiment != metadata.get("experiment"):
                    continue
                log_path = self.evidence / evidence_log
                video_path = self.evidence / evidence_video
                if not video_path.is_file() or not video_path.resolve().is_relative_to(
                    self.root
                ):
                    continue
                same_run = False
                if log_path.is_file():
                    try:
                        evidence_meta = self.read_metadata(log_path)
                        same_run = identity == (
                            evidence_meta.get("experiment"),
                            evidence_meta.get("created_utc"),
                        )
                    except (
                        EOFError,
                        OSError,
                        ValueError,
                        JSONDecodeError,
                        zlib.error,
                        RecursionError,
                    ):
                        pass
                if same_run and exact:
                    video = video_path
                    poster = (
                        self.evidence / evidence_poster if evidence_poster else None
                    )
                    video_label = (
                        "Recording from this run; playback is not synchronized."
                    )
                    break
                if video is None and "rejection" not in evidence_video:
                    video = video_path
                    poster = (
                        self.evidence / evidence_poster if evidence_poster else None
                    )
                    video_label = (
                        "Example recording of this experiment; may be a different run."
                    )
            poster_available = bool(
                poster
                and poster.is_file()
                and poster.resolve().is_relative_to(self.root)
            )
            # A case result applies only to the exact recording it was computed from.
            config = metadata.get("config")
            assembly = config.get("assembly") if isinstance(config, dict) else None
            case = assembly.get("case") if isinstance(assembly, dict) else None
            case = case if isinstance(case, dict) else None
            case_id = str(case.get("id", "")) if case else ""
            case_result = next(
                (
                    item
                    for item in suite_cases
                    if isinstance(item, dict)
                    and case_id
                    and item.get("id") == case_id
                    and item.get("created_utc") == metadata.get("created_utc")
                ),
                None,
            )
            if case_result is not None:
                own_video = self.evidence / f"ur5e-case-{case_id}-run.mp4"
                if own_video.is_file():
                    video = own_video
                    video_label = (
                        f"Recording of this {case_id} run; "
                        "playback is not synchronized."
                    )
                log_name = Path(str(case_result.get("console_log", ""))).name
                if log_name and (self.evidence / log_name).is_file():
                    case_logs[run_id] = self.evidence / log_name
            if case and video is None:
                source = {**case, **(case_result or {})}.get(
                    "representative_video_case", ""
                )
                source = Path(str(source)).name
                representative = self.evidence / f"ur5e-case-{source}-run.mp4"
                if source and representative.is_file():
                    video = representative
                    video_label = (
                        f"Representative video from case {source}; "
                        "it does not show this run."
                    )
            run = dict(summary)
            run.update(
                {
                    "id": run_id,
                    "filename": path.name,
                    "video": video is not None,
                    "poster": poster_available,
                    "video_label": video_label,
                    "case": case,
                    "case_result": case_result,
                    "case_suite": (
                        {key: value for key, value in suite.items() if key != "cases"}
                        if case_result is not None
                        else None
                    ),
                    "case_log": run_id in case_logs,
                }
            )
            runs[run_id] = run
            paths[run_id] = path
            if video is not None:
                videos[run_id] = video
            if poster_available:
                posters[run_id] = poster
        self.runs = runs
        self.paths = paths
        self.videos = videos
        self.posters = posters
        self.case_logs = case_logs
        return sorted(
            runs.values(),
            key=lambda run: run["metadata"].get("created_utc") or "",
            reverse=True,
        )


class DashboardServer(ThreadingHTTPServer):
    """HTTP server holding the configured recording collection."""

    def __init__(self, port: int, collection: RunCollection) -> None:
        """Bind the dashboard to the local machine only.

        Args:
            port: TCP port on the loopback interface.
            collection: Recording collection available to requests.
        """
        self.collection = collection
        super().__init__(("127.0.0.1", port), DashboardHandler)


class DashboardHandler(BaseHTTPRequestHandler):
    """Serve only the dashboard assets and discovered read-only recordings."""

    def do_GET(self) -> None:
        """Respond to an asset, run list, run detail, video, or download request."""
        server = self.server
        if not isinstance(server, DashboardServer):
            raise TypeError("DashboardHandler requires DashboardServer")
        route = urlsplit(self.path)
        query = parse_qs(route.query)
        run_id = query.get("id", [""])[0]
        if route.path == "/api/runs":
            runs = server.collection.refresh()
            body = dumps(
                [
                    {
                        "id": run["id"],
                        "filename": run["filename"],
                        "experiment": run["metadata"].get("experiment"),
                        "created_utc": run["metadata"].get("created_utc"),
                        "source": run["metadata"].get("source"),
                        "status": run["status"],
                        "duration_s": run["duration_s"],
                        "samples": run["samples"],
                        "connected": sum(
                            bool(p.get("connected")) for p in run["placements"]
                        ),
                        "placements": len(run["placements"]),
                        "case_id": (run["case"] or {}).get("id"),
                        "case_title": (run["case"] or {}).get("title"),
                        "case_category": (run["case"] or {}).get("category"),
                        "case_expected": (run["case"] or {}).get("expected_outcome"),
                        "case_observed": (run["case_result"] or {}).get(
                            "observed_outcome"
                        ),
                        "case_as_predicted": (run["case_result"] or {}).get(
                            "as_predicted"
                        ),
                    }
                    for run in runs
                ],
                allow_nan=False,
            ).encode()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
            return
        if route.path == "/api/run":
            run = server.collection.runs.get(run_id)
            if run is None:
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            body = dumps(run, allow_nan=False).encode()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
            return
        assets = {
            "/": (ASSETS / "index.html", "text/html; charset=utf-8"),
            "/app.js": (ASSETS / "app.js", "text/javascript; charset=utf-8"),
            "/style.css": (ASSETS / "style.css", "text/css; charset=utf-8"),
            "/icon.svg": (ASSETS / "icon.svg", "image/svg+xml"),
        }
        if route.path in assets:
            path, content_type = assets[route.path]
        elif route.path == "/video" and run_id in server.collection.videos:
            path = server.collection.videos[run_id]
            content_type = "video/mp4"
        elif route.path == "/poster" and run_id in server.collection.posters:
            path = server.collection.posters[run_id]
            content_type = "image/png"
        elif route.path == "/download" and run_id in server.collection.paths:
            path = server.collection.paths[run_id]
            content_type = "application/octet-stream"
        elif route.path == "/case-log" and run_id in server.collection.case_logs:
            path = server.collection.case_logs[run_id]
            content_type = "text/plain; charset=utf-8"
        elif (
            route.path == "/case-suite"
            and (server.collection.evidence / CASE_SUITE).is_file()
        ):
            path = server.collection.evidence / CASE_SUITE
            content_type = "application/json; charset=utf-8"
        else:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        size = path.stat().st_size
        start, end = 0, size - 1
        range_header = self.headers.get("Range")
        if range_header:
            try:
                unit, bounds = range_header.split("=", 1)
                first, last_byte = bounds.split("-", 1)
                if unit != "bytes" or "," in bounds or not (first or last_byte):
                    raise ValueError("Unsupported range")
                if first:
                    start = int(first)
                    end = min(int(last_byte), end) if last_byte else end
                else:
                    start = max(0, size - int(last_byte))
                if start < 0 or start > end or start >= size:
                    raise ValueError("Unsatisfiable range")
            except ValueError:
                self.send_response(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
                self.send_header("Content-Range", f"bytes */{size}")
                self.end_headers()
                return
        self.send_response(
            HTTPStatus.PARTIAL_CONTENT if range_header else HTTPStatus.OK
        )
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(max(0, end - start + 1)))
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Cache-Control", "no-store")
        if range_header:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        if route.path == "/download":
            encoded_filename = quote(path.name, safe="", errors="replace")
            self.send_header(
                "Content-Disposition",
                f"attachment; filename*=UTF-8''{encoded_filename}",
            )
        self.end_headers()
        try:
            with path.open("rb") as stream:
                stream.seek(start)
                remaining = end - start + 1
                while remaining > 0:
                    chunk = stream.read(min(remaining, 1024 * 1024))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    remaining -= len(chunk)
        except (BrokenPipeError, ConnectionResetError):
            return


if __name__ == "__main__":
    parser = ArgumentParser(description=__doc__)
    parser.add_argument(
        "--experiment-root",
        type=Path,
        default=Path.cwd(),
        help="Experiment root (default: current directory)",
    )
    parser.add_argument(
        "--port", type=int, default=8765, help="Local port (default: 8765)"
    )
    args = parser.parse_args()
    server = DashboardServer(args.port, RunCollection(args.experiment_root))
    print(f"Results viewer: http://127.0.0.1:{server.server_port}", flush=True)
    print(f"Experiment root: {args.experiment_root.resolve()}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.server_close()
