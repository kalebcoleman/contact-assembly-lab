# Experiment protocol

Copy this structure into the notebook before each new experiment. Record all
units explicitly: meters, kilograms, seconds, newtons, newton-meters, radians;
quaternions wxyz unless a named interface requires a conversion. Record frames
such as world, each robot base, flange, tool center point, camera, and object.

## Identity and question

Experiment ID, date/time with timezone, researcher, research question, hypothesis,
and relation to the current supervisor-agreed milestone.

## Model and provenance

Source commit and patch/diff; lockfile hash; simulator, physics, and compiler
versions; asset versions and dependency hashes; hardware; CPU/GPU physics;
timestep and solver settings; collision approximation and contact/rest offsets;
material coefficients and friction combine mode; masses, inertias, and joint
drive parameters; controller frequency and limits; sensing and latency.

State which quantities are manufacturer-specified, lab-measured, fitted, or
assumed. Save calibration data separately from evaluation data. A model fitted
to a trial cannot claim that same trial as independent validation.

## Trial design

Specify independent variables, controlled variables, random seeds if used,
initial states and reset procedure, trial count, exclusions, and stop conditions.
Start with a fixed scene before randomizing uncertainty. Repeat trials and
report variability; select the trial count before interpreting outcomes.

## Measurements and acceptance

For the two-arm task, candidates include object position/orientation tracking
error, relative end-effector error, slip, grasp retention, contact or wrist
forces when available, peak joint load, completion time, and success rate.
Distinguish commanded from measured values and simulator contact reports from
physical sensors. Agree numeric thresholds with the supervisor before testing.

For friction validation, measure motion and load rather than judging a rendered
image. Check that conclusions survive timestep/solver refinement. A Coulomb
sliding calculation can provide a sanity check under its stated assumptions;
it is not a substitute for measuring the lab materials.

## Results and interpretation

Link config, manifest, trace, scene/dependencies, console log, video if used,
analysis code, and summary metrics. Record failures and missing data. Separate
what the data shows from a proposed explanation. State limits of generalization.

## Next action and review

Record the smallest next experiment that distinguishes competing explanations,
supervisor feedback when received, and any change to the protocol. Do not invent
supervisor approval or present a proposed result as completed.
