"use strict";

const byId = (id) => document.getElementById(id);
let runs = [];
let selectedId = null;
let currentRun = null;
let activeFilter = "all";
let requestVersion = 0;
let structures = [];
let selectedStructure = null;

/** Escape recorded text before inserting it into an HTML fragment. */
function escapeText(value) {
  return String(value ?? "").replace(
    /[&<>"']/g,
    (character) =>
      ({
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        '"': "&quot;",
        "'": "&#39;",
      })[character],
  );
}

/** Identify the documented controlled-rejection trial by its recorded metadata. */
function isControlledRejection(name, createdUtc) {
  return name === "stack" && createdUtc === "2026-10-31T23:28:47.042595+00:00";
}

/** Return a readable experiment name without changing unknown names. */
function experimentName(name, createdUtc) {
  if (isControlledRejection(name, createdUtc))
    return "Controlled rejection test";
  const names = {
    stack_four: "Four-brick stack",
    stack: "Three-brick stack",
    baseplate: "Baseplate assembly",
    transfer: "Brick transfer",
  };
  return Object.hasOwn(names, name)
    ? names[name]
    : String(name || "Unnamed experiment").replaceAll("_", " ");
}

/** Return a readable case outcome without changing unknown outcomes. */
function outcomeName(outcome) {
  const names = {
    connected: "Connected",
    rejected: "Connection rejected",
    wrong_stud: "Connected at the wrong stud (flagged)",
    target_not_reached: "Arm target not reached",
    grasp_off_center: "Grasp off center",
    dropped: "Brick dropped",
    detached: "Brick detached",
    other_failure: "Other failure",
    harness_failure: "Run did not finish",
  };
  return Object.hasOwn(names, outcome)
    ? names[outcome]
    : String(outcome || "Not recorded").replaceAll("_", " ");
}

/** Tell whether a run built a structure that is no longer in the library. */
function isHistorical(run) {
  return Boolean(run.structure) && !run.in_library;
}

/** Describe joint breaks as lasting / transient, flagging an incomplete log. */
function breaksText(run) {
  const text = `${run.lasting_breaks} lasting / ${run.transient_breaks} transient`;
  return run.event_log_complete ? text : `${text} (log incomplete)`;
}

/** Describe breakage-solver warnings as non-convergence / high-slack counts. */
function solverText(warnings) {
  return `${warnings.not_converged} not converged / ${warnings.high_slack} high slack`;
}

/** Return the title shown for a run, preferring its test case. */
function runTitle(run) {
  return run.case_id
    ? `${run.case_id} · ${run.case_title}`
    : experimentName(run.experiment, run.created_utc);
}

/** Describe a case result: unpublished, as predicted, or differing. */
function predictionLabel(asPredicted) {
  if (asPredicted === true) return "As predicted";
  if (asPredicted === false) return "Differs from prediction";
  return "Not in the published suite";
}

/** Fill a definition list using the existing settings row style. */
function fillRows(id, rows) {
  byId(id).innerHTML = rows
    .map(
      ([key, value]) =>
        `<div class="settings-row"><dt>${escapeText(key)}</dt><dd>${escapeText(value)}</dd></div>`,
    )
    .join("");
}

/** Format recorded simulation seconds as minutes and seconds. */
function formatTime(seconds) {
  if (!Number.isFinite(seconds)) return "—";
  const minutes = Math.floor(seconds / 60);
  return `${minutes}:${String(Math.floor(seconds % 60)).padStart(2, "0")}`;
}

/** Format a finite measurement, preserving missing values as unavailable. */
function formatNumber(value, digits = 2) {
  return Number.isFinite(value) ? value.toFixed(digits) : "—";
}

/** Describe a recording's actual end record, including unfinished runs. */
function describeStatus(status) {
  const statuses = {
    completed: ["Completed", "completed"],
    stopped: ["Stopped", "other"],
    interrupted_or_failed: ["Interrupted / failed", "other"],
    incomplete: ["Incomplete", "other"],
    invalid: ["Invalid log", "invalid"],
  };
  return Object.hasOwn(statuses, status)
    ? statuses[status]
    : [String(status || "Unknown"), "other"];
}

/** Display a timestamp in the viewer's local time zone. */
function formatDate(timestamp) {
  if (!timestamp) return "Date unavailable";
  const date = new Date(timestamp);
  if (Number.isNaN(date.getTime())) return String(timestamp);
  return new Intl.DateTimeFormat(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
    second: "2-digit",
  }).format(date);
}

/** Filter and render the list of discovered recordings. */
function renderRuns() {
  const term = byId("search").value.trim().toLowerCase();
  const filtered = runs.filter((run) => {
    const category = run.status === "completed" ? "completed" : "other";
    const matchesFilter =
      activeFilter === "all" ||
      activeFilter === category ||
      (activeFilter === "cases" && Boolean(run.case_id));
    const text =
      `${runTitle(run)} ${run.case_category || ""} ${run.filename} ${run.status} ${run.sweep || ""} ${isHistorical(run) ? "historical" : ""} ${isControlledRejection(run.experiment, run.created_utc) ? "intentional test" : ""}`.toLowerCase();
    return matchesFilter && text.includes(term);
  });
  byId("run-count").textContent = String(runs.length);
  const list = byId("run-list");
  list.replaceChildren();
  if (!filtered.length) {
    const message = document.createElement("p");
    message.className = "side-message";
    message.textContent = runs.length
      ? "No runs match this filter."
      : "No runs found.";
    list.append(message);
    return;
  }
  for (const run of filtered) {
    const [label, category] = describeStatus(run.status);
    const intentional = isControlledRejection(run.experiment, run.created_utc);
    const button = document.createElement("button");
    button.type = "button";
    button.className = `run${run.id === selectedId ? " active" : ""}`;
    button.setAttribute(
      "aria-current",
      run.id === selectedId ? "true" : "false",
    );
    button.setAttribute(
      "aria-label",
      `${runTitle(run)}, ${intentional ? "intentional test, " : ""}${describeStatus(run.status)[0]}, ${formatDate(run.created_utc)}`,
    );
    button.innerHTML = `<span class="run-top"><span class="run-title">${escapeText(runTitle(run))}</span></span>
      <span class="run-date">${escapeText(formatDate(run.created_utc))}</span>
      <span class="run-status"><i class="run-dot ${escapeText(category)}"></i>${escapeText(label)} <span>·</span> ${escapeText(formatTime(run.duration_s))}</span>
      ${intentional ? '<span class="run-purpose">Intentional test</span>' : ""}
      ${run.case_id ? `<span class="run-purpose">${escapeText(predictionLabel(run.case_as_predicted))}</span>` : ""}
      ${isHistorical(run) ? '<span class="run-purpose">Historical · not in the current library</span>' : ""}
      ${run.sweep ? `<span class="run-purpose">Sweep ${escapeText(run.sweep)}</span>` : ""}`;
    button.addEventListener("click", () => selectRun(run.id));
    list.append(button);
  }
}

/** Draw the selected signal against recorded simulation time. */
function drawChart() {
  if (!currentRun) return;
  const data = currentRun.chart || [];
  const signal = byId("signal").value;
  const colors = [
    "#111111",
    "#333333",
    "#555555",
    "#222222",
    "#444444",
    "#555555",
  ];
  const patterns = [[], [9, 4], [2, 3], [10, 3, 2, 3], [5, 3, 1, 3], [1, 3]];
  let names;
  let values;
  let unit;
  if (
    ["joints", "joint_commands", "joint_velocities", "joint_efforts"].includes(
      signal,
    )
  ) {
    names = currentRun.metadata?.robot_joint_names || [];
    if (!names.length)
      names = [
        "Joint 1",
        "Joint 2",
        "Joint 3",
        "Joint 4",
        "Joint 5",
        "Joint 6",
      ];
    values = (sample) => sample[signal] || [];
    unit =
      signal === "joint_velocities"
        ? "rad/s"
        : signal === "joint_efforts"
          ? "N·m"
          : "rad";
  } else if (signal === "tool" || signal === "tool_target") {
    names = ["World X", "World Y", "World Z"];
    values = (sample) => sample[signal] || [];
    unit = "m";
  } else if (signal === "gripper" || signal === "gripper_target") {
    names = ["Gripper joint"];
    values = (sample) => [sample[signal]];
    unit = "rad";
  } else if (signal === "force") {
    names = ["Peak compression"];
    values = (sample) => [sample.force];
    unit = "N";
  } else {
    names = ["Required force"];
    values = (sample) => [sample.required_force];
    unit = "N";
  }
  byId("chart-legend").innerHTML = names
    .map(
      (name, index) =>
        `<span class="legend-item"><svg class="legend-swatch" viewBox="0 0 28 10" aria-hidden="true"><line x1="1" y1="5" x2="27" y2="5" stroke="${colors[index % colors.length]}" stroke-width="2" stroke-dasharray="${patterns[index % patterns.length].join(" ")}"/></svg>${escapeText(name.replaceAll("_joint", "").replaceAll("_", " "))}</span>`,
    )
    .join("");
  byId("chart-unit").textContent = `Value (${unit})`;
  const peakData = currentRun.chart_series?.[signal];
  const traces = Array.isArray(peakData)
    ? names.map((_, index) => peakData[index] || [])
    : names.map((_, index) =>
        data.map((sample) => [sample.t, values(sample)[index]]),
      );
  const forceNote =
    signal === "force"
      ? "Contact debug readings are simulated; gaps mean no reading. "
      : "";
  const samplingNote = currentRun.chart_series
    ? `Min and max preserved in windows of up to ${currentRun.chart_bucket_size || 1} samples.`
    : "Restart the results viewer to show short peaks in the graphs.";
  byId("chart-note").textContent = forceNote + samplingNote;

  let minTime = 0;
  let maxTime = Number.isFinite(currentRun.duration_s)
    ? currentRun.duration_s
    : 0;
  let minValue = Infinity;
  let maxValue = -Infinity;
  for (const trace of traces) {
    for (const [time, value] of trace) {
      if (!Number.isFinite(time) || !Number.isFinite(value)) continue;
      minTime = Math.min(minTime, time);
      maxTime = Math.max(maxTime, time);
      minValue = Math.min(minValue, value);
      maxValue = Math.max(maxValue, value);
    }
  }
  const empty = !Number.isFinite(minValue) || !Number.isFinite(maxValue);
  byId("chart-empty").hidden = !empty;
  const rangeFormatter = new Intl.NumberFormat(undefined, {
    maximumSignificantDigits: 5,
  });
  byId("chart-range").textContent = empty
    ? "No recorded values"
    : `${currentRun.chart_series ? "Recorded" : "Displayed"} range: ${rangeFormatter.format(minValue === 0 ? 0 : minValue)} – ${rangeFormatter.format(maxValue === 0 ? 0 : maxValue)} ${unit}`;
  const canvas = byId("chart");
  canvas.setAttribute(
    "aria-label",
    `${byId("signal").selectedOptions[0].textContent.trim()} in ${unit}, over simulation time`,
  );
  const bounds = canvas.getBoundingClientRect();
  const width = Math.max(bounds.width, 100);
  const height = Math.max(bounds.height, 100);
  const scale = window.devicePixelRatio || 1;
  canvas.width = Math.round(width * scale);
  canvas.height = Math.round(height * scale);
  const context = canvas.getContext("2d");
  context.setTransform(scale, 0, 0, scale, 0, 0);
  context.clearRect(0, 0, width, height);
  if (empty) return;

  const nonnegativeForce =
    ["force", "required_force"].includes(signal) && minValue >= 0;
  if (minValue === maxValue) {
    const padding = Math.max(Math.abs(minValue) * 0.1, 0.1);
    minValue -= padding;
    maxValue += padding;
  }
  if (nonnegativeForce) {
    minValue = Math.max(0, minValue);
  }
  const roughStep = (maxValue - minValue) / 4;
  const magnitude = 10 ** Math.floor(Math.log10(roughStep));
  const fraction = roughStep / magnitude;
  const step =
    [1, 2, 2.5, 5, 10].find((candidate) => candidate >= fraction) * magnitude;
  const lower = Math.floor(minValue / step) * step;
  const upper = Math.ceil(maxValue / step) * step;
  const tickCount = Math.max(1, Math.round((upper - lower) / step));
  let digits = Math.max(0, -Math.floor(Math.log10(step)));
  if (Math.abs(step * 10 ** digits - Math.round(step * 10 ** digits)) > 1e-7)
    digits += 1;
  const tickLabels = Array.from({ length: tickCount + 1 }, (_, index) => {
    const value = upper - index * step;
    const normalized = Math.abs(value) < step * 1e-8 ? 0 : value;
    return Math.abs(normalized) >= 1e8 || step < 1e-6
      ? normalized.toExponential(2)
      : normalized.toFixed(Math.min(digits, 6));
  });
  context.font = "12px system-ui, sans-serif";
  const left =
    Math.ceil(
      Math.max(...tickLabels.map((label) => context.measureText(label).width)),
    ) + 14;
  const right = 24,
    top = 10,
    bottom = 26;
  const plotWidth = Math.max(1, width - left - right);
  const plotHeight = Math.max(1, height - top - bottom);
  const span = Math.max(maxTime - minTime, 1e-9);
  context.textAlign = "right";
  context.textBaseline = "middle";
  tickLabels.forEach((label, index) => {
    const y = top + (plotHeight * index) / tickCount;
    context.beginPath();
    context.strokeStyle = "#e3e3e3";
    context.lineWidth = 1;
    context.moveTo(left, y);
    context.lineTo(left + plotWidth, y);
    context.stroke();
    context.fillStyle = "#555555";
    context.fillText(label, left - 8, y);
  });
  context.textAlign = "center";
  context.textBaseline = "top";
  const timeDigits = span < 4 ? 2 : span < 40 ? 1 : 0;
  for (let index = 0; index <= 4; index += 1) {
    const x = left + (plotWidth * index) / 4;
    context.fillStyle = "#555555";
    context.fillText(
      (minTime + (span * index) / 4).toFixed(timeDigits),
      x,
      height - 17,
    );
  }
  traces.forEach((trace, index) => {
    context.beginPath();
    context.strokeStyle = colors[index % colors.length];
    context.lineWidth = 1.8;
    context.setLineDash(patterns[index % patterns.length]);
    let drawing = false;
    let previousY = 0;
    for (const [time, value] of trace) {
      if (!Number.isFinite(time) || !Number.isFinite(value)) {
        drawing = false;
        continue;
      }
      const x = left + ((time - minTime) / span) * plotWidth;
      const y = top + ((upper - value) / (upper - lower)) * plotHeight;
      if (drawing) {
        if (signal === "required_force") context.lineTo(x, previousY);
        context.lineTo(x, y);
      } else context.moveTo(x, y);
      drawing = true;
      previousY = y;
    }
    context.stroke();
    if (signal === "force") {
      context.setLineDash([]);
      context.fillStyle = colors[index % colors.length];
      trace.forEach(([time, value], pointIndex) => {
        if (!Number.isFinite(time) || !Number.isFinite(value)) return;
        const previous = trace[pointIndex - 1]?.[1];
        const next = trace[pointIndex + 1]?.[1];
        if (Number.isFinite(previous) || Number.isFinite(next)) return;
        const x = left + ((time - minTime) / span) * plotWidth;
        const y = top + ((upper - value) / (upper - lower)) * plotHeight;
        context.beginPath();
        context.arc(x, y, 2, 0, Math.PI * 2);
        context.fill();
      });
    }
  });
  context.setLineDash([]);
}

/** Load the selected recording, ignoring responses superseded by another selection. */
async function selectRun(id) {
  selectedId = id;
  renderRuns();
  const version = ++requestVersion;
  try {
    const response = await fetch(`/api/run?id=${encodeURIComponent(id)}`);
    if (!response.ok)
      throw new Error(`Unable to load the run (${response.status}).`);
    const run = await response.json();
    if (version === requestVersion) {
      currentRun = run;
      byId("loading").hidden = true;
      byId("empty").hidden = true;
      byId("error").hidden = true;
      byId("structure-view").hidden = true;
      byId("content").hidden = false;
      const metadata = run.metadata || {};
      const [status, category] = describeStatus(run.status);
      const name = run.case
        ? `${run.case.id} · ${run.case.title}`
        : experimentName(metadata.experiment, metadata.created_utc);
      const result = run.case_result;
      const intentional = isControlledRejection(
        metadata.experiment,
        metadata.created_utc,
      );
      byId("experiment-name").textContent = name;
      byId("breadcrumb-name").textContent = name.toUpperCase();
      byId("run-date").textContent = formatDate(metadata.created_utc);
      byId("run-date").title = metadata.created_utc || "";
      byId("run-file").textContent = run.filename;
      byId("status").textContent = status;
      byId("status").className = `status ${category}`;
      byId("scenario-badge").hidden = !intentional;
      byId("scenario-notice").hidden = !intentional;
      byId("run-historical").hidden = !isHistorical(run);
      byId("run-historical").textContent = isHistorical(run)
        ? `Historical run: "${run.structure}" is not in the current structure library. This is not a current result.`
        : "";
      const sweep = run.sweep;
      byId("sweep-panel").hidden = !sweep;
      if (sweep) {
        byId("sweep-title").textContent = `${sweep.sweep} · ${sweep.label}`;
        byId("sweep-badge").textContent = String(sweep.outcome).toUpperCase();
        byId("sweep-note").textContent =
          "From the committed sweep summary. One simulation run; a completion is not evidence of robustness." +
          (sweep.event_log_complete
            ? ""
            : " The console event log is incomplete, so breaks and solver warnings are lower bounds.");
        fillRows("sweep-rows", [
          ["Run", sweep.run],
          ["Breakage model", sweep.breakage_enabled ? "on" : "off"],
          [
            "Connected at end",
            `${sweep.bricks_connected_end} / ${sweep.bricks_total}`,
          ],
          ["Stopped by", sweep.failure || "nothing (no controller failure)"],
          ["Joint breaks", breaksText(sweep)],
          ["Solver warnings", solverText(sweep.solver_warnings)],
          ["Gripper contacts", `${sweep.contact_mode} mode`],
        ]);
        byId("sweep-breaks").innerHTML = sweep.breaks.length
          ? "<thead><tr><th>Joint (support → brick)</th><th>Phase</th><th>Break</th><th>Before the break</th><th>Peak utilization</th></tr></thead><tbody>" +
            sweep.breaks
              .map(
                (item) =>
                  `<tr><td>${escapeText(`${item.parent} → ${item.child}`)}</td><td>${escapeText(item.phase || "—")}</td><td>${item.rejoined ? "transient (re-formed)" : "lasting"}</td><td>${escapeText(item.cause)}</td><td>${escapeText(formatNumber(item.peak_utilization_before_break))}</td></tr>`,
              )
              .join("") +
            "</tbody>"
          : "";
      }
      byId("metric-outcome").textContent = result
        ? outcomeName(result.observed_outcome)
        : status;
      byId("case-panel").hidden = !run.case;
      if (run.case) {
        const suite = run.case_suite || {};
        byId("case-title").textContent = runTitle({
          case_id: run.case.id,
          case_title: run.case.title,
        });
        byId("case-badge").textContent = predictionLabel(
          result ? result.as_predicted : undefined,
        ).toUpperCase();
        byId("case-basis").textContent =
          `Written prediction: ${run.case.prediction_basis || "not recorded"}`;
        const failure = byId("case-failure");
        failure.hidden = !result?.failure;
        failure.textContent = result?.failure
          ? `Recorded failure: ${result.failure}`
          : "";
        const assembly = run.metadata?.config?.assembly || {};
        fillRows(
          "case-inputs",
          Object.entries(assembly)
            .filter(([key]) => !["case", "experiment_name"].includes(key))
            .map(([key, value]) => {
              if (key.endsWith("_rad"))
                return [
                  key.replace("_rad", ""),
                  `${formatNumber((value * 180) / Math.PI, 2)} deg`,
                ];
              if (key === "ground_truth_xy_correction")
                return [key, value ? "on" : "off"];
              return [key, JSON.stringify(value)];
            }),
        );
        fillRows("case-outcome", [
          ["Expected", outcomeName(run.case.expected_outcome)],
          ["Observed", result ? outcomeName(result.observed_outcome) : "Not published"],
          ["Recorded status", describeStatus(run.status)[0]],
          ["Last phase", result?.last_phase || "—"],
          ["Simulated duration", `${formatNumber(run.duration_s, 1)} s`],
          ["Config file", result?.config_file || "—"],
        ]);
        const number = (value, digits = 2) => formatNumber(value, digits);
        byId("case-measurements").innerHTML =
          "<thead><tr><th>Brick</th><th>Target studs</th><th>Connected studs</th><th>Pre-connection lateral (mm)</th><th>Pre-connection gap (mm)</th><th>Pre-connection yaw (deg)</th><th>Final lateral (mm)</th><th>Final yaw (deg)</th><th>Peak simulated force (N)</th></tr></thead><tbody>" +
          (result?.placements || [])
            .map(
              (item) =>
                `<tr><td>${escapeText(item.brick)}</td><td>${escapeText(JSON.stringify(item.target_offset_studs))}</td><td>${escapeText(item.connected ? JSON.stringify(item.connected_offset_studs) : "none")}</td><td>${number(item.pre_connection_lateral_mm)}</td><td>${number(item.pre_connection_gap_mm)}</td><td>${number(item.pre_connection_yaw_deg)}</td><td>${number(item.final_lateral_error_mm)}</td><td>${number(item.final_yaw_deg)}</td><td>${number(item.peak_simulated_contact_force_n)}</td></tr>`,
            )
            .join("") +
          "</tbody>";
        const evidence = suite.evidence_classes || {};
        const evidenceNames = {
          contact_physics: "Contact physics",
          simulated_connection: "Simulated connection",
          ground_truth_corrections: "Ground-truth corrections",
          other_assumptions: "Other assumptions",
        };
        fillRows(
          "case-evidence",
          Object.entries(evidence).map(([key, value]) => [
            evidenceNames[key] || key,
            value,
          ]),
        );
        byId("case-limitations").innerHTML = (suite.limitations || [])
          .map((item) => `<li>${escapeText(item)}</li>`)
          .join("");
        const environment = suite.environment || {};
        fillRows("case-provenance", [
          ["Commit", result?.commit || suite.commit || "—"],
          ["Suite", result?.suite_id || suite.suite_id || "—"],
          ["Isaac Sim", environment.isaacsim || "—"],
          ["isaac-mcp resolver", environment.isaac_mcp_commit || "—"],
          [
            "Lab assets match reference",
            Object.values(environment.lab_assets || {}).every(
              (item) => item.matches_reference,
            )
              ? "yes"
              : "no",
          ],
        ]);
        const id = encodeURIComponent(run.id);
        byId("case-files").innerHTML = [
          `<a href="/download?id=${id}">Full run log</a>`,
          run.case_log ? `<a href="/case-log?id=${id}">Console log</a>` : "",
          `<a href="/case-suite">Suite manifest</a>`,
        ]
          .filter(Boolean)
          .join(" · ");
        const cases = runs
          .filter((item) => item.case_id && item.case_observed)
          .sort((left, right) => left.case_id.localeCompare(right.case_id));
        const overview = byId("case-overview");
        overview.innerHTML =
          "<thead><tr><th>Case</th><th>Test</th><th>Expected</th><th>Observed</th><th>Prediction</th></tr></thead>";
        const body = document.createElement("tbody");
        for (const item of cases) {
          const row = document.createElement("tr");
          row.className = item.id === run.id ? "active" : "";
          row.innerHTML = `<td><button type="button" class="case-link">${escapeText(item.case_id)}</button></td><td>${escapeText(item.case_title)}</td><td>${escapeText(outcomeName(item.case_expected))}</td><td>${escapeText(outcomeName(item.case_observed))}</td><td>${escapeText(predictionLabel(item.case_as_predicted))}</td>`;
          row
            .querySelector("button")
            .addEventListener("click", () => selectRun(item.id));
          body.append(row);
        }
        overview.append(body);
      }
      byId("metric-outcome-note").textContent =
        run.error ||
        (result
          ? `${predictionLabel(result.as_predicted)}; expected ${outcomeName(result.expected_outcome)}`
          : null) ||
        (intentional
          ? "Expected: brick 2 is rejected"
          : run.status === "completed"
            ? "Script reported completion"
            : "See run details");
      const placements = run.placements || [];
      const connected = placements.filter((item) => item.connected).length;
      byId("metric-connections").textContent = placements.length
        ? `${connected} / ${placements.length}`
        : "—";
      byId("metric-duration").textContent = formatTime(run.duration_s);
      byId("metric-samples").textContent = Number(
        run.samples || 0,
      ).toLocaleString();
      byId("download").href = `/download?id=${encodeURIComponent(run.id)}`;
      const video = byId("video");
      video.pause();
      if (run.video) {
        if (run.poster)
          video.poster = `/poster?id=${encodeURIComponent(run.id)}`;
        else video.removeAttribute("poster");
        video.src = `/video?id=${encodeURIComponent(run.id)}`;
        video.hidden = false;
        byId("video-empty").hidden = true;
        byId("video-note").textContent = run.video_label;
      } else {
        video.removeAttribute("src");
        video.removeAttribute("poster");
        video.load();
        video.hidden = true;
        byId("video-empty").hidden = false;
        byId("video-note").textContent = "";
      }
      const container = byId("connections");
      container.replaceChildren();
      byId("connections-badge").textContent = placements.length
        ? `${connected} / ${placements.length} CONNECTED`
        : "NOT TRACKED";
      if (!placements.length) {
        container.innerHTML =
          '<p class="no-data">No assembly connections were recorded for this experiment.</p>';
      } else
        placements.forEach((placement, index) => {
          const event = (run.events || [])
            .filter(
              (item) => item.type === "connected" && item.brick === index + 1,
            )
            .at(-1);
          const error = event?.error_m;
          const xy =
            Array.isArray(error) &&
            Number.isFinite(error[0]) &&
            Number.isFinite(error[1])
              ? `${formatNumber(Math.hypot(error[0], error[1]) * 1000, 3)} mm`
              : "—";
          const z =
            Array.isArray(error) && Number.isFinite(error[2])
              ? `${formatNumber(error[2] * 1000, 3)} mm`
              : "—";
          const offset = Array.isArray(placement.connected_offset_studs)
            ? `(${placement.connected_offset_studs.join(", ")})`
            : "—";
          const state = placement.connected
            ? `Connected${event && Number.isFinite(event.time_s) ? ` · ${formatTime(event.time_s)}` : ""}`
            : "Not connected";
          const card = document.createElement("div");
          card.className = "connection";
          card.innerHTML = `<div class="connection-header"><span class="connection-name">Brick ${index + 1}</span><span class="connection-state${placement.connected ? "" : " no"}">${state}</span></div>
          <div class="connection-detail"><div><span>XY before</span><strong>${escapeText(xy)}</strong></div><div><span>Z before</span><strong>${escapeText(z)}</strong></div><div><span>Offset · studs</span><strong>${escapeText(offset)}</strong></div></div>`;
          container.append(card);
        });
      const timeline = byId("timeline");
      timeline.replaceChildren();
      byId("phase-count").textContent = `${(run.phases || []).length} PHASES`;
      for (const phase of run.phases || []) {
        const item = document.createElement("div");
        item.className = "timeline-item";
        item.innerHTML = `<span class="timeline-time">${escapeText(formatTime(phase.time_s))}</span><span class="timeline-marker"><i></i></span><span class="timeline-name">${escapeText(String(phase.phase).replaceAll("_", " "))}${phase.brick ? `<small>· Brick ${escapeText(phase.brick)}</small>` : ""}</span>`;
        timeline.append(item);
      }
      if (!timeline.childElementCount)
        timeline.innerHTML =
          '<p class="no-data">No phase changes were recorded.</p>';
      const assembly = run.assembly_settings || {};
      const breaks = run.breakage_settings || {};
      const settings = [
        [
          "Assembly checking",
          assembly.enabled == null
            ? "—"
            : assembly.enabled
              ? "Enabled"
              : "Disabled",
        ],
        [
          "Required force",
          Number.isFinite(assembly.required_force_n)
            ? `${formatNumber(assembly.required_force_n, 2)} N`
            : "—",
        ],
        [
          "Distance tolerance",
          Number.isFinite(assembly.distance_tolerance_m)
            ? `${formatNumber(assembly.distance_tolerance_m * 1000, 2)} mm`
            : "—",
        ],
        [
          "Position tolerance",
          Number.isFinite(assembly.position_tolerance_m)
            ? `${formatNumber(assembly.position_tolerance_m * 1000, 2)} mm`
            : "—",
        ],
        [
          "Yaw tolerance",
          Number.isFinite(assembly.yaw_tolerance_rad)
            ? `${formatNumber((assembly.yaw_tolerance_rad * 180) / Math.PI, 1)}°`
            : "—",
        ],
        [
          "Breakage checking",
          breaks.enabled == null
            ? "—"
            : breaks.enabled
              ? "Enabled"
              : "Disabled",
        ],
      ];
      byId("settings").innerHTML = settings
        .map(
          ([label, value]) =>
            `<div class="settings-row"><dt>${escapeText(label)}</dt><dd>${escapeText(value)}</dd></div>`,
        )
        .join("");
      byId("metadata").textContent = JSON.stringify(
        {
          metadata: run.metadata,
          assembly_settings_at_last_sample: assembly,
          breakage_settings_at_last_sample: breaks,
          connection_events: run.events,
        },
        null,
        2,
      );
      drawChart();
    }
  } catch (error) {
    if (version !== requestVersion) return;
    byId("content").hidden = true;
    byId("loading").hidden = true;
    byId("error").hidden = false;
    byId("error-message").textContent = error.message;
  }
}

/** Return the latest trial of one kind, optionally with one breakage setting. */
function latestTrial(structure, kind, breakage) {
  const matching = structure.trials.filter(
    (trial) =>
      trial.kind === kind && (breakage === null || trial.breakage === breakage),
  );
  return matching.length ? matching[matching.length - 1] : null;
}

/** Summarize a trial as connected bricks and a completed or failed mark. */
function trialLabel(trial) {
  if (!trial) return "not run";
  const mark = trial.outcome === "completed" ? "✓" : "✗";
  return `${trial.bricks_connected}/${trial.bricks_total} ${mark}`;
}

/** Short label of a structure's results at its standard settings. */
function defaultLabel(structure) {
  const entry = structure.catalog;
  if (!entry) return trialLabel(latestTrial(structure, "simulation", null));
  if (!entry.default_runs) return "sim not run";
  const mark =
    entry.default_completed === entry.default_runs
      ? "✓"
      : entry.default_completed
        ? "partly"
        : "✗";
  return `sim ${entry.default_completed}/${entry.default_runs} runs completed ${mark}`;
}

/** Title of a structure: the catalog title, else its file name. */
function structureTitle(structure) {
  return structure.catalog ? structure.catalog.title : structure.name;
}

/** Title of the catalog section a structure belongs to. */
function sectionTitle(structure) {
  return structure.catalog ? structure.catalog.section_title : "Other";
}

/** Render the sidebar list of structures matching the search term. */
function renderStructureList() {
  const term = byId("search").value.trim().toLowerCase();
  const list = byId("run-list");
  list.replaceChildren();
  byId("run-count").textContent = String(structures.length);
  const filtered = structures.filter((structure) =>
    `${structure.name} ${structureTitle(structure)}`.toLowerCase().includes(term),
  );
  if (!filtered.length) {
    const message = document.createElement("p");
    message.className = "side-message";
    message.textContent = "No structures match this search.";
    list.append(message);
    return;
  }
  let heading = null;
  for (const structure of filtered) {
    const section = sectionTitle(structure);
    if (section !== heading) {
      heading = section;
      const label = document.createElement("p");
      label.className = "side-section";
      label.textContent = section;
      list.append(label);
    }
    const button = document.createElement("button");
    button.type = "button";
    const active = structure.name === selectedStructure;
    button.className = `run${active ? " active" : ""}`;
    button.setAttribute("aria-current", active ? "true" : "false");
    button.className += " structure-item";
    button.innerHTML = `<span class="run-top"><span class="run-title">${escapeText(structureTitle(structure))}</span></span>
      <span class="run-status">${structure.brick_count} bricks <span>·</span> ${escapeText(defaultLabel(structure))}</span>`;
    button.addEventListener("click", () => showStructure(structure.name));
    list.append(button);
  }
}

/** One run's outcome in words, e.g. "completed, 7/7 connected". */
function runText(run) {
  if (!run) return "not run";
  if (run.outcome === "completed")
    return `completed, ${run.connected}/${run.total} connected`;
  return `failed (${run.stop}), ${run.connected}/${run.total} connected at the end`;
}

/** Fill the simulation, results and attempts panels from the catalog. */
function showCatalog(structure) {
  const entry = structure.catalog;
  const media = byId("structure-media");
  media.replaceChildren();
  byId("structure-media-panel").hidden = !(entry && (entry.still || entry.video));
  if (entry && entry.video) {
    const video = document.createElement("video");
    video.controls = true;
    video.preload = "none";
    video.src = `/docs/${entry.video}`;
    if (entry.still) video.poster = `/docs/${entry.still}`;
    media.append(video);
  } else if (entry && entry.still) {
    const image = document.createElement("img");
    image.src = `/docs/${entry.still}`;
    image.alt = `${entry.title} in simulation`;
    media.append(image);
  }
  const result = byId("structure-result");
  const paragraphs = [];
  if (!entry) {
    paragraphs.push("No catalog entry for this structure.");
  } else {
    paragraphs.push(
      `Standard settings: ${entry.needs || "the controller defaults"}.`,
    );
    if (entry.blocked) paragraphs.push(`Not buildable yet: ${entry.blocked}.`);
    if (!entry.default_runs) {
      paragraphs.push("Not run at its standard settings yet.");
    } else {
      const latest = entry.latest;
      paragraphs.push(
        `${entry.default_completed} of ${entry.default_runs} simulation runs at these settings completed. ` +
          `Latest: ${runText(latest)}.`,
        `Latest run ${latest.run} (sweep ${latest.sweep}): breakage ${latest.breakage ? "on" : "off"}; ` +
          `joint breaks ${breaksText(latest)}; solver warnings ${solverText(latest.solver_warnings)}.`,
      );
    }
  }
  result.innerHTML = paragraphs
    .map((text) => `<p>${escapeText(text)}</p>`)
    .join("");
  const explanation = byId("structure-explanation");
  const lines = [];
  if (entry && entry.mechanism) lines.push(`Failure mechanism ${entry.mechanism}.`);
  if (entry && entry.note) lines.push(entry.note);
  explanation.textContent = lines.join(" ");
  explanation.hidden = !lines.length;
  const attempts = entry ? entry.attempts : [];
  byId("structure-attempts-wrap").hidden = !attempts.length;
  byId("structure-attempts").innerHTML =
    "<thead><tr><th>Changed setting</th><th>Result</th><th>Breakage</th><th>Joint breaks</th><th>Solver warnings</th></tr></thead><tbody>" +
    attempts
      .map(
        (attempt) =>
          `<tr><td>${escapeText(attempt.settings)}</td><td>${escapeText(runText(attempt))}</td><td>${attempt.breakage ? "on" : "off"}</td><td>${escapeText(breaksText(attempt))}</td><td>${escapeText(solverText(attempt.solver_warnings))}</td></tr>`,
      )
      .join("") +
    "</tbody>";
}

/** Draw one top-view square per layer: this layer filled, lower layers outlined. */
function drawLayers(structure) {
  const container = byId("structure-layers");
  container.replaceChildren();
  for (let layer = 0; layer < structure.layers; layer += 1) {
    // Stud grid: x right, y up; SVG y grows downward, so flip y.
    const rect = (brick, attributes) =>
      `<rect x="${brick.x}" y="${20 - brick.y - brick.depth}" width="${brick.width}" height="${brick.depth}" ${attributes}/>`;
    const below = structure.bricks
      .filter((brick) => brick.layer < layer)
      .map((brick) =>
        rect(brick, 'fill="none" stroke="#c4c4c4" stroke-width="0.12"'),
      );
    const current = structure.bricks
      .filter((brick) => brick.layer === layer)
      .map((brick) => {
        const [r, g, b] = brick.color;
        const label = `<text x="${brick.x + brick.width / 2}" y="${20 - brick.y - brick.depth / 2 + 0.55}" font-size="1.5" text-anchor="middle" fill="#fff">${brick.index + 1}</text>`;
        return (
          rect(brick, `fill="rgb(${r},${g},${b})" stroke="#111" stroke-width="0.12"`) +
          label
        );
      });
    const figure = document.createElement("figure");
    figure.className = "structure-layer";
    figure.innerHTML = `<svg viewBox="0 0 20 20" role="img" aria-label="Layer ${layer + 1}">
      <rect x="0" y="0" width="20" height="20" fill="#f0f0f0"/>
      ${below.join("")}${current.join("")}</svg>
      <figcaption>Layer ${layer + 1}</figcaption>`;
    container.append(figure);
  }
}

/** Show one structure's layout, trials and the overview of all structures. */
function showStructure(name) {
  const structure = structures.find((item) => item.name === name);
  if (!structure) return;
  selectedStructure = name;
  renderStructureList();
  for (const id of ["content", "loading", "empty", "error"])
    byId(id).hidden = true;
  byId("structure-view").hidden = false;
  byId("structure-breadcrumb").textContent = sectionTitle(structure).toUpperCase();
  byId("structure-name").textContent = structureTitle(structure);
  byId("structure-status").textContent = defaultLabel(structure).toUpperCase();
  byId("structure-subheading").textContent =
    `${structure.catalog ? `${structure.catalog.description} ` : ""}` +
    `${structure.brick_count} bricks · ${structure.layers} layers · ${structure.recipe}`;
  showCatalog(structure);
  byId("structure-error").hidden = !structure.error;
  byId("structure-error").textContent = structure.error
    ? `Recipe does not validate: ${structure.error}`
    : "";
  drawLayers(structure);
  const rows = structure.trials
    .slice()
    .reverse()
    .map(
      (trial) => `<tr>
        <td>${escapeText(formatDate(trial.date_utc))}</td>
        <td>${escapeText(trial.kind)}</td>
        <td>${trial.breakage === null || trial.breakage === undefined ? "—" : trial.breakage ? "on" : "off"}</td>
        <td>${escapeText(trialLabel(trial))}</td>
        <td title="${escapeText(trial.failure || "")}">${escapeText((trial.failure || "").replace(/: connected=[\s\S]*$/, ""))}</td>
        <td>${escapeText(Object.entries(trial.controller_settings || {}).map(([key, value]) => `${key}=${value}`).join(", "))}</td>
        <td>${trial.run_id ? `<button class="case-link" type="button" data-run="${escapeText(trial.run_id)}">Open run</button>` : ""}</td>
      </tr>`,
    );
  byId("structure-trial-count").textContent = String(structure.trials.length);
  byId("structure-trials").innerHTML =
    "<thead><tr><th>Date</th><th>Kind</th><th>Breakage</th><th>Connected</th><th>First failure</th><th>Changed settings</th><th></th></tr></thead>" +
    `<tbody>${rows.join("") || '<tr><td colspan="7">No trials recorded yet.</td></tr>'}</tbody>`;
  for (const button of byId("structure-trials").querySelectorAll("[data-run]"))
    button.addEventListener("click", () => openRun(button.dataset.run));
  let overviewSection = null;
  byId("structure-overview").innerHTML =
    "<thead><tr><th>Structure</th><th>Bricks</th><th>Simulation, standard settings</th><th>Real robot</th></tr></thead><tbody>" +
    structures
      .map((item) => {
        const section = sectionTitle(item);
        const header =
          section !== overviewSection
            ? `<tr class="section-row"><td colspan="4">${escapeText(section)}</td></tr>`
            : "";
        overviewSection = section;
        return `${header}<tr class="${item.name === name ? "active" : ""}">
          <td><button class="case-link" type="button" data-structure="${escapeText(item.name)}">${escapeText(structureTitle(item))}</button></td>
          <td>${item.brick_count}</td>
          <td>${escapeText(defaultLabel(item))}</td>
          <td>${escapeText(trialLabel(latestTrial(item, "real", null)))}</td>
        </tr>`;
      })
      .join("") +
    "</tbody>";
  for (const button of byId("structure-overview").querySelectorAll(
    "[data-structure]",
  ))
    button.addEventListener("click", () =>
      showStructure(button.dataset.structure),
    );
}

/** Load structures and their trials, keeping the selected structure. */
async function loadStructures() {
  byId("refresh").disabled = true;
  try {
    const response = await fetch("/api/structures", { cache: "no-store" });
    if (!response.ok)
      throw new Error(`Unable to read the structures (${response.status}).`);
    structures = await response.json();
    renderStructureList();
    const next =
      structures.find((item) => item.name === selectedStructure) ||
      structures[0];
    if (next) showStructure(next.name);
  } catch (error) {
    byId("structure-view").hidden = true;
    byId("error").hidden = false;
    byId("error-message").textContent = error.message;
  } finally {
    byId("refresh").disabled = false;
  }
}

/** Mark one filter button active and render the list it selects. */
function setFilter(filter) {
  activeFilter = filter;
  for (const item of document.querySelectorAll(".filter")) {
    item.classList.toggle("active", item.dataset.filter === filter);
    item.setAttribute(
      "aria-pressed",
      item.dataset.filter === filter ? "true" : "false",
    );
  }
  if (filter === "structures") {
    loadStructures();
    return;
  }
  byId("structure-view").hidden = true;
  if (currentRun) byId("content").hidden = false;
  renderRuns();
}

/** Leave the structure view and open one recording in the run library. */
function openRun(id) {
  setFilter("all");
  selectRun(id);
}

/** Refresh the discovered recordings while preserving the selected run. */
async function loadRuns() {
  byId("refresh").disabled = true;
  byId("error").hidden = true;
  if (!currentRun) byId("loading").hidden = false;
  try {
    const response = await fetch("/api/runs", { cache: "no-store" });
    if (!response.ok)
      throw new Error(`Unable to read the run library (${response.status}).`);
    runs = await response.json();
    renderRuns();
    byId("loading").hidden = true;
    if (!runs.length) {
      currentRun = null;
      byId("content").hidden = true;
      byId("empty").hidden = false;
      return;
    }
    byId("empty").hidden = true;
    const next = runs.find((run) => run.id === selectedId) || runs[0];
    await selectRun(next.id);
  } catch (error) {
    byId("loading").hidden = true;
    byId("content").hidden = true;
    byId("empty").hidden = true;
    byId("error").hidden = false;
    byId("error-message").textContent = error.message;
  } finally {
    byId("refresh").disabled = false;
  }
}

byId("search").addEventListener("input", () =>
  activeFilter === "structures" ? renderStructureList() : renderRuns(),
);
for (const button of document.querySelectorAll(".filter"))
  button.addEventListener("click", () => setFilter(button.dataset.filter));
byId("signal").addEventListener("change", drawChart);
const refreshView = () =>
  activeFilter === "structures" ? loadStructures() : loadRuns();
byId("refresh").addEventListener("click", refreshView);
byId("retry").addEventListener("click", refreshView);
new ResizeObserver(drawChart).observe(byId("chart").parentElement);
loadRuns();
