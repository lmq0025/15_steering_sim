# Multi-axle steering baseline references

## Scope boundary

These public sources justify modeling methods and plausibility checks only.
No hardpoint, cylinder stroke, ratio, mass, limit or calibration coefficient
from another vehicle is used as CUSTOMER data for this project. The frozen
CUSTOMER geometry remains the sole geometry used by the R02-B closed chain.

## 1. Topaç et al. (2017)

M. M. Topaç, A. Kaplan, B. Kuleli, and U. Deryal, “Design of a Multi-Axle
Steering Mechanism for a Special Purpose Vehicle: Kinematic Design and
Optimization,” IATS’17, 2017, pp. 502–509. The university publication record
confirms the title, authors and conference; the publicly available full text
describes rigid-link/hardpoint multibody kinematics, swing-arm linkage
optimization, and Ackermann error as a separate evaluation quantity.
[University record](https://avesis.deu.edu.tr/yayin/448ff7ab-8711-4e40-a0f6-59e56e278fe3/design-of-a-multi-axle-steering-mechanism-for-a-special-purpose-vehicle-kinematic-design-and-optimization),
[public full text](https://www.researchgate.net/publication/321360642_Design_of_a_multi-axle_steering_mechanism_for_a_special_purpose_vehicle_kinematic_design_and_optimization).

The paper reports that its own optimized example can satisfy approximately
±0.5 deg Ackermann error. This is a result for that vehicle and optimization
case, not an acceptance threshold or accuracy claim for the present six-axle
CUSTOMER mechanism. R02-D therefore computes Ackermann error only as a
reference plausibility metric and never overwrites closed-chain wheel angles.

## 2. SAE 952121

L. Yucheng, Z. Wei, Z. Guifan, and W. Cong, “Kinematical Models and Emulation
of Multi-Axle Steering of Off-Highway Vehicles with Multi-Axle,” SAE Technical
Paper 952121, 1995, DOI 10.4271/952121. Its official abstract covers kinematic
models of multiple steering linkages, linkage relationships, minimum turning
radius, wheel alignment and linkage optimization for a multi-axle off-highway
vehicle. [SAE Mobilus record](https://saemobilus.sae.org/papers/kinematical-models-emulation-multi-axle-steering-off-highway-vehicles-multi-axle-952121).

This supports explicit linkage kinematics and wheel-location reasoning. It
does not supply parameters for the present vehicle.

## 3. Hydraulic-cylinder position feedback

Public electro-hydraulic multi-axle steering disclosures show the engineering
pattern of an integrated cylinder displacement sensor, conversion through the
mechanical linkage relation, and rear-axle wheel-angle feedback. For example,
CN115465359B describes a magnetostrictive displacement sensor in a steering
cylinder and conversion of extension/retraction through the steering linkage;
Bosch’s commercial rear-axle steering overview identifies a cylinder unit with
an integrated linear sensor for position feedback.
[CN115465359B](https://patents.google.com/patent/CN115465359B/en),
[Bosch rear-axle steering](https://www.bosch-mobility.com/en/solutions/steering/rear-axle-steering/).

These sources support the external chain “actuator position → mechanical
mapping → wheel angle.” R02-D still uses only this project’s frozen actuator
geometry and explicitly traceable sensor conversion parameters.
