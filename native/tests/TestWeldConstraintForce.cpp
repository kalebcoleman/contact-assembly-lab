import std;
import bricksim.physx.weld_constraint;
import bricksim.vendor;

#include <cassert>
#include <foundation/PxPhysicsVersion.h>

using namespace bricksim;

namespace {

// Raw torque PhysX reports for a weld between a heavy body A (centre of mass at
// the origin) and a light body B whose centre of mass is the weld point P at
// rA = (0.03, 0.03, 0) m. B is pushed with 2.4 N along -z, so the true torque
// about P is zero. Returns {reported torque about P, rA x F0} where F0 is the
// reported force on A.
std::pair<physx::PxVec3, physx::PxVec3>
reported_weld_torque(physx::PxSolverType::Enum solver_type) {
	physx::PxDefaultAllocator allocator;
	physx::PxDefaultErrorCallback error_callback;
	physx::PxFoundation *foundation =
	    PxCreateFoundation(PX_PHYSICS_VERSION, allocator, error_callback);
	physx::PxPhysics *physics =
	    PxCreatePhysics(PX_PHYSICS_VERSION, *foundation,
	                    physx::PxTolerancesScale{}, true, nullptr);
	physx::PxSceneDesc desc(physics->getTolerancesScale());
	desc.gravity = physx::PxVec3(0.0f);
	physx::PxDefaultCpuDispatcher *dispatcher =
	    physx::PxDefaultCpuDispatcherCreate(1);
	desc.cpuDispatcher = dispatcher;
	desc.filterShader = physx::PxDefaultSimulationFilterShader;
	desc.solverType = solver_type;
	physx::PxScene *scene = physics->createScene(desc);

	const physx::PxVec3 rA(0.03f, 0.03f, 0.0f);
	physx::PxRigidDynamic *a =
	    physics->createRigidDynamic(physx::PxTransform(physx::PxVec3(0.0f)));
	physx::PxRigidDynamic *b =
	    physics->createRigidDynamic(physx::PxTransform(rA));
	a->setMass(1000.0f);
	a->setMassSpaceInertiaTensor(physx::PxVec3(100.0f));
	b->setMass(0.01f);
	b->setMassSpaceInertiaTensor(physx::PxVec3(1e-6f));
	scene->addActor(*a);
	scene->addActor(*b);
	physx::PxConstraint *weld = createWeldConstraint(
	    *physics, a, b,
	    WeldConstraintData{.parentLocal = physx::PxTransform(rA),
	                       .childLocal =
	                           physx::PxTransform(physx::PxIdentity)});

	for (int step = 0; step < 20; ++step) {
		b->addForce(physx::PxVec3(0.0f, 0.0f, -2.4f));
		scene->simulate(1.0f / 120.0f);
		scene->fetchResults(true);
	}
	physx::PxVec3 force, torque;
	weld->getForce(force, torque);

	weld->release();
	scene->release();
	dispatcher->release();
	physics->release();
	foundation->release();
	return {torque, rA.cross(force)};
}

// PhysicsLegoGraph adds 2 rA x F to the weld torque on CPU TGS scenes. This pins
// the PhysX behaviour that correction relies on: if a PhysX update fixes the
// TGS writeback, this test fails and the correction must be removed.
void test_cpu_tgs_reports_weld_torque_short_by_two_ra_cross_f() {
	auto [pgs_torque, pgs_rxf] =
	    reported_weld_torque(physx::PxSolverType::ePGS);
	auto [tgs_torque, tgs_rxf] =
	    reported_weld_torque(physx::PxSolverType::eTGS);
	std::println("PGS torque about P {} {} {}, rA x F {} {} {}", pgs_torque.x,
	             pgs_torque.y, pgs_torque.z, pgs_rxf.x, pgs_rxf.y, pgs_rxf.z);
	std::println("TGS torque about P {} {} {}, rA x F {} {} {}", tgs_torque.x,
	             tgs_torque.y, tgs_torque.z, tgs_rxf.x, tgs_rxf.y, tgs_rxf.z);
	assert(pgs_rxf.magnitude() > 0.05f);
	assert(pgs_torque.magnitude() < 0.05f * pgs_rxf.magnitude());
	assert((tgs_torque + tgs_rxf * 2.0f).magnitude() <
	       0.05f * tgs_rxf.magnitude());
}

} // namespace

int main() {
	test_cpu_tgs_reports_weld_torque_short_by_two_ra_cross_f();
	return 0;
}
