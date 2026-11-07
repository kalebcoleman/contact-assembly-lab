# Research notebook

Dates use America/Phoenix unless stated otherwise. Run-folder timestamps use UTC.

## 2026-10-26 — Direction and first scene integration

**User-stated objective:** ASU RISE digital twin research, including custom
physics, friction-sensitive complex tasks, lab robot USDs, and cooperating arms.
The selected first target is two arms manipulating a shared object. Brick
assembly is the installation baseline, not the task domain.

**Context supplied by user:** Max and Wenlong requested robot/workstation USDs
for Kaleb. Aldrin supplied `inbarajaldrin/omni-kit-mcp` and
`inbarajaldrin/isaac-sim-mcp` as lab assets and simulator-control starting points.
This establishes provenance; calibration fidelity and current lab configuration
remain to be checked.

**Rejected first baseline:** two generic NVIDIA UR5e articulations loaded with six
joints each, but the finite-state check missed extreme physical divergence.
Evidence retained: `outputs/rise/20261027T054624.215389Z/` (manifest annotated
`review_status=rejected_physical_divergence`). Configuration hash:
`356a2175f1b627abfe50dac202f77cd2c465696ccbc05654d99105ec6683f0ad`.
Two intermediate setup failures are also retained in timestamped run folders.

**Cause and correction:** SingleArticulation resolved the root-joint prim;
assigning position through it did not move the complete model, leaving both
arms overlapping. Author the complete robot's parent Xform pose, preserve its
transform properties, and enforce physical bounds instead of only NaN/Inf checks.

**Accepted scene baseline:** `outputs/rise/20261027T061121.266491Z/` recorded
120 samples over two simulation seconds. Maximum joint target error:
4.371139006309477e-8 rad. Final object position:
[-3.113757784944937e-8, -3.8314783523674123e-7, 0.4249999523162842] m.
Acceptance for this smoke test: joint errors below 0.25 rad and object coordinates
within 5 m. No grasp, coordinated movement, friction calibration, or physical
robot control was attempted. Unused robot_gripper_joint asset warnings remain
to audit before gripper work. Manifest and summary.json preserve the evidence.

**Integration findings:** the lab repositories contain a rigged UR5e, RG2
gripper, camera, Vention workstation, and assembly objects. The lab extension's
old `register_tool` API did not match the generic bridge's owner registry.
Applied a local compatibility patch using a `ur5e` namespace, preserving the
checkpoint-policy hooks by normalizing that namespace. Both MCP gateways then
passed actual stdio MCP initialization and discovery: 8 generic tools and 30
lab-endpoint tools (including builtins and gateway refresh).

**Additional findings:** the lab Quick Start skipped initializing a Python
World when a USD PhysicsScene already existed, causing `warm_start` on None.
Added a physics-context check. Its redirected log stream lacked `isatty`, which
broke uvicorn logging initialization; added terminal-detection delegation.
These are local patches, not upstream releases. Full Quick Start with workstation
passed; MCP inspection confirmed /World/UR5e, /World/RG2_Gripper, /World/Vention,
and /World/workspace_camera_sim. See `outputs/rise/mcp-validation.json` and
MCP_SETUP.md. Physical driver tools were not invoked. The lab model explicitly
disables robot-chain gravity for position mirroring, so it is separate from the
force-controlled cooperative benchmark.

**Code verification:** Ruff and four invalid-configuration tests pass. Generated
local type-checker extension overlays; vendor Scene.add / pxr annotations still
produce diagnostics, so this is not a clean static-type-check result.

**Decision:** keep the generic two-arm baseline separate from the lab's
single-arm Quick Start. Port the calibrated gripper and cell deliberately after
auditing joints and frames. Do not claim that importing the lab models creates
a validated twin.

**Next research discussion:** confirm shared object/task, gripper model, robot
base separation, available sensor logs, and numerical task-success criteria.
Then establish a stationary two-arm hold before coordinated object motion.

## 2026-10-26 — ChatGPT tunnel registration

The user approved creating **RISE Isaac Sim** in the Personal Platform
organization, linked to the available ChatGPT workspace. Creation was verified
in the Platform UI. Tunnel ID: `tunnel_6ae0430847888191a155fc8c3f92f1b3`.
Configured the local stdio profile with an environment secret reference.
Prepared a restricted 30-day runtime key form (Tunnels Read + Use only), but
automatic approval review rejected its final creation click. The user subsequently
reported completing key creation; the secret has not been read by the agent.
Added `scripts/start_chatgpt_tunnel.sh` for hidden-input
runtime-key entry, doctor validation, and foreground operation.
Verified the user's existing visible simulator bridge is running (30 advertised
tools on port 8766). Runtime authentication and a connected ChatGPT tool call
are not verified yet; the user was directed to enter the key in their terminal.

**2026-10-28 update:** tunnel route removed at the user's request; local files
moved to Trash. Revoke the Platform tunnel and runtime key in the OpenAI UI.

## 2026-10-26 — Local Codex lab scene

The user chose local Codex for simulator control. Started a visible lab
simulator and invoked the lab Quick Start with workstation; it returned
`status: success`. Both configured stdio MCP gateways initialized, listed
tools, and returned the same simulator PID via their status tools: `rise-kit`
advertised 8 tools; `rise-isaac` advertised 30, including the lab Quick Start.
The local Codex entries are enabled. A fresh local Codex chat called
`mcp__rise_isaac__status` and `mcp__rise_isaac__run_python` directly; both
succeeded and confirmed all five lab scene prims were valid, active, and loaded.
The original chat's tool catalog may still require a reload or fresh session.

The lab Quick Start is a position-mirrored single-arm scene. It disables
robot-chain gravity and the workstation is visual-only; the ground-plane
collider supplies the support surface. It is not yet a calibrated
force/contact model. No physical robot driver was started.

Automatic approval review blocked a further scene-inspection command due to
the account's review usage limit. The platform reported a review failure, not
a finding that the command was unsafe. The Quick Start's success response is
available, but its individual scene prims were not independently checked in
this session.

## 2026-10-27 — Single-arm collision and tracking baseline

Corrected the earlier audit: the UR5e has seven enabled convex-decomposition
colliders inside USD instances. Ordinary traversal missed them. Added 385
static oriented-box Vention CAD-part proxies in the lab loader; holes and
concavities are approximated, not calibrated.

PhysX contact reports identified the flat-pose +0.03 rad shoulder error as
wrist/quick-changer interference with the legacy table/plane. Negative
commands tracked accurately. Preserved drive gains and introduced a -0.30 rad
shoulder target reached through drives. An intermediate initial-coordinate
teleport destabilized the separately welded gripper and was rejected; the
original consistent initial coordinates are retained.

Final live suite: all 12 bidirectional joint tests passed (worst error
4.7684e-6 rad); shoulder errors 3.7849e-6 / 3.8147e-6 rad. RGB/depth was
640x480 with 100% finite positive depth. With legacy supporting surfaces
disabled temporarily, a 4 cm probe settled on Vention at -0.0654746592 m center
height and generated actual bench collision events. Another probe contacted
the UR5e forearm. Cleanup removed probes, restored supporting surfaces, and
verified a 3.6061e-6 rad return error. A camera-detach cleanup error was fixed
before this successful full rerun. Syntax and whitespace checks also passed.

Evidence: `../../isaac-sim-mcp/resources/workstation-validation/report.json`,
camera.png in the same directory, and the workspace-wide
[post-clone inventory](../../POST_CLONE_CHANGES.md). Current panel top is about
85 mm below the legacy work plane; physical table/base calibration remains
necessary. No friction/force calibration, grasp retention, physical driver,
or second lab arm was tested or added. The simulation was left playing at
the raised target, with both MCP bridges available.

## 2026-10-27 — Opposite-end lab two-arm baseline and USDA checkpoints

Added a complete second lab UR5e/QC/RG2 rig in `/World/Arm2`, remapping joint
and material targets so no second-rig joint targets the first. The first
0.65 m side placement passed independent movement and upper-arm collision
tests; these results remain separately archived.

The user requested the arms at opposite table ends facing one another and
USDA checkpoints at meaningful milestones. Final bases are (+0.75, -0.30, 0)
and (-0.75, -0.30, 0) m, yaw 180 / 0 degrees. Both home shoulders are -0.80 rad.
Complete welded rigs were folded through drives, captured together, and moved
with consistent arm/gripper poses; source assets were not overwritten.

All 24 bidirectional joint cases passed, including stationary-arm hold checks;
worst error was 0.000499834 rad against 0.001 rad acceptance. Gradual shoulder
extension generated real forearm-forearm contact at -0.50 rad commands, peak
solver impulse 0.925822 N*s, about 0.0065 rad joint deflection, and minimum
reported separation -2.862e-6 m. Withdrawal left no inter-rig contact; return
errors 7.749e-6 / 6.551e-5 rad. States stayed finite.

Evidence: `../../isaac-sim-mcp/resources/dual-arm-end-table-validation/` contains
JSON measurements and home/contact camera images. Stage checkpoints in
`../../checkpoints/` retain the prior stage, dynamically folded stage,
positioned stage, and accepted validated stage, with JSON/SHA256 provenance.
Latest accepted file: `20261027T071807.819020Z-03-end-table-validated.usda`.
It reopened independently with all payloads loaded and zero composition errors.
Live scene remains at separated home with the overview camera selected.

The checkpoint copies normalize velocities and hold saved joint states; they
reference existing local assets and do not capture solver caches or running
controller processes. Placement/mounting, friction, force accuracy, and
coordinated shared-object manipulation remain uncalibrated. Robot gravity is
disabled as in the supplied position-mirroring rig. No physical driver was
started. See the [experiment guide](../../isaac-sim-mcp/docs/DUAL_ARM_EXPERIMENT.md)
and [post-clone inventory](../../POST_CLONE_CHANGES.md) for full changes.

## 2026-10-27 — Shared-object lift and checkpoint playback correction

The user requested a shared object, a real two-gripper grasp/lift test, and a
USDA checkpoint on success. Both MCP endpoints were initially unavailable;
at the user's request the visible lab application was reopened and the prior
checkpoint loaded. This exposed the screenshot's PhysX broadphase failure.
The prior stage had passed live/composition checks but had not passed actual
reloaded physics playback. It is superseded, not a valid resume point.

Canonical first-rig definitions restored 16 second-rig joint frames altered
by posed body-relationship remapping. Checkpoint normalization now loads all
payloads (24 joint states normalized), and a repaired baseline passed actual
playback for both arms and both grippers. The repair is preserved in source.

Added a 650x35x60 mm, 0.1 kg shared bar with gravity, static friction 0.8 and
dynamic friction 0.6. Verified USD FK against measured pads, solved top-down
IK at x=+/-0.22 m, and coordinated approach/closure/100 mm lift. No object
weld, kinematic pose updates during lift, disabled gravity, or hidden supports.

Rejected trial 001 used linkage instead of fingertip contact. Trial 002 moved
the object during initialization. Trial 003 grasp/lift/hold passed but exposed
a queued USD close target overriding tensor-only release. Raising the grasp
datum, clearing the setup area, preserving initial arm targets, and synchronizing
USD/tensor gripper commands corrected these issues. All trials are retained.

Accepted trial 004: minimum object clearance 99.388 mm over two seconds,
maximum relative slip 1.718 mm, four fingertip contacts in 100% of hold samples.
Opening both grippers caused a 99.522 mm gravity-driven drop. Reloading the
held stage retained the grasp. The exact final 06 checkpoint then played for
two more seconds with 99.495 mm minimum clearance, four contacts, gravity
enabled, kinematic false, and no object joints.

Latest accepted checkpoint:
`../../checkpoints/20261027T162819.114595Z-06-shared-grasp-lift-validated.usda`.
JSON/SHA256 metadata is beside it. Evidence is in
`../../isaac-sim-mcp/resources/shared-object-validation/trial-004/`.
The source checkpoint helper preserves force-limited closing preload for a
loaded grasp. The simulator is left playing the successful hold; no physical
driver was started. See the [experiment record](../../isaac-sim-mcp/docs/SHARED_OBJECT_EXPERIMENT.md).
This is one accepted deterministic trial, not friction/force calibration,
physical validation, randomized robustness, or measured load-sharing accuracy.

## 2026-10-27 — Coordinated bar translation and rotation

From accepted grasp checkpoint 06, both arms moved the physically held bar
through a 50 mm Y / 30 mm Z translation, +10 degree yaw, +5 degree pitch,
return, then a (25,25,25) mm offset with -10 degree yaw. Object-relative grasp
frames generated both IK targets; only native arm targets moved. The original
grip-force caps, object gravity, and contact/friction grasp were preserved.

Trial 001 passed without retries: 449 samples over 32.917 simulation seconds,
maximum motion slip 0.0825 mm / 0.02451 degrees, all four fingers contacting in
100% of sampled states, minimum clearance 99.486 mm, zero unexpected collision
events. Object goal errors (distinct from slip) were at most 1.155 mm /
0.2016 degrees. Inter-arm, non-mount robot/environment, and non-finger bar
contacts were monitored; fixed-base mounting and same-rig fixture contacts
were excluded. Existing self-collision policy was not changed or validated.

Intermediate replay passed with maximum relative slip 0.1217 mm / 0.03205
degrees. Final checkpoint 08 was then independently reloaded and physically
played for two seconds: 124.411 mm minimum clearance, four finger contacts,
no unexpected contacts, gravity enabled, kinematic false, no object joints.

Checkpoint:
`../../checkpoints/20261027T164045.283144Z-08-coordinated-bar-motion-validated.usda`.
Results and images: `../../isaac-sim-mcp/resources/coordinated-bar-validation/trial-001/`.
See the [motion record](../../isaac-sim-mcp/docs/COORDINATED_BAR_MOTION.md).
The simulator is left playing the final held pose. No physical driver was
started. This is one slow deterministic simulated trajectory; force/load
sharing, parameter calibration, robustness, and arbitrary safe paths remain
unvalidated.

## 2026-10-27 — Bar load/speed limits and checkpoint usability

The user requested heavier/faster trials and clearer checkpoint names. Added
short Approved copies: Empty Hands, Grasp and Lift, Move and Rotate, plus
Heavier Bars/Faster Moves/Combined Loads folders named by mass and speed. JSON
notes were separated into Test Notes folders. Content browser was navigated
to Approved; original timestamped checkpoints and test provenance were retained.

Twenty independent trials reset to accepted grasp 06, changing only mass with
matching cuboid inertia and requested trajectory durations. Fixed bar geometry
650x35x60 mm, object friction 0.8/0.6, original drive gains/caps, and gravity
settings. Drift references were captured before mass loading. Thresholds:
relative drift 2 mm / 1 degree, path error 10 mm / 5 degrees, clearance 50 mm,
sampled four-finger contact >=95%, no unexpected contact, checkpoint replay.

Thirteen trials passed. At 1x, 1.25 kg passed and 1.5 kg exceeded relative drift
(4.869 mm), both repeated with the same outcome. A 2 kg bar dropped to the
ground-plane collider at 0.25 simulation seconds before movement. At 0.1 kg,
5x passed while 6x crossed path-tracking error (10.052 mm), both repeated.
Grip drift at the 6x stop was only 0.252 mm: this is not a gripper-slip speed
boundary. The completed 5x pass reached about 0.104 m/s and 17.70 degrees/s.

Combined 1.25 kg/2x and 0.625 kg/5x passed; 1.25 kg/5x failed tracking. Eleven
short-named successful stage copies were independently replayed: actual mass
matched, gravity enabled, kinematic false, all four contacts in every replay
sample, no support contacts, less than 0.18 mm replay drift.

Full evidence: `../../isaac-sim-mcp/resources/bar-load-speed-limits/run-001/`.
The [limit record](../../isaac-sim-mcp/docs/BAR_LOAD_SPEED_LIMITS.md) includes
thresholds, repetitions, measured speeds, failure mechanisms, the untested-cell
map, and human-readable checkpoint locations. These are deterministic
simulation brackets, not statistical confidence or physical robot ratings.
Opening a checkpoint restores a held pose/test mass, not a motion recording.

## New entry template

Experiment ID / date / question:

Hypothesis and controlled conditions:

Run directory and source/config/asset revisions:

Measurements and acceptance criteria:

Observed result, including failures:

Interpretation and uncertainty:

Next test and supervisor feedback:
