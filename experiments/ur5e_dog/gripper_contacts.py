"""Report every contact between the RG2 gripper and a brick it is not holding."""

from experiments.ur5e_lego.recording import RunRecorder
from omni.physx import get_physx_simulation_interface
from omni.physx.bindings._physx import ContactEventType
from pxr import PhysicsSchemaTools, PhysxSchema, Usd, UsdPhysics


class GripperContactMonitor:
    """Collect gripper contacts with bricks other than the held one.

    Contact reports are enabled on every RG2 rigid body. A contact counts when
    one actor is under the gripper and the other is a brick part other than the
    brick of the current step (the baseplate counts too); during the retreat the
    just-released brick counts as well, since the fingers must have let go of it.
    The step and phase come from `recorder`, set once the run recorder exists. Each
    (part, brick, phase) is kept once. Create the monitor before the world reset:
    changing physics schemas on a playing scene invalidates the articulation views.
    """

    def __init__(
        self,
        stage: Usd.Stage,
        gripper_root: str,
        parts_root: str,
        brick_paths: list[str],
    ) -> None:
        """Enable contact reports on the gripper and subscribe to them.

        Args:
            stage: The simulation stage.
            gripper_root: Path of the RG2 articulation root prim.
            parts_root: Path under which brick parts (and the baseplate) live.
            brick_paths: Brick part paths in build order.
        """
        for prim in Usd.PrimRange(stage.GetPrimAtPath(gripper_root)):
            if prim.HasAPI(UsdPhysics.RigidBodyAPI):
                PhysxSchema.PhysxContactReportAPI.Apply(prim).CreateThresholdAttr(0.0)
        self.gripper_root = gripper_root + "/"
        self.parts_root = parts_root + "/"
        # Its `brick_index` (1-based, 0 before the first brick) and `phase`
        # describe the current step.
        self.recorder: RunRecorder | None = None
        self.brick_paths = brick_paths
        self.contacts: list[tuple[str, int, str]] = []
        # Contact impulse (N*s) above which a contact counts as a touch: about 1 mN
        # over a 1/120 s step. Smaller numerical grazes are ignored.
        self.min_impulse = 1e-5
        self.subscription = (
            get_physx_simulation_interface().subscribe_contact_report_events(
                self.on_contacts
            )
        )

    def on_contacts(self, headers: object, data: object) -> None:
        """Record new gripper-to-brick contacts from one simulation step.

        Args:
            headers: omni.physx ContactEventHeaderVector of this step.
            data: omni.physx ContactDataVector of this step.
        """
        if self.recorder is None:
            return
        index = self.recorder.brick_index
        held = self.brick_paths[index - 1] if index else ""
        if self.recorder.phase == "retreat":
            held = ""
        for header in headers:
            if header.type == ContactEventType.CONTACT_LOST:
                continue
            paths = (
                str(PhysicsSchemaTools.intToSdfPath(header.actor0)),
                str(PhysicsSchemaTools.intToSdfPath(header.actor1)),
            )
            for gripper_path, other in (paths, paths[::-1]):
                if not (
                    gripper_path.startswith(self.gripper_root)
                    and other.startswith(self.parts_root)
                    and other != held
                ):
                    continue
                # PhysX also reports shapes within the contact offset that do not
                # touch; count only points that exchanged an impulse.
                points = [
                    data[header.contact_data_offset + i]
                    for i in range(header.num_contact_data)
                ]
                pushing = [
                    point
                    for point in points
                    if sum(c * c for c in point.impulse) ** 0.5 > self.min_impulse
                ]
                if not pushing:
                    continue
                key = (other, index, self.recorder.phase)
                if key in self.contacts:
                    continue
                self.contacts.append(key)
                strongest = max(
                    pushing, key=lambda point: sum(c * c for c in point.impulse)
                )
                impulse = sum(c * c for c in strongest.impulse) ** 0.5
                print(
                    f"UR5e baseplate: gripper touched {other} during {key[2]} of "
                    f"brick {index} ({gripper_path.rsplit('/', 1)[-1]} at "
                    "({:.4f}, {:.4f}, {:.4f}) m, ".format(*strongest.position)
                    + f"impulse {impulse * 1000:.3f} mN*s)",
                    flush=True,
                )
