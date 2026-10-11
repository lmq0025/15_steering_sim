# L1-R1 equation and code audit

## Result

The original L1 channel binding was not supported by IR V3. It was minimally corrected without changing the four actuator channels or 16-state vector: pump01/pump01_1 share the front supply feeding dirvalve_6 and actuator002; pump01_2/pump01_3 share the rear supply feeding redundant valve pairs 1/2, 8/9 and 11/12 for actuator001, actuator001_1 and actuator001_2. Supply pressure is one algebraic effort per group. Each parallel PU001 retains its own relief branch.

PU001 uses `Q=D*omega*eta_v-C_leak*dp` and `T=dp*D`. SC_1 uses a saturated signed four-way orifice law. Positive command is P-A/B-T; negative command is P-B/A-T. Cylinder equations preserve power signs: `F=A_A p_A-A_B p_B`, `dpA/dt=beta/V_A(Q_A-A_A v-Ctp dp)`, `dpB/dt=beta/V_B(Q_B+A_B v+Ctp dp)`. The supply algebraic balance is sum(pump flows)=sum(valve supply flows)+sum(relief flows. Tank is exactly 0 Pa gauge. There is no pressure hard clamp.

`model.evaluate()` does not use time internally, but `simulation.py` evaluates `inputs(t)`, `inputs(t+h/2)` and `inputs(t+h)` at every RK4 stage. Sine inputs are therefore time-varying and are not frozen.

The three spring-return cylinders are omitted only from the four primary controlled-output state vector. Their hydraulic branches remain a known topology reduction boundary; this is acceptable for the current primary-output L1 model but must be revisited before a system-level fluid inventory claim.
