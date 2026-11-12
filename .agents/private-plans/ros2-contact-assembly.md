# ROS 2 mock assembly controller

## Purpose / Big Picture

Add a Python 3.10 ROS 2 Humble package under ros2/risl_contact_assembly that plans known brick poses and rehearses assembly without connecting to hardware. Follow .agents/PLANS.md. Real insertion is not validated by simulation or mock execution.

## Progress

- [x] 2026-11-12: Verified Ubuntu 22.04 laptop, Humble, colcon and vcs; cloned Kaleb repo and began local Max workspace import.
- [x] 2026-11-12: Delegated planner, executor, mock infrastructure, and documentation/compatibility to four OpenCode asu/deepseek-v4-1-flash children in isolated T3 worktrees.
- [x] Received/reviewed planner, infrastructure and docs commits; cancelled the uncommitted executor child and completed its implementation in the coordinator.
- [x] Integrated code; independent colcon build/test (46 tests), Ruff, scoped ty, and one/three-brick official mock dry runs pass.
- [ ] Moving trajectory execution remains unverified; retained as an explicit draft-PR limitation.
- [ ] Record evidence and open one PR on Kaleb repo; never merge.

## Surprises & Discoveries

UR driver apt packages are absent. sudo is blocked by no-new-privileges. Isaac MCP source exists at /home/kaleb/isaac-workspace/isaac-mcp but no Isaac tool is exposed. ~/ros2_ws/src was initially empty. Coordinator takeover confirmed all six imported repository directories and /opt/ros/humble exist; builds remain unverified.

## Decision Log

User explicitly requires opencode asu/deepseek-v4-1-flash; this supersedes AGENTS.md model preference. All runtime commands must use ROS_LOCALHOST_ONLY=1 and ROS_DOMAIN_ID=83. Never connect to 192.168.1.111 or 192.168.7.2, run socat, command hardware, or modify network settings. No Max upstream writes. Mock launcher hardcodes mock hardware and loopback IP. Dry-run publishes no control commands. An explicit mock execution mode may exercise the mock controller, with proof of mock configuration. Hardware use remains unverified.

## Context and Orientation

Simulation lives in experiments/ur5e_assembly; docs/structures/index.json is a catalog, inspect actual referenced structure data. Max source imports into /home/kaleb/ros2_ws/src. New package is ament_python and independent of simulator Python dependencies.

## Interfaces and Dependencies

Shared implementation contract: planner.py exports load_config(path)->dict, load_structure(path)->dict, plan_structure(structure:dict, config:dict)->list[dict]. Each step has action (approach, descend, close, lift, transfer, approach_target, slow_descend, seat, open, retreat), brick_id string, xyz_m list of three floats, rpy_deg list of three floats, speed_m_s positive float, and optional gripper_width_mm. Poses are TCP in base, units SI except explicit degree/mm fields. Config has baseplate {origin_xyz_m,yaw_deg,stud_pitch_m:0.008,brick_height_m:0.0096}, pickup {xyz_m,rpy_deg,gripper_width_mm}, where xyz_m/rpy_deg are an absolute fixture TCP pose in UR base; an explicit calibrated brick-to-TCP rigid transform supplies target TCP offsets (translation in brick axes and orientation convention documented in YAML), limits {workspace_min_m,workspace_max_m,max_speed_m_s,max_speed_scale}, motion {hover_m,travel_speed_m_s,descend_speed_m_s}, seating {force_n,max_travel_m,timeout_s}. Planner owns fixtures/config schema and tests. Executor consumes these fields and validates independently. Executor ROS parameters: config_file, structure_file, dry_run=true, confirm_each_step=true, pose_source=known_poses, step_log, mock_execution=false. Entry points assembly_executor=risl_contact_assembly.executor:main, fake_gripper=risl_contact_assembly.fake_gripper:main, record_joint_states=risl_contact_assembly.record_joint_states:main. Mock infrastructure owns package metadata and launch; planner owns __init__.py. Integration may adapt contracts based on evidence.

## Plan of Work

First children implement disjoint files in T3 worktrees and commit locally. Coordinator reviews each diff and cherry-picks accepted commits. Then install/build dependencies locally without sudo if feasible. Source /opt/ros/humble/setup.bash and run colcon build --base-paths ros2; run python3 -m pytest on package tests and colcon test then colcon test-result --verbose. Launch mock only on isolated localhost domain and record joint states and step JSONL for single and three bricks. Check completed steps and actual joint movement separately from dry-run logs. Record failures without substituting fabricated evidence.

## Validation and Acceptance

Planner tests must cover transforms, pitch/height, order, invalid/nonfinite inputs and workspace limits. Executor tests cover dry-run command absence, stale/missing feedback, timeout and overtravel stop behavior. Mock evidence must distinguish plan rehearsal from actual trajectory execution and force-mode emulation. Parent independently verifies all results.

## Idempotence and Recovery

Only additive changes under ros2 and this plan. Keep Max fixes local, record patches; no pushes there. Stop only processes launched for this task. Preserve failing tests and diagnostics. If dependencies cannot be installed, report blocked checks explicitly.

## Outcomes & Retrospective

Planner, guarded executor, official mock launch and documentation implemented. Verified dry-run rehearsal only; physical execution is disabled. Moving trajectories and hardware seating remain unverified.

## Coordinator handoff

Implementation ownership transferred to this project-bound coordinator. Four editing delegates launched: planner 53f22397-e8f0-436e-9524-8f19bb9919c9; executor f936aa58-0341-4367-94b2-49cf19b95e6d; mock infrastructure 9c653dd1-8f40-419a-bd33-c378841b0c12; documentation 2847ee73-af82-472c-ac0c-e6a67b06ed0f. All use OpenCode asu/deepseek-v4-1-flash. Children commit locally without pushing; parent independently reviews and verifies. Their completions wake this thread. Original coordinator will forward separate read-only research.

Revision 2026-11-12: recorded authorized takeover, verified imported directory inventory, and started disjoint implementation work. No hardware contacted.

Revision 2026-11-12 (research corrections): this laptop is robot-side. Independently read cell.launch.py (hardcoded mock=false and unconditional real gripper), rg_gripper.py (constructor invokes socat), and Bota config (460800 USB baud). Do not launch those paths. Hardware seating remains blocked until sensing, calibration and force/travel limits are validated; never recommend open-loop seating to bypass missing force feedback. Numeric mock defaults are unvalidated for hardware. Forwarded corrections to running executor, mock and documentation delegates. Only necessary local build fixes are in scope; no upstream redesign.

Revision 2026-11-12 (planner semantics): independently inspected native compute_transform and stud/hole interface poses, confirming support-grid offset rotation and accumulated child yaw. Source simulation positions remain stage coordinates; only explicit YAML calibration defines UR base targets. Pickup is an absolute fixture TCP pose, never an offset. Simulation grasp/release/press settings are unvalidated hints, not automatically applied. seating.force_n is requested force, not a measured force limit. Forwarded to planner/executor/docs. Independent numeric cross-checks remain pending implementation.

Revision 2026-11-12 (executor review): keep base, explicitly verify base_link rotation against driver; use time.monotonic deadlines; no tolerance added to travel cap; no seated-success inference from travel; verify interpolated TCP workspace/speed. Independently confirmed MotionExecutor constructs command clients/publishers and prestarts controllers, and IK returns best candidates despite excessive residuals. Running delegates received corrections. apt-cache provides driver 2.15.0, controller-manager 2.54.3, control-msgs 4.9.0 and ur-description 2.14.0 candidates; rootless dependency feasibility remains open, not disproven by sudo failure. Apt simulation recorded in private mock-dependencies.txt without installation.

Revision 2026-11-12 (official driver route): independently inspected extracted driver2.15 launch and description xacro; ur_control uses use_fake_hardware=true, selects mock_components/GenericSystem, skips hardware-specific nodes, and removes tcp_pose_broadcaster. base_link to base is explicitly pi about Z in ur_macro.xacro. Copied/extracted official debs into ignored repository-local .agents/private-plans/ros-overlay excluding socat; no system installation. Source env.sh there for validation. Official driver action-based mock is required; topic-only mock is not acceptance. Prior research child disclosed an unauthorized ur5e launch attempt with missing robot_ip; it claims argument validation stopped execution. Parent process snapshot found no matching running driver/socat process, which cannot prove absence of historical sockets. Preserve disclosure in final report.

Revision 2026-11-12 after sleep: inspected all four implementation threads; all report running with post-wake activity, no replacement needed. Sent continue and verified-flag instructions. Recovered original unauthorized research launch log and wrote ros2/evidence/research-launch-incident.md plus unchanged log copy; include incident in final PR description. Parent tree has no integrated child code yet. Build, tests, official mock dry/moving evidence and one PR remain outstanding.

Revision 2026-11-12 infrastructure integration: reviewed child commit 6f22fff and cherry-picked as ddbe6df. Parent independently ran test_mock_infrastructure.py: 14 passed in 0.16s. Expanded official UR5e xacro with loopback/use_fake_hardware=true/tool communication=false and parsed XML: sole hardware plugin mock_components/GenericSystem. Built a private copy of Max risl_ur with colcon (1 package finished), leaving upstream checkout unchanged; use .agents/private-plans/max-install/local_setup.bash after overlay env.sh. No ROS nodes launched. Infrastructure currently lacks executor launch integration; add dry-run parameters after executor arrives. Planner, executor, docs commits still pending.

Revision 2026-11-12 docs integration: reviewed/cherry-picked 2be9a00 as e4cc608; corrected feedback topic, allowed fake driver wording, contradictory include statement, unchecked IK candidate semantics, and test-result flags. Independently checked colcon help. Final config/schema/commands and validation evidence await remaining planner/executor commits. Incident linked from README.

Independent frame check: parsed expanded official URDF joints and composed world-to-base/world-to-tool0 transforms at zero joints and [1.57,-1.2,1.4,-1.8,-1.57,0.3] rad. Compared base-to-tool0 against installed Max forward_kinematics: position errors 6.29e-11/4.27e-11 m; rotation errors 2.05e-10/3.52e-10 rad. Confirms nominal DH frame convention for these samples, not physical calibration.

Revision 2026-11-12 planner and live infrastructure: cherry-picked bab0d989 as 53c4001; parent 30 tests pass after adding H3-only regression. Independent validator cross-check passed 29 structures/206 targets at plate yaw37deg. colcon build passes. Launched official fake driver with package fake gripper/recorder; live hardware class and robot_description both verify GenericSystem, scaled trajectory controller active; gripper command publishers zero before probe, query returned110mm. Evidence ros2/evidence/initial-mock-verification.json. All launched processes stopped; fixed Python Ctrl-C cleanup after observing traceback exits. Executor still pending; this is not assembly execution evidence.

Revision 2026-11-12 executor recovery: user reported inaccessible child. Thread read showed active lint work, uncommitted executor/test files; requested task cancellation and copied those files for authorized parent completion. Replaced MotionExecutor constructor with direct standard action client; added live GenericSystem/robot-description/gripper gates, derived mock FK feedback, monotonic active-motion guards, no physical execution, and launch integration with dry_run=true. Parent pytest/colcon:45 pass; ruff and scoped ty with Humble/overlay paths pass. One/three-brick official mock dry runs:10/30 planned,0 executed,138/118 joint samples with0 displacement,0 observed gripper-command publishers; all launch processes stopped. Scope remains dry-run evidence, no moving-trajectory or physical seating validation. Final README and PR in progress.

User scope update: no questions-for-Max sections in docs, PR or final response. Keep unresolved lab calibration facts beside technical requirements. Final three-brick rerun exposed subtractive float error at the exact travel cap; compare approach_z > target_z + cap without widening cap, regression checks three layers and rejects1e-10m excess.

Final validation:46 tests pass, scoped Ruff/ty pass. Final dry traces contain133/1417 samples, zero displacement and10/30 planned steps, zero executed. One mock controller required launch SIGTERM escalation after5s; final process inventory empty. Preparing one draft PR because moving-trajectory execution remains unverified, with incident disclosure and no questions-for-Max section per user.
