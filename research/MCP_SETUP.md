# Lab MCP installation and operation

See the [post-clone change inventory](../../POST_CLONE_CHANGES.md) for current
collision and tracking changes and validation limits. The original setup record
below predates those tests. In particular, the lab arm has seven enabled
colliders inside USD instances; ordinary traversal missed them. The workstation
loader now adds CAD-part box proxies and restarts physics when required.

Installed on 2026-10-26 (America/Phoenix). Repository commits and asset locations
are listed in README.md. No physical robot connection has been established.

## Launch the lab scene

Close the simulator normally before relaunching; preserve any scene edits first.
From the repository root run:

```bash
./scripts/run_rise_lab.sh
```

The **UR5e Digital Twin** panel should be present. Select **Quick Start +
Workstation** to load the supplied UR5e, RG2 gripper, workspace camera, and Vention
bench. The launcher configures the bundled ROS 2 Jazzy libraries and localhost
ROS discovery. It does not launch a physical robot driver. The lab extension
includes driver tools, but those were not invoked during setup.

The lab Quick Start is a single-arm, position-mirrored twin. Its source disables
gravity on the robot chain; it is not the same as a physically validated,
force-controlled cooperative manipulation model. It also changes collision
cooking settings. Record those changes when comparing physics experiments.

## Local Codex desktop

Two globally configured stdio MCP gateways are installed:

| Name | Executable | Bridge endpoint |
| --- | --- | --- |
| `rise-kit` | `../isaac-sim-mcp/.venv/bin/kit-mcp` | `127.0.0.1:9009` |
| `rise-isaac` | `../isaac-sim-mcp/.venv/bin/isaac-mcp` | `localhost:8766` |

The shared bridge provides general Kit inspection and Python execution. The lab
extension owns its separate bridge and exposes namespaced tools such as
`ur5e__quick_start_with_workstation`. This is the current lab source's two-bridge
architecture, despite the generic repository's preferred single-bridge design.

Restart/reload the local Codex client or open a fresh local chat to load newly
registered MCP servers. The current chat's original tool catalog is not proof of
hot activation. Start Isaac Sim before discovery; if the gateway started first,
call its `refresh_tools` after the simulator starts. With multiple simulator
instances, verify the endpoint's PID; a second general bridge may use an
ephemeral port rather than 9009.

Checks:

```bash
codex mcp get rise-kit
codex mcp get rise-isaac
../isaac-sim-mcp/.venv/bin/python -m kit_mcp.client status --port 9009
../isaac-sim-mcp/.venv/bin/python -m kit_mcp.client status --port 8766
```

Both actual MCP stdio handshakes and tool discovery passed: 8 generic tools and
30 lab-endpoint tools, including builtins and gateway refresh. Workstation
loading and the full simulated Quick Start returned success after compatibility
fixes. The simulator startup test used its bundled ROS libraries. No real robot
driver tool was called, and motion tracking/contact performance remains untested.

## ChatGPT tunnel: removed

The optional ChatGPT tunnel route was removed on 2026-10-28 at the user's
request. The tunnel client, local profile and `scripts/start_chatgpt_tunnel.sh`
were moved to the desktop Trash. The local `rise-kit`/`rise-isaac` stdio
gateways are the only supported MCP transport. The Platform-side tunnel
(`tunnel_6ae0430847888191a155fc8c3f92f1b3`) and its runtime key still exist in
the user's OpenAI organization until revoked there.

## Local compatibility patches

The lab repository remains on its inspected upstream commit plus explicit local
changes in `exts/ur5e-dt/ur5e_dt/extension.py` and `isaac_mcp/server.py`:

- Register tools with the newer owner-scoped bridge API under `ur5e`.
- Normalize that prefix before existing checkpoint gates and output-dir policy.
- Initialize a Python physics context even if a USD PhysicsScene already exists.
- Delegate `isatty()` through the log redirector so uvicorn logging can start.

Preserve/review these patches before pulling updates. They have not been pushed
or presented as upstream fixes. Gate-policy behavior must remain intact; do not
remove the namespace normalization when updating registration.

## Settings and rollback

The installer added both extension directories and autoload entries to
`~/.local/share/ov/data/Kit/Isaac-Sim Full/5.1/user.config.json`, backing up the
previous file as `user.config.json.bak.1793080747`. Apply persistent extension
registration only while Isaac Sim is closed, since graceful shutdown rewrites
these settings. Remove Codex entries with `codex mcp remove rise-kit` and
`codex mcp remove rise-isaac` if requested. The generic installer's `--remove`
can undo its registration using the same folder/extension arguments; it should
not run automatically as part of cleanup.
