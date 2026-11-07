# RISE digital twin workspace

This is Kaleb's starting workspace for independent experiments with the RISE lab
robot and workstation. The first research direction is two arms manipulating a
shared object, with emphasis on contact, friction, and custom physics.

## Where to work

- `experiments/`: experiment plans and small experiment-specific scripts.
- `notes/`: dated notes, decisions, and links to evidence.
- `scenes/`: saved copies of research scenes and asset inventories.
- `runs/`: an index of experiment artifacts. Generated simulation data remains
  under the repository's ignored `outputs/rise/` directory unless intentionally
  archived elsewhere.

The existing upstream examples, lab assets, and previous research notes are
preserved. This folder begins with a scene audit and a blank experiment template.
The live simulator scene has **not** been exported into this folder yet.

## Start the lab simulator

From the repository root:

```bash
./scripts/run_rise_lab.sh
```

In the **UR5e Digital Twin** panel, select **Quick Start + Workstation**. The
initial RISE lab scene contains one UR5e, RG2 gripper, camera, and Vention bench.
Its robot chain is configured for position mirroring with gravity disabled, and
the bench is visual-only; the ground-plane collider supplies contact. Those
choices must be assessed before force or friction studies. This is a useful
starting scene, not a validated model of the physical cell.

The lab MCP gateways are `rise-isaac` and `rise-kit`. They use local loopback
connections and require the simulator to be running. A new Codex chat or client
reload may be needed after changing MCP configuration. Ask Codex to check the
`rise-isaac` status before modifying the scene. When running multiple simulator
instances, verify the process and endpoint before issuing commands.

## Begin an experiment

Copy [experiments/EXPERIMENT_TEMPLATE.md](experiments/EXPERIMENT_TEMPLATE.md),
fill in the question, variables, success criteria, and expected output before
running trials, then add dated observations under `notes/`. The existing
[research protocol](../PROTOCOL.md) provides more detail on recording units,
calibration, and repeated trials.

The existing [two-UR5e scene experiment](../../experiments/rise_dual_ur5e.py)
uses generic NVIDIA robots and a shared object as an integration check. It does
not yet attach grippers or perform cooperative manipulation. Its configuration
is [here](../configs/dual_ur5e.json); preserve that baseline when building your
own version. Lab-specific asset provenance and C++ integration notes are in the
broader [research overview](../README.md).
