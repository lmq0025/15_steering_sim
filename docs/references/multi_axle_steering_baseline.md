# Multi-axle steering baseline references

## Scope boundary

Public sources in this note justify steering-mode architecture, linkage
kinematics, plausibility checks, and actuator-position feedback only. No
hardpoint, cylinder stroke, steering ratio, mass, limit, or calibration
coefficient from another vehicle is used as CUSTOMER data. R02-E reads all
twelve steering-axis centers from the frozen CUSTOMER ReferenceGeometry.

## XCMG XCA500L8 public operation manual

A publicly accessible copy of the XCA500L8_1 All Terrain Crane Operation
Manual (first edition, March 2024), chassis-operation section 5, describes:

- low-speed road travel, V <= 30 km/h: Axles 1/2/3 steer in the Axle1
  direction; Axles 4/5/6 steer opposite to Axle1;
- tight-turn mode, V <= 8 km/h: Axles 1/2/3 steer in one phase and Axles
  4/5/6 in the counter phase;
- crab mode, V <= 8 km/h: Axles 1 through 6 steer in the same direction;
- middle-speed road travel, 30 < V <= 60 km/h: Axles 1/2 and 5/6 steer,
  Axles 5/6 counter-phase to 1/2, while Axles 3/4 are locked at center;
- high-speed road travel, V > 60 km/h: only Axles 1/2 steer and Axles 3
  through 6 are locked at center.

Public manual copy:
https://www.scribd.com/document/978421371/1-Xca500l8-1%E5%85%A8%E5%9C%B0%E9%9D%A2%E8%B5%B7%E9%87%8D%E6%9C%BA%E6%93%8D%E4%BD%9C%E6%89%8B%E5%86%8C-%E8%8B%B1%E6%96%87

Official XCMG product page confirming the model identity:
https://www.xcmg.com/product/pro-detail.jsp?id=138446

R02-E uses only the phase pattern as PUBLIC_6AXLE_BASELINE architecture.
Placing x_ICR between Axles 3 and 4 is this project's generalized-Ackermann
baseline interpretation; it is not a copied XCMG parameter and is not a claim
about the CUSTOMER vehicle.

## CUSTOMER_HINT_BASELINE

The user recalls that the CUSTOMER vehicle may reverse phase between Axles 2
and 3. R02-E therefore includes an explicitly separate, low-confidence preset:
Axles 1/2 in the Axle1 phase and Axles 3/4/5/6 in the opposite phase, obtained
by placing x_ICR between Axles 2 and 3.

Source is CUSTOMER_HINT_UNCONFIRMED. It requires formal CUSTOMER confirmation
or calibration and must not be described as a verified customer requirement.

## Topaç et al. (2017)

M. M. Topaç, A. Kaplan, B. Kuleli, and U. Deryal, “Design of a Multi-Axle
Steering Mechanism for a Special Purpose Vehicle: Kinematic Design and
Optimization,” IATS'17, 2017, pp. 502–509.

University record:
https://avesis.deu.edu.tr/yayin/448ff7ab-8711-4e40-a0f6-59e56e278fe3/design-of-a-multi-axle-steering-mechanism-for-a-special-purpose-vehicle-kinematic-design-and-optimization

Public full text:
https://www.researchgate.net/publication/321360642_Design_of_a_multi-axle_steering_mechanism_for_a_special_purpose_vehicle_kinematic_design_and_optimization

The paper supports rigid-link/hardpoint kinematics and Ackermann error as a
separate evaluation quantity. Its reported approximately ±0.5 deg result
belongs only to its optimized example. It is not an acceptance threshold or
accuracy claim for this project.

## SAE 952121

L. Yucheng, Z. Wei, Z. Guifan, and W. Cong, “Kinematical Models and Emulation
of Multi-Axle Steering of Off-Highway Vehicles with Multi-Axle,” SAE Technical
Paper 952121, 1995, DOI 10.4271/952121.

Official record:
https://saemobilus.sae.org/papers/kinematical-models-emulation-multi-axle-steering-off-highway-vehicles-multi-axle-952121

This supports explicit linkage kinematics, wheel-location reasoning, and
multi-axle coordination as model concepts. It supplies no project parameters.

## Hydraulic-cylinder position feedback

CN115465359B describes cylinder displacement sensing followed by linkage-based
conversion, while Bosch's public rear-axle-steering overview describes a
cylinder unit with an integrated linear position sensor:

- https://patents.google.com/patent/CN115465359B/en
- https://www.bosch-mobility.com/en/solutions/steering/rear-axle-steering/

These sources support the R02-D external chain actuator position -> mechanical
mapping -> wheel angle. Only frozen project geometry and traceable baseline
sensor-conversion parameters are used.
