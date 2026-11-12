# ROS 2 mock assembly controller

## Purpose / Big Picture

Add a Python 3.10 ROS 2 Humble package under ros2/risl_contact_assembly that plans known brick poses and rehearses assembly without connecting to hardware. Follow .agents/PLANS.md. Real insertion is not validated by simulation or mock execution.

## Progress

- [x] 2026-11-12: Verified Ubuntu 22.04 laptop, Humble, colcon and vcs; cloned Kaleb repo and began local Max workspace import.
- [ ] Delegate planner, executor, mock infrastructure, and documentation/compatibility to four DeepSeek children.
- [ ] Review and integrate commits; independently run pytest, colcon build/test and one/three-brick mock runs.
- [ ] Record evidence and open one PR on Kaleb repo; never merge.

## Surprises & Discoveries

UR driver apt packages are absent. sudo is blocked by no-new-privileges. Isaac MCP source exists at /home/kaleb/isaac-workspace/isaac-mcp but no Isaac tool is exposed. ~/ros2_ws/src was empty.

## Decision Log

User explicitly requires opencode asu/deepseek-v4-1-flash; this supersedes AGENTS.md model preference. All runtime commands must use ROS_LOCALHOST_ONLY=1 and ROS_DOMAIN_ID=83. Never connect to 192.168.1.111 or 192.168.7.2, run socat, command hardware, or modify network settings. No Max upstream writes. Mock launcher hardcodes mock hardware and loopback IP. Dry-run publishes no control commands. An explicit mock execution mode may exercise the mock controller, with proof of mock configuration. Hardware use remains unverified.

## Context and Orientation

Simulation lives in experiments/ur5e_assembly; docs/structures/index.json is a catalog, inspect actual referenced structure data. Max source imports into /home/kaleb/ros2_ws/src. New package is ament_python and independent of simulator Python dependencies.

## Interfaces and Dependencies

Shared implementation contract: planner.py exports load_config(path)->dict, load_structure(path)->dict, plan_structure(structure:dict, config:dict)->list[dict]. Each step has action (approach, descend, close, lift, transfer, approach_target, slow_descend, seat, open, retreat), brick_id string, xyz_m list of three floats, rpy_deg list of three floats, speed_m_s positive float, and optional gripper_width_mm. Poses are TCP in base, units SI except explicit degree/mm fields. Config has baseplate {origin_xyz_m,yaw_deg,stud_pitch_m:0.008,brick_height_m:0.0096}, pickup {xyz_m,rpy_deg,gripper_width_mm}, limits {workspace_min_m,workspace_max_m,max_speed_m_s,max_speed_scale}, motion {hover_m,travel_speed_m_s,descend_speed_m_s}, seating {force_n,max_travel_m,timeout_s}. Planner owns fixtures/config schema and tests. Executor consumes these fields and validates independently. Executor ROS parameters: config_file, structure_file, dry_run=true, confirm_each_step=true, pose_source=known_poses, step_log, mock_execution=false. Entry points assembly_executor=risl_contact_assembly.executor:main, fake_gripper=risl_contact_assembly.fake_gripper:main, record_joint_states=risl_contact_assembly.record_joint_states:main. Mock infrastructure owns package metadata and launch; planner owns __init__.py. Integration may adapt contracts based on evidence.

## Plan of Work

First children implement disjoint files in T3 worktrees and commit locally. Coordinator reviews each diff and cherry-picks accepted commits. Then install/build dependencies locally without sudo if feasible. Source /opt/ros/humble/setup.bash and run colcon build --base-paths ros2; run python3 -m pytest on package tests and colcon test then colcon test-result --verbose. Launch mock only on isolated localhost domain and record joint states and step JSONL for single and three bricks. Check completed steps and actual joint movement separately from dry-run logs. Record failures without substituting fabricated evidence.

## Validation and Acceptance

Planner tests must cover transforms, pitch/height, order, invalid/nonfinite inputs and workspace limits. Executor tests cover dry-run command absence, stale/missing feedback, timeout and overtravel stop behavior. Mock evidence must distinguish plan rehearsal from actual trajectory execution and force-mode emulation. Parent independently verifies all results.

## Idempotence and Recovery

Only additive changes under ros2 and this plan. Keep Max fixes local, record patches; no pushes there. Stop only processes launched for this task. Preserve failing tests and diagnostics. If dependencies cannot be installed, report blocked checks explicitly.

## Outcomes & Retrospective

Implementation pending.
