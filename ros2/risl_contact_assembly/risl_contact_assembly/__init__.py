"""Known-pose brick assembly planning for a robot arm in ``base`` coordinates.

Exports the shared planner contract:

- ``load_config(path)`` returns a validated assembly config mapping.
- ``load_structure(path)`` returns a simulator stud-grid structure mapping.
- ``plan_structure(structure, config)`` returns ten steps per brick in build
  order. Poses are TCP in ``base``, SI meters and degrees; ``base`` is not
  ``base_link``.
"""

from risl_contact_assembly.planner import (
    AssemblyConfig,
    PlanAction,
    PlanStep,
    Structure,
    load_config,
    load_structure,
    plan_structure,
)

__all__ = [
    "AssemblyConfig",
    "PlanAction",
    "PlanStep",
    "Structure",
    "load_config",
    "load_structure",
    "plan_structure",
]
