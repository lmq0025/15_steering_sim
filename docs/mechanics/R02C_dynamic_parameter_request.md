# R02-C mechanical dynamics parameter request

This request separates data needed by the reduced inertia model from later
loss and external-load refinements. The kinematic coordinates and topology
remain frozen by R02-B.1.

## A. Required for engineering dynamics

Complete every required row in
`configs/mechanics/mechanical_mass_properties_template.csv`:

- `mass_kg`: component mass;
- `com_local_x_m`, `com_local_y_m`: planar COM in the component body frame;
- `izz_kg_m2`: inertia about +Z through that COM;
- `source`, `confidence`, `notes`: traceability metadata.

Rows cover every recognized swing arm, steering wheel/knuckle equivalent body,
side tie rod, cross tie rod and axle-1/2 longitudinal tie rod. For swing and
wheel/knuckle bodies, the local origin is the fixed revolute pivot and the
local axes match the CUSTOMER q=0 frame. For a tie rod, the natural origin is
its q=0 endpoint midpoint and local +X lies from endpoint A to endpoint B.

If a component is deliberately excluded from inertia, set
`include_in_inertia=false` and document the reviewed justification in `notes`.
Do not leave it blank or rely on an implicit massless assumption.

## B. Important for the second dynamics stage

- revolute-joint, ball-joint, bushing and steering-gear friction;
- viscous damping and speed dependence;
- transmission and joint efficiency/resistance conventions;
- backlash/dead-zone geometry and parameters;
- true mechanical limit locations and contact stiffness/damping.

These are not populated with assumed engineering values in R02-C1. The
`MechanicalLossModel` interface returns zero until reviewed parameters exist.

## C. Later external-load inputs

- axle loads and load distribution;
- tire steering torque or an identifiable tire lateral-force model;
- road surface, vehicle speed, tire construction, pressure and temperature;
- test/AMESim time histories with force, angle, displacement and speed channel
  definitions for validation.

These inputs are not prerequisites for verifying the R02-C1 mass-matrix core,
but they are required before predicting customer-vehicle motion or loads.

## Synthetic boundary

`data/example/mechanical_mass_properties_SYNTHETIC_TEST_ONLY.csv` exists solely
for numerical tests and the debug example. Every row is `source=ASSUMED` and
has the note `synthetic numerical verification only; not customer engineering
data`. The formal dynamics constructor rejects this set unless the caller
explicitly enables the test-only guard.
