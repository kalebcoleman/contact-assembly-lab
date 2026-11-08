# Evaluation practices worth carrying to Jenga

This repository's UR5e brick assembly is a demo and a contact-physics testbed.
The main research direction is Jenga with MPC and RL, in its own projects.
This note lists practices that the brick sweeps of 2026-11-08 showed to matter,
so the Jenga work can adopt the ones that fit. It is not a proposal to share
code, schemas or a common architecture: each project keeps its own recorder,
formats and tools. Everything below comes from simulation runs; no hardware
was involved.

The evidence is in
[experiments/ur5e_structures/FAILURES.md](../experiments/ur5e_structures/FAILURES.md)
and the generated sweep summaries in
[experiments/ur5e_structures/sweeps/](../experiments/ur5e_structures/sweeps/README.md).

## 1. Record the effective settings in the run itself

**Seen here.** Each recording stores breakage and assembly settings at every
step. The gripper-contact mode, press depth and timing, however, were only
environment variables. For the existing runs they had to be recovered from
the sweep definitions.

**For Jenga.** Write the settings actually used into the episode header, after
defaults are resolved:
- controller and MPC parameters;
- the policy checkpoint;
- the seed;
- physics and solver settings;
- the simulator version;
- the git commit and whether the tree was dirty.

A run should explain itself without the command line that launched it.

## 2. Keep termination reasons apart

**Seen here.** "Failed" covered very different things:
- a joint overloaded by the physics model;
- a controller that refused to act (no gripper clearance);
- a brick lost from the grasp;
- a safety monitor that stopped the run (fail-on-contact).

The controller's stop reason is not the physical mechanism either.
`cantilever_tip2` stopped as "did not seat" because the press had already
broken the structure's base joint.

**For Jenga.** Use an enumerated termination reason per episode, never a single
success flag. The categories to keep apart:
- task success;
- physical failure (tower fell, block dropped);
- safety or monitor abort;
- infeasible action;
- time limit;
- infrastructure error.

For RL, aborts and time limits are truncations, not policy failures; count
them separately in success rates.

## 3. Make monitors switchable between logging and stopping

**Seen here.** The gripper-contact monitor stops a run by default (`fail`). The
sweeps ran it in `log` mode so that every structure ran to its physical
outcome while still counting contacts.

**For Jenga.** Run contact and safety monitors in log mode when collecting
evaluation data, and record the mode with the run. Switch them to stopping
mode only where the policy needs it, and report both counts.

## 4. Log simulator health next to physical outcomes

**Seen here.**
- 23 of 31 runs logged breakage-solver non-convergence or high slack.
- 12 of the 16 lasting joint breaks came right after such warnings.
- A utilization of 1e6 is a sentinel for exhausted capacity, not a load.

Treating every break as physics would overstate what the model predicts.

**For Jenga.** Count solver health per episode and log it per step around events:
- solver warnings and iteration limits;
- penetration depth;
- velocity spikes;
- contact-count jumps.

Flag episodes where a physical event follows numerical trouble, and report
results with and without them. Never average sentinel values.

## 5. Sample the quantity that decides an event, at the event

**Seen here.** BrickSim breaks a joint inside the physics step, and the
utilization CSV is read after it. The breaking value is therefore never
recorded, and a "sudden" break cannot be explained from the telemetry.

**For Jenga.** Log the decision quantities on the step where the event happens:
- per-block contact normal and friction forces;
- friction utilization |F_t| / (μ F_n);
- block displacement and tower tilt.

Log them for the step a block slips, falls or the tower collapses, not only the
step before. Where an event happens inside the simulator, have it report the
deciding value with the event.

## 6. Keep events in structured records, not text logs

**Seen here.** Kit's console log lost some or all of its BrickSim events in 8 of
31 runs, and every one of them in both human runs: it is flushed
asynchronously and the run exits at once. The step-by-step
recording, which samples every brick's planned joint, is what showed that the
dog's last joint broke and re-formed 16 ms later.

**For Jenga.** Write events into the episode record with the step number:
- block removed;
- block placed;
- block fell;
- collapse detected.

Flush and close the record before the process exits. Use text logs for
diagnosis only.

## 7. Count near-failures, not only outcomes

**Seen here.** 59 of 75 joint breaks were re-formed within 1 s, and every
completed run except the one-brick build had some. A joint that breaks transiently on every release
(tree, tower_2x2, column_10) is the clearest early sign of a lasting break.
The controller never sees these breaks.

**For Jenga.** Record recoverable events as well as the final state, since they
measure margin and success alone hides it:
- a block that slipped and resettled;
- tilt beyond a threshold that recovered;
- contact forces near the friction cone.

## 8. Vary one factor against a control

**Seen here.**
- `cantilever_tip2` and `cantilever_root2` differ only in where the same load
  sits. The tip load fails and the root load completes.
- The press-force sweep (1, 2, 3, 5 N) moves the column from completing to
  failing between 2.2 N and 3.9 N peak force.

These pairs say more than any single build.

**For Jenga.** For each hypothesis, run a matched pair or a one-factor sweep:
- removal speed;
- push force;
- block position;
- friction coefficient.

Keep everything else identical.

## 9. Check determinism, then measure variance on purpose

**Seen here.** Paired runs in the two sweeps match exactly: outcome, contacts,
solver warnings, joint breaks and the simulator step of every logged joint
event. One run per
setting is therefore reproducible. It still says nothing about sensitivity to
initial conditions.

**For Jenga.** Rerun a few episodes to confirm determinism for a fixed seed.
Then evaluate across seeds and perturbations: initial block poses, friction,
mass. Report the number of episodes and the spread, not single runs.

## 10. Keep evidence linked and claims scoped

**Seen here.** Each run connects:
- a sweep definition (config, overrides, controller commit);
- a run id;
- a recording;
- a utilization CSV;
- a video rendered in simulated time.

The summaries are generated from these and committed; the raw data stays
local. Every claim is marked as simulation, with poses from ground truth.

**For Jenga.** Link every reported number to the episodes behind it, and every
video to its episode. Render videos at a fixed rate of simulated time. State
which observations the controller used (ground truth or perceived), and keep
simulation and hardware results in separate tables.

## Not recommended to share

The brick controller, its recording schema and the dashboard are specific to
this testbed. Jenga's MPC and RL loops have different time scales, data
volumes (vectorized environments) and event types. Agreeing on conventions is
enough: the termination categories, provenance fields and health counters
above.
