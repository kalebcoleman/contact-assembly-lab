# Experiment results viewer

Open recorded UR5e brick experiments in a local, read-only browser dashboard.
From the repository root, run:

    python3 experiments/ur5e_dashboard/server.py

Open `http://127.0.0.1:8765` and select a run. The committed example recordings
and videos appear immediately. The server uses only the Python standard library;
Isaac Sim does not need to be running. Stop the server with Ctrl+C.

To inspect recordings in another checkout, or choose a different local port:

    python3 experiments/ur5e_dashboard/server.py --experiment-root /path/to/checkout --port 8766

The selected root may contain live or archived JSON Lines files under
`outputs/ur5e_lego/` and the committed compressed examples under
`experiments/ur5e_lego/docs/evidence/`. Matching plain and compressed logs are
listed once. A new video can be placed beside its log with the same base name,
for example `example.jsonl` and `example.mp4`. Press **Refresh runs** after new
data is written. An unfinished recording is marked incomplete. A recording
with unreadable metadata is skipped; malformed contents are marked invalid.
Other recordings remain available. The viewer does not control or modify the
simulator or files.

The run list, phase history, connection state, last pre-connection alignment,
settings, and signal plots come from the recorded samples. The plots preserve
the minimum and maximum in each display window, along with missing-data gaps;
intermediate values can be reduced. Phase and connection events are computed
from every recorded sample. Download the source log for full-resolution data.
The recorded elapsed time labels the end of the physics step; samples precede
that step, so subtract `physics_dt_s` for the sample time.
Video playback is independent of log time. Some curated videos show a different
trial of the same experiment, as identified beside the video.

The documented controlled-rejection trial is identified by its recorded
experiment and timestamp and labeled as an intentional failure test. Its
recorded controller outcome is shown separately. Other failed or incomplete
runs are not assumed to be intentional.

The **Test cases** filter lists the simulation test suite described in
[UR5e simulation test cases](../ur5e_lego/docs/ur5e-cases.md). Each case shows
its inputs, written prediction, observed outcome, measurements, what is physics
versus assisted, limits, provenance, and links to its logs. A result attaches
only to the exact recording the suite measured, identified by case and creation
time, so a later local re-run is labeled as not in the published suite. A video
is labeled either as this run's recording or as a representative recording of
another case.

All current logs are simulation data. Tool and part poses are in the world
frame, placement errors are in the support frame, joint angles are radians,
positions are meters, and force is in newtons. The viewer converts placement
errors and tolerances to millimeters. The Z value is the gap from the seated
pose, not a physical force or a hardware accuracy measurement. USD poses may
update at the render rate; contact debug data is available only when recorded.
NaN and Infinity tokens are shown as unavailable. Numbers that overflow while
decoding or processing cause the recording to be skipped or marked invalid.
The recorded video and data do not establish physical robot performance.

Run the focused checks from the repository root:

    python3 -m unittest discover -s experiments/ur5e_dashboard -p 'test_*.py'

To also check browser label formatting, use Node.js:

    node --test experiments/ur5e_dashboard/test_app.cjs
