# Constitutive Equations

Truth labels: **LEVEL A** is direct `.c/.spe` evidence; **LEVEL B** is model metadata/topology; **LEVEL C** is an engineering surrogate. Diagnostic activity/energy integrals are not physical ODE states.

## CONS00 — constant signal

- Truth: LEVEL A — SOURCE VERIFIED
- Actual instances: constant;constant_1;constant_10;constant_11;constant_12;constant_13;constant_14;constant_2;constant_3;constant_4;constant_5;constant_6;constant_7;constant_8;constant_9
- Inputs/outputs: out [null; ame_variable_io_output]
- Parameters: k [null]
- Physical states: STATELESS ALGEBRAIC ELEMENT
- Exact Amesim relation: $y=k$.
- Engineering simplified relation (LEVEL C): $y=k$.
- Bond Graph: `signal block`
- Python note/status: `SIGNAL_ONLY`. Amesim labels linked constants as state variables, but they are fixed parameters, not ODE states.
- Evidence directory: `hydraulic_audit/submodels/CONS00/`

## CV010 — static check valve with cracking pressure and hysteresis

- Truth: LEVEL A — SOURCE VERIFIED
- Actual instances: presscontrol02;presscontrol02_1;presscontrol02_4;presscontrol02_5;presscontrol02_8;presscontrol02_9
- Inputs/outputs: q1 [L/min; ame_variable_io_output], p1 [bar; ame_variable_io_input], q2 [L/min; ame_variable_io_output], p2 [bar; ame_variable_io_input]
- Parameters: pcrack [bar], grad [L/min/bar], hyst [bar], indexf [-]
- Physical states: STATELESS ALGEBRAIC ELEMENT
- Exact Amesim relation: With source hysteresis variable $\Delta p_h$, $q=0$ when closed and $q=G\Delta p_h$ when open, followed by polysmooth_ to prevent reverse flow.
- Engineering simplified relation (LEVEL C): $q=G\max(p_2-p_1-p_{crack},0)$, optionally with a two-threshold hysteresis state machine.
- Bond Graph: `R`
- Python note/status: `READY_APPROX`. 
- Evidence directory: `hydraulic_audit/submodels/CV010/`

## CV012 — spring check valve with optional spool dynamics and orifice law

- Truth: LEVEL A — SOURCE VERIFIED
- Actual instances: springcheckvalve
- Inputs/outputs: q1 [L/min; ame_variable_io_output], p1 [bar; ame_variable_io_input], q2 [L/min; ame_variable_io_output], p2 [bar; ame_variable_io_input]
- Parameters: pcrack [bar], grad [L/min/bar], qchar [L/min], dpchar [bar], lcrit [null], rhochar [kg/m**3], nuchar [cSt], hyst [bar], tau [s], wn [Hz], zeta [null], indexf [-], userfp [-], spooldyn [-]
- Physical states: STATELESS ALGEBRAIC ELEMENT
- Exact Amesim relation: $u=(p_2-p_1-p_{crack})/\Delta p_m$; opening $x=valvedyn(u)$; $A=A_{max}x$; $q=orif3f(p_2,p_1,A,2\sqrt{A/\pi},\ldots)$. Current spooldyn=1 is static.
- Engineering simplified relation (LEVEL C): Static check-orifice: $x=\operatorname{clip}((\Delta p-p_c)/\Delta p_m,0,1)$ and square-root orifice flow.
- Bond Graph: `composite subgraph`
- Python note/status: `READY_APPROX`. 
- Evidence directory: `hydraulic_audit/submodels/CV012/`

## DIRECT — Amesim connection line metadata

- Truth: LEVEL B — MODEL METADATA VERIFIED
- Actual instances: control;control_1;control_10;control_11;control_12;control_13;control_14;control_15;control_16;control_17;control_18;control_19;control_2;control_20;control_21;control_22;control_23;control_24;control_25;control_26;control_27;control_28;control_29;control_3;control_30;control_31;control_32;control_33;control_34;control_35;control_36;control_37;control_38;control_39;control_4;control_40;control_41;control_42;control_43;control_44;control_45;control_46;control_47;control_48;control_49;control_5;control_50;control_51;control_52;control_53;control_54;control_6;control_7;control_8;control_9;dirvalve_1.control;dirvalve_1.control_1;dirvalve_1.control_2;dirvalve_1.control_3;dirvalve_1.control_4;dirvalve_1.control_5;dirvalve_1.control_6;dirvalve_1.hydraulic;dirvalve_1.hydraulic_1;dirvalve_1.hydraulic_10;dirvalve_1.hydraulic_11;dirvalve_1.hydraulic_2;dirvalve_1.hydraulic_3;dirvalve_1.hydraulic_4;dirvalve_1.hydraulic_5;dirvalve_1.hydraulic_6;dirvalve_1.hydraulic_7;dirvalve_1.hydraulic_8;dirvalve_1.hydraulic_9;dirvalve_10.control;dirvalve_10.control_1;dirvalve_10.control_2;dirvalve_10.hydraulic;dirvalve_10.hydraulic_1;dirvalve_10.hydraulic_2;dirvalve_10.hydraulic_3;dirvalve_10.hydraulic_4;dirvalve_11.control;dirvalve_11.control_1;dirvalve_11.control_2;dirvalve_11.control_3;dirvalve_11.control_4;dirvalve_11.control_5;dirvalve_11.control_6;dirvalve_11.hydraulic;dirvalve_11.hydraulic_1;dirvalve_11.hydraulic_10;dirvalve_11.hydraulic_11;dirvalve_11.hydraulic_2;dirvalve_11.hydraulic_3;dirvalve_11.hydraulic_4;dirvalve_11.hydraulic_5;dirvalve_11.hydraulic_6;dirvalve_11.hydraulic_7;dirvalve_11.hydraulic_8;dirvalve_11.hydraulic_9;dirvalve_12.control;dirvalve_12.control_1;dirvalve_12.control_2;dirvalve_12.hydraulic;dirvalve_12.hydraulic_1;dirvalve_12.hydraulic_2;dirvalve_12.hydraulic_3;dirvalve_13.control;dirvalve_13.control_1;dirvalve_13.control_2;dirvalve_13.hydraulic;dirvalve_13.hydraulic_1;dirvalve_13.hydraulic_2;dirvalve_13.hydraulic_3;dirvalve_13.hydraulic_4;dirvalve_2.control;dirvalve_2.control_1;dirvalve_2.control_2;dirvalve_2.hydraulic;dirvalve_2.hydraulic_1;dirvalve_2.hydraulic_2;dirvalve_2.hydraulic_3;dirvalve_3.control;dirvalve_3.control_1;dirvalve_3.control_2;dirvalve_3.hydraulic;dirvalve_3.hydraulic_1;dirvalve_3.hydraulic_2;dirvalve_3.hydraulic_3;dirvalve_3.hydraulic_4;dirvalve_6.control;dirvalve_6.control_1;dirvalve_6.control_2;dirvalve_6.control_3;dirvalve_6.control_4;dirvalve_6.control_5;dirvalve_6.control_6;dirvalve_6.hydraulic;dirvalve_6.hydraulic_1;dirvalve_6.hydraulic_10;dirvalve_6.hydraulic_11;dirvalve_6.hydraulic_2;dirvalve_6.hydraulic_3;dirvalve_6.hydraulic_4;dirvalve_6.hydraulic_5;dirvalve_6.hydraulic_6;dirvalve_6.hydraulic_7;dirvalve_6.hydraulic_8;dirvalve_6.hydraulic_9;dirvalve_8.control;dirvalve_8.control_1;dirvalve_8.control_2;dirvalve_8.control_3;dirvalve_8.control_4;dirvalve_8.control_5;dirvalve_8.control_6;dirvalve_8.hydraulic;dirvalve_8.hydraulic_1;dirvalve_8.hydraulic_10;dirvalve_8.hydraulic_11;dirvalve_8.hydraulic_2;dirvalve_8.hydraulic_3;dirvalve_8.hydraulic_4;dirvalve_8.hydraulic_5;dirvalve_8.hydraulic_6;dirvalve_8.hydraulic_7;dirvalve_8.hydraulic_8;dirvalve_8.hydraulic_9;dirvalve_9.control;dirvalve_9.control_1;dirvalve_9.control_2;dirvalve_9.hydraulic;dirvalve_9.hydraulic_1;dirvalve_9.hydraulic_2;dirvalve_9.hydraulic_3;hydraulic_10;hydraulic_100;hydraulic_102;hydraulic_104;hydraulic_105;hydraulic_106;hydraulic_107;hydraulic_108;hydraulic_109;hydraulic_110;hydraulic_111;hydraulic_112;hydraulic_114;hydraulic_116;hydraulic_117;hydraulic_12;hydraulic_120;hydraulic_121;hydraulic_123;hydraulic_124;hydraulic_125;hydraulic_126;hydraulic_128;hydraulic_13;hydraulic_130;hydraulic_132;hydraulic_133;hydraulic_135;hydraulic_138;hydraulic_139;hydraulic_140;hydraulic_141;hydraulic_144;hydraulic_145;hydraulic_146;hydraulic_151;hydraulic_152;hydraulic_154;hydraulic_155;hydraulic_156;hydraulic_157;hydraulic_16;hydraulic_160;hydraulic_161;hydraulic_162;hydraulic_163;hydraulic_164;hydraulic_17;hydraulic_170;hydraulic_171;hydraulic_172;hydraulic_18;hydraulic_182;hydraulic_185;hydraulic_186;hydraulic_187;hydraulic_19;hydraulic_190;hydraulic_2;hydraulic_20;hydraulic_21;hydraulic_22;hydraulic_24;hydraulic_25;hydraulic_26;hydraulic_28;hydraulic_29;hydraulic_30;hydraulic_33;hydraulic_36;hydraulic_37;hydraulic_40;hydraulic_42;hydraulic_43;hydraulic_44;hydraulic_45;hydraulic_46;hydraulic_47;hydraulic_48;hydraulic_49;hydraulic_5;hydraulic_50;hydraulic_51;hydraulic_52;hydraulic_53;hydraulic_54;hydraulic_55;hydraulic_60;hydraulic_64;hydraulic_65;hydraulic_66;hydraulic_67;hydraulic_72;hydraulic_73;hydraulic_74;hydraulic_75;hydraulic_76;hydraulic_78;hydraulic_8;hydraulic_82;hydraulic_83;hydraulic_85;hydraulic_86;hydraulic_87;hydraulic_88;hydraulic_90;hydraulic_92;hydraulic_93;hydraulic_96;hydraulic_97;hydraulic_98;hydraulic_99;linear;linear_1;linear_10;linear_11;linear_12;linear_2;linear_3;linear_4;linear_5;linear_6;linear_7;linear_8;linear_9;rotary;rotary_1;rotary_2;rotary_3
- Inputs/outputs: ev1 [L/min; ame_variable_io_output], ev2 [bar; ame_variable_io_input], ev3 [bar; ame_variable_io_output], ev4 [L/min; ame_variable_io_input], ev5 [cm**3; ame_variable_io_input], ev1 [bar; ame_variable_io_output], ev2 [L/min; ame_variable_io_input], ev3 [cm**3; ame_variable_io_input], ev4 [L/min; ame_variable_io_output], ev5 [cm**3; ame_variable_io_output], ev6 [bar; ame_variable_io_input], ev1 [null; ame_variable_io_output], ev2 [null; ame_variable_io_input], ev5 [bar; ame_variable_io_input], ev2 [cm**3; ame_variable_io_output], ev3 [bar; ame_variable_io_input], ev4 [bar; ame_variable_io_output], ev5 [L/min; ame_variable_io_input], ev6 [cm**3; ame_variable_io_input], ev3 [L/min; ame_variable_io_output]
- Parameters: none
- Physical states: STATELESS ALGEBRAIC ELEMENT
- Exact Amesim relation: Connectivity only; no constitutive law.
- Engineering simplified relation (LEVEL C): Connectivity only.
- Bond Graph: `non-power property object`
- Python note/status: `NON_POWER`. 
- Evidence directory: `hydraulic_audit/submodels/DIRECT/`

## FORC — constant translational force source

- Truth: LEVEL A — SOURCE VERIFIED
- Actual instances: forcecon;forcecon_1;forcecon_2;forcecon_3;forcecon_4;forcecon_5
- Inputs/outputs: input [null; ame_variable_io_input], force [N; ame_variable_io_output]
- Parameters: none
- Physical states: STATELESS ALGEBRAIC ELEMENT
- Exact Amesim relation: $F=F_0$; velocity is imposed by the connected network.
- Engineering simplified relation (LEVEL C): Same equation.
- Bond Graph: `Se`
- Python note/status: `READY_EXACT`. 
- Evidence directory: `hydraulic_audit/submodels/FORC/`

## FP04 — hydraulic fluid property object

- Truth: LEVEL A — SOURCE VERIFIED
- Actual instances: elementaryhydraulicprops_1
- Inputs/outputs: connectivity/configuration only
- Parameters: fpd [kg/m**3], fpbm [bar], fpslope [null], fpav [cP], fpavag [cP], fpsp [bar], fpac [%], fpt [degC], T1 [degC], nu1 [cSt], T2 [degC], nu2 [cSt], tvis [null], fppi [null], hsvp [bar], lsvp [bar], muvap [cP], emm [null], gdens [kg/m**3], psat [bar], proptype [-], rbtype [-], fluidfile [-], bulkmod [-], indexf [-], fluidname [-], fpfname [-]
- Physical states: STATELESS ALGEBRAIC ELEMENT
- Exact Amesim relation: Provides fluid-property configuration; it is not a power port element.
- Engineering simplified relation (LEVEL C): Read properties into a fluid configuration object.
- Bond Graph: `non-power property object`
- Python note/status: `NON_POWER`. 
- Evidence directory: `hydraulic_audit/submodels/FP04/`

## FX00 — analytical/table signal function

- Truth: LEVEL A — SOURCE VERIFIED
- Actual instances: dirvalve_1.table_13;dirvalve_1.table_14;dirvalve_1.table_23;dirvalve_1.table_24;dirvalve_1.table_fractional_spool_position;dirvalve_10.table_13;dirvalve_10.table_23;dirvalve_10.table_fractional_spool_position;dirvalve_11.table_13;dirvalve_11.table_14;dirvalve_11.table_23;dirvalve_11.table_24;dirvalve_11.table_fractional_spool_position;dirvalve_12.table_14;dirvalve_12.table_23;dirvalve_12.table_fractional_spool_position;dirvalve_13.table_13;dirvalve_13.table_23;dirvalve_13.table_fractional_spool_position;dirvalve_2.table_14;dirvalve_2.table_23;dirvalve_2.table_fractional_spool_position;dirvalve_3.table_13;dirvalve_3.table_23;dirvalve_3.table_fractional_spool_position;dirvalve_6.table_13;dirvalve_6.table_14;dirvalve_6.table_23;dirvalve_6.table_24;dirvalve_6.table_fractional_spool_position;dirvalve_8.table_13;dirvalve_8.table_14;dirvalve_8.table_23;dirvalve_8.table_24;dirvalve_8.table_fractional_spool_position;dirvalve_9.table_14;dirvalve_9.table_23;dirvalve_9.table_fractional_spool_position
- Inputs/outputs: fofx [null; ame_variable_io_output], x [null; ame_variable_io_input]
- Parameters: outputtype [-], disc [-], fstr [-]
- Physical states: STATELESS ALGEBRAIC ELEMENT
- Exact Amesim relation: $y=f(x)$ from the stored expression/table.
- Engineering simplified relation (LEVEL C): Evaluate the frozen expression/table.
- Bond Graph: `signal block`
- Python note/status: `SIGNAL_ONLY`. 
- Evidence directory: `hydraulic_audit/submodels/FX00/`

## GRAV0 — gravity configuration

- Truth: LEVEL A — SOURCE VERIFIED
- Actual instances: gravityicon
- Inputs/outputs: connectivity/configuration only
- Parameters: fixedg [m/s/s], gtype [-], mode [-], disc [-], gfile [-]
- Physical states: STATELESS ALGEBRAIC ELEMENT
- Exact Amesim relation: Configures gravitational acceleration/direction; no power bond.
- Engineering simplified relation (LEVEL C): Global gravity parameter.
- Bond Graph: `environment/configuration object`
- Python note/status: `NON_POWER`. 
- Evidence directory: `hydraulic_audit/submodels/GRAV0/`

## H3NODE1 — three-port hydraulic topology node

- Truth: LEVEL A — SOURCE VERIFIED
- Actual instances: dirvalve_1.three_way_hyd_startnode_14;dirvalve_1.three_way_hyd_startnode_23;dirvalve_11.three_way_hyd_startnode_14;dirvalve_11.three_way_hyd_startnode_23;dirvalve_6.three_way_hyd_startnode_13;dirvalve_6.three_way_hyd_startnode_24;dirvalve_8.three_way_hyd_startnode_14;dirvalve_8.three_way_hyd_startnode_23;hydrnode3_11;hydrnode3_12;hydrnode3_13;hydrnode3_14;hydrnode3_15;hydrnode3_17;hydrnode3_18;hydrnode3_19;hydrnode3_2;hydrnode3_20;hydrnode3_21;hydrnode3_22;hydrnode3_23;hydrnode3_24;hydrnode3_25;hydrnode3_26;hydrnode3_27;hydrnode3_28;hydrnode3_29;hydrnode3_3;hydrnode3_30;hydrnode3_31;hydrnode3_32;hydrnode3_33;hydrnode3_34;hydrnode3_35;hydrnode3_36;hydrnode3_37;hydrnode3_38;hydrnode3_39;hydrnode3_4;hydrnode3_40;hydrnode3_41;hydrnode3_42;hydrnode3_43;hydrnode3_44;hydrnode3_45;hydrnode3_46;hydrnode3_47;hydrnode3_48;hydrnode3_49;hydrnode3_5;hydrnode3_50;hydrnode3_51;hydrnode3_52;hydrnode3_53;hydrnode3_54;hydrnode3_55;hydrnode3_7;hydrnode3_8;hydrnode3_9
- Inputs/outputs: q1 [L/min; ame_variable_io_output], vol1 [cm**3; ame_variable_io_output], pjunc [bar; ame_variable_io_input], pjunc2 [bar; ame_variable_io_output], q2 [L/min; ame_variable_io_input], vol2 [cm**3; ame_variable_io_input], pjunc3 [bar; ame_variable_io_output], q3 [L/min; ame_variable_io_input], vol3 [cm**3; ame_variable_io_input]
- Parameters: none
- Physical states: STATELESS ALGEBRAIC ELEMENT
- Exact Amesim relation: $p_1=p_2=p_3$, $\sum q_i=0$.
- Engineering simplified relation (LEVEL C): Same equation.
- Bond Graph: `0-junction`
- Python note/status: `READY_EXACT`. 
- Evidence directory: `hydraulic_audit/submodels/H3NODE1/`

## H3NODE2 — three-port hydraulic topology node

- Truth: LEVEL A — SOURCE VERIFIED
- Actual instances: hydrnode3;hydrnode3_10
- Inputs/outputs: pjunc1 [bar; ame_variable_io_output], q1 [L/min; ame_variable_io_input], vol1 [cm**3; ame_variable_io_input], q2 [L/min; ame_variable_io_output], vol2 [cm**3; ame_variable_io_output], pjunc [bar; ame_variable_io_input], pjunc3 [bar; ame_variable_io_output], q3 [L/min; ame_variable_io_input], vol3 [cm**3; ame_variable_io_input]
- Parameters: none
- Physical states: STATELESS ALGEBRAIC ELEMENT
- Exact Amesim relation: $p_1=p_2=p_3$, $\sum q_i=0$.
- Engineering simplified relation (LEVEL C): Same equation.
- Bond Graph: `0-junction`
- Python note/status: `READY_EXACT`. 
- Evidence directory: `hydraulic_audit/submodels/H3NODE2/`

## H3NODE3 — three-port hydraulic topology node

- Truth: LEVEL A — SOURCE VERIFIED
- Actual instances: dirvalve_1.three_way_hyd_endnode_32;dirvalve_1.three_way_hyd_endnode_42;dirvalve_10.three_way_hyd_endnode_32;dirvalve_11.three_way_hyd_endnode_32;dirvalve_11.three_way_hyd_endnode_42;dirvalve_13.three_way_hyd_endnode_32;dirvalve_3.three_way_hyd_endnode_32;dirvalve_6.three_way_hyd_endnode_32;dirvalve_6.three_way_hyd_endnode_42;dirvalve_8.three_way_hyd_endnode_32;dirvalve_8.three_way_hyd_endnode_42;hydrnode3_1;hydrnode3_16;hydrnode3_6
- Inputs/outputs: pjunc1 [bar; ame_variable_io_output], q1 [L/min; ame_variable_io_input], vol1 [cm**3; ame_variable_io_input], pjunc2 [bar; ame_variable_io_output], q2 [L/min; ame_variable_io_input], vol2 [cm**3; ame_variable_io_input], q3 [L/min; ame_variable_io_output], vol3 [cm**3; ame_variable_io_output], pjunc [bar; ame_variable_io_input]
- Parameters: none
- Physical states: STATELESS ALGEBRAIC ELEMENT
- Exact Amesim relation: $p_1=p_2=p_3$, $\sum q_i=0$.
- Engineering simplified relation (LEVEL C): Same equation.
- Bond Graph: `0-junction`
- Python note/status: `READY_EXACT`. 
- Evidence directory: `hydraulic_audit/submodels/H3NODE3/`

## H4NODE1 — four-port hydraulic topology node

- Truth: LEVEL A — SOURCE VERIFIED
- Actual instances: hydrnode4_4;hydrnode4_9
- Inputs/outputs: q1 [L/min; ame_variable_io_output], vol1 [cm**3; ame_variable_io_output], pjunc [bar; ame_variable_io_input], pjunc2 [bar; ame_variable_io_output], q2 [L/min; ame_variable_io_input], vol2 [cm**3; ame_variable_io_input], pjunc3 [bar; ame_variable_io_output], q3 [L/min; ame_variable_io_input], vol3 [cm**3; ame_variable_io_input], pjunc4 [bar; ame_variable_io_output], q4 [L/min; ame_variable_io_input], vol4 [cm**3; ame_variable_io_input]
- Parameters: none
- Physical states: STATELESS ALGEBRAIC ELEMENT
- Exact Amesim relation: $p_1=\cdots=p_4$, $\sum q_i=0$.
- Engineering simplified relation (LEVEL C): Same equation.
- Bond Graph: `0-junction`
- Python note/status: `READY_EXACT`. 
- Evidence directory: `hydraulic_audit/submodels/H4NODE1/`

## H4NODE4 — four-port hydraulic topology node

- Truth: LEVEL A — SOURCE VERIFIED
- Actual instances: hydrnode4;hydrnode4_1;hydrnode4_10;hydrnode4_11
- Inputs/outputs: pjunc1 [bar; ame_variable_io_output], q1 [L/min; ame_variable_io_input], vol1 [cm**3; ame_variable_io_input], pjunc2 [bar; ame_variable_io_output], q2 [L/min; ame_variable_io_input], vol2 [cm**3; ame_variable_io_input], pjunc3 [bar; ame_variable_io_output], q3 [L/min; ame_variable_io_input], vol3 [cm**3; ame_variable_io_input], q4 [L/min; ame_variable_io_output], vol4 [cm**3; ame_variable_io_output], pjunc [bar; ame_variable_io_input]
- Parameters: none
- Physical states: STATELESS ALGEBRAIC ELEMENT
- Exact Amesim relation: $p_1=\cdots=p_4$, $\sum q_i=0$.
- Engineering simplified relation (LEVEL C): Same equation.
- Bond Graph: `0-junction`
- Python note/status: `READY_EXACT`. 
- Evidence directory: `hydraulic_audit/submodels/H4NODE4/`

## HA001 — gas-loaded hydraulic accumulator

- Truth: LEVEL A — SOURCE VERIFIED
- Actual instances: accumulator;accumulator_1
- Inputs/outputs: pout [bar; ame_variable_io_output], qout [L/min; ame_variable_io_input]
- Parameters: gaspc [bar], accvol [L], gamma [null], indexf [-], init [-]
- Physical states: pout
- Exact Amesim relation: Normal region: $(p+p_{atm})V_g^\gamma=K$, $V_g=(K/(p+p_{atm}))^{1/\gamma}$, $\dot p=\gamma(p+p_{atm})q/V_g$. Fully charged/discharged limits call pcdyn2_.
- Engineering simplified relation (LEVEL C): Use the polytropic normal-region equation with hard volume bounds; replace bound compliance by $\dot p=\beta q/V$ if needed.
- Bond Graph: `C`
- Python note/status: `READY_APPROX`. 
- Evidence directory: `hydraulic_audit/submodels/HA001/`

## HJ0022 — double-chamber single-rod spring-return cylinder

- Truth: LEVEL A — SOURCE VERIFIED
- Actual instances: springreturnactuator;springreturnactuator_1;springreturnactuator_2
- Inputs/outputs: p1 [bar; ame_variable_io_output], q1 [L/min; ame_variable_io_input], p2 [bar; ame_variable_io_output], q2 [L/min; ame_variable_io_input], frod [N; ame_variable_io_output], v [m/s; ame_variable_io_input], x [m; ame_variable_io_input]
- Parameters: xact0 [m], diamp [mm], diamr [mm], stroke [m], dead1 [cm**3], dead2 [cm**3], cvisc [N/(m/s)], cleak [L/min/bar], preld [N], ksprng [N/m], k [N/mm], cdamp [N/(m/s)], distdef [mm], indexf [-], usedispl [-]
- Physical states: p1, p2
- Exact Amesim relation: $F=A_1p_1-A_2p_2+c_vv-F_{pre}-kx+F_{stop}$; $q_l=C_l(p_1-p_2)$; chamber pressure derivatives are the HJ020 pcdyn2_ relations.
- Engineering simplified relation (LEVEL C): Two chamber C elements + area TFs + leakage/viscous R + return spring C + end-stop C/R, with $q0top=1$ and $\dot p=\beta_eq_{net}/V$.
- Bond Graph: `composite subgraph`
- Python note/status: `READY_APPROX`. 
- Evidence directory: `hydraulic_audit/submodels/HJ0022/`

## HJ020 — double-chamber single-rod cylinder with compliant chambers and end stops

- Truth: LEVEL A — SOURCE VERIFIED
- Actual instances: actuator001;actuator001_1;actuator001_2
- Inputs/outputs: p1 [bar; ame_variable_io_output], q1 [L/min; ame_variable_io_input], p2 [bar; ame_variable_io_output], q2 [L/min; ame_variable_io_input], frod [N; ame_variable_io_output], v [m/s; ame_variable_io_input], x [m; ame_variable_io_input]
- Parameters: xact0 [m], diamp [mm], diamr [mm], stroke [m], dead1 [cm**3], dead2 [cm**3], visc [N/(m/s)], leak [L/min/bar], k [N/mm], cdamp [N/(m/s)], distdef [mm], indexf [-], usedispl [-]
- Physical states: p1, p2
- Exact Amesim relation: $A_1=\pi d_p^2/4$, $A_2=\pi(d_p^2-d_r^2)/4$; $F=A_1p_1-A_2p_2+c_vv+F_{stop}$; $q_l=C_l(p_1-p_2)$; $\dot p_1=pcdyn2(p_1,0,V_1,A_1v/q0top(p_1)-q_l+q_1)$; $\dot p_2=pcdyn2(p_2,0,V_2,-A_2v/q0top(p_2)+q_l+q_2)$.
- Engineering simplified relation (LEVEL C): $\dot p_i=\beta_e q_{net,i}/V_i$ and the same force/leak/end-stop equations; take q0top=1.
- Bond Graph: `composite subgraph`
- Python note/status: `READY_APPROX`. The mechanical displacement is supplied by the connected mechanical element; chamber pressures are internal states.
- Evidence directory: `hydraulic_audit/submodels/HJ020/`

## HJ021 — double-chamber through/double-rod cylinder with compliant chambers and end stops

- Truth: LEVEL A — SOURCE VERIFIED
- Actual instances: actuator002
- Inputs/outputs: p1 [bar; ame_variable_io_output], q1 [L/min; ame_variable_io_input], p2 [bar; ame_variable_io_output], q2 [L/min; ame_variable_io_input], frod [N; ame_variable_io_output], v [m/s; ame_variable_io_input], x [m; ame_variable_io_input]
- Parameters: xact0 [m], diamp [mm], diamr1 [mm], diamr2 [mm], stroke [m], dead1 [cm**3], dead2 [cm**3], visc [N/(m/s)], leak [L/min/bar], k [N/mm], cdamp [N/(m/s)], distdef [mm], indexf [-], usedispl [-]
- Physical states: p1, p2
- Exact Amesim relation: As HJ020, but $A_1=\pi(d_p^2-d_{r1}^2)/4$, $A_2=\pi(d_p^2-d_{r2}^2)/4$; source equations for force, leakage and two pcdyn2_ chamber derivatives are otherwise analogous.
- Engineering simplified relation (LEVEL C): Two chamber C elements, two area TFs, leakage R, viscous R and end-stop C/R; $\dot p_i=\beta_eq_{net,i}/V_i$.
- Bond Graph: `composite subgraph`
- Python note/status: `READY_APPROX`. 
- Evidence directory: `hydraulic_audit/submodels/HJ021/`

## HL0000 — lumped hydraulic line compliance

- Truth: LEVEL A — SOURCE VERIFIED
- Actual instances: hydraulic_103;hydraulic_113;hydraulic_129;hydraulic_136;hydraulic_143;hydraulic_148;hydraulic_165;hydraulic_3;hydraulic_4;hydraulic_41;hydraulic_91;hydraulic_94
- Inputs/outputs: p1 [bar; ame_variable_io_output], q1 [L/min; ame_variable_io_input], p2 [bar; ame_variable_io_output], q2 [L/min; ame_variable_io_input]
- Parameters: diam [mm], a [mm], b [mm], dinn [mm], dout [mm], ecc [null], area [mm**2], dh [mm], le [m], thick [mm], emod [bar], beff [bar], bulkfluid [bar], indexf [-], method [-], volexptype [-], geom [-], dvfile [-], bmwallfile [-]
- Physical states: p1
- Exact Amesim relation: $\dot p=pcdyn02(p,V,V_c,q_{in},B_w,V_{eff},B_{eff})$ or pcdyn03_ for table-based hose properties; both ports share pressure.
- Engineering simplified relation (LEVEL C): $\dot p=(\beta_e/V)(q_1+q_2)$.
- Bond Graph: `C`
- Python note/status: `READY_APPROX`. 
- Evidence directory: `hydraulic_audit/submodels/HL0000/`

## HL0002 — R-C-R hydraulic line

- Truth: LEVEL A — SOURCE VERIFIED
- Actual instances: hydraulic_101;hydraulic_115;hydraulic_131;hydraulic_137;hydraulic_142;hydraulic_159;hydraulic_166;hydraulic_39;hydraulic_77;hydraulic_95
- Inputs/outputs: q1 [L/min; ame_variable_io_output], p1 [bar; ame_variable_io_input], q2 [L/min; ame_variable_io_output], p2 [bar; ame_variable_io_input]
- Parameters: diam [mm], a [mm], b [mm], dinn [mm], dout [mm], ecc [null], area [mm**2], dh [mm], gain [null], le [m], rr [null], ang [degree], thick [mm], emod [bar], beff [bar], bulkfluid [bar], indexf [-], method [-], volexptype [-], geom [-], dvfile [-], bmwallfile [-]
- Physical states: pmid
- Exact Amesim relation: Each end flow is returned by pipefr1_ from end pressure to midpoint pressure; $\dot p_m=pcdyn02/03(p_m,\ldots,-q_1-q_2)$.
- Engineering simplified relation (LEVEL C): Two quasi-steady resistances around a central compliance: $q_i=K_i\operatorname{sgn}(\Delta p_i)\sqrt{|\Delta p_i|}$, $\dot p_m=\beta_e(-q_1-q_2)/V$.
- Bond Graph: `composite subgraph`
- Python note/status: `READY_APPROX`. 
- Evidence directory: `hydraulic_audit/submodels/HL0002/`

## HL011 — segmented R-C hydraulic line, R-C-R end form

- Truth: LEVEL A — SOURCE VERIFIED
- Actual instances: hydraulic_56;hydraulic_57;hydraulic_61;hydraulic_62;hydraulic_63;hydraulic_70
- Inputs/outputs: q1 [L/min; ame_variable_io_output], p1 [bar; ame_variable_io_input], q2 [L/min; ame_variable_io_output], p2 [bar; ame_variable_io_input]
- Parameters: diam [mm], a [mm], b [mm], dinn [mm], dout [mm], ecc [null], area [mm**2], dh [mm], gain [null], le [m], rr [null], ang [degree], thick [mm], emod [bar], beff [bar], bulkfluid [bar], indexf [-], nodes [-], method [-], postproc [-], volexptype [-], geom [-], dvfile [-], bmwallfile [-]
- Physical states: pmid, pn_1, pn_2, pn_3, pn_4, pn_5, pn_6
- Exact Amesim relation: A source-sized chain of pipefr1_ resistive segments and pcdyn02_/pcdyn03_ pressure states; current metadata exposes pmid/pn_1..pn_6 states per instance.
- Engineering simplified relation (LEVEL C): Retain the same number of pressure cells with $\dot p_i=\beta_e(q_{i-1}-q_i)/V_i$ and calibrated quadratic/laminar segment losses.
- Bond Graph: `composite subgraph`
- Python note/status: `READY_APPROX`. 
- Evidence directory: `hydraulic_audit/submodels/HL011/`

## HL012 — segmented C-R hydraulic line, C-R-C end form

- Truth: LEVEL A — SOURCE VERIFIED
- Actual instances: hydraulic;hydraulic_1;hydraulic_11;hydraulic_118;hydraulic_119;hydraulic_122;hydraulic_127;hydraulic_134;hydraulic_14;hydraulic_147;hydraulic_149;hydraulic_15;hydraulic_150;hydraulic_153;hydraulic_158;hydraulic_180;hydraulic_181;hydraulic_23;hydraulic_27;hydraulic_31;hydraulic_32;hydraulic_34;hydraulic_35;hydraulic_38;hydraulic_58;hydraulic_59;hydraulic_6;hydraulic_68;hydraulic_69;hydraulic_7;hydraulic_71;hydraulic_79;hydraulic_80;hydraulic_81;hydraulic_84;hydraulic_89;hydraulic_9
- Inputs/outputs: p1 [bar; ame_variable_io_output], q1 [L/min; ame_variable_io_input], p2 [bar; ame_variable_io_output], q2 [L/min; ame_variable_io_input]
- Parameters: diam [mm], a [mm], b [mm], dinn [mm], dout [mm], ecc [null], area [mm**2], dh [mm], gain [null], le [m], rr [null], ang [degree], thick [mm], emod [bar], beff [bar], bulkfluid [bar], indexf [-], nodes [-], method [-], postproc [-], volexptype [-], geom [-], dvfile [-], bmwallfile [-]
- Physical states: p1, p2, pn_1, pn_2, pn_3, pn_4, pn_5
- Exact Amesim relation: A source-sized chain with endpoint pressure states p1,p2 and pn_1..pn_5; pipefr1_ supplies segment flows and pcdyn02_/03 supplies every pressure derivative.
- Engineering simplified relation (LEVEL C): Retain seven pressure cells per present instance and use $\dot p_i=\beta_e(q_{i-1}-q_i)/V_i$ plus calibrated segment resistance.
- Bond Graph: `composite subgraph`
- Python note/status: `READY_APPROX`. 
- Evidence directory: `hydraulic_audit/submodels/HL012/`

## HN222A — two-port hydraulic topology node

- Truth: LEVEL A — SOURCE VERIFIED
- Actual instances: dirvalve_1.two_port_node_bottom_1;dirvalve_1.two_port_node_bottom_2;dirvalve_1.two_port_node_top_3;dirvalve_1.two_port_node_top_4;dirvalve_10.two_port_node_bottom_1;dirvalve_10.two_port_node_bottom_2;dirvalve_10.two_port_node_top_3;dirvalve_11.two_port_node_bottom_1;dirvalve_11.two_port_node_bottom_2;dirvalve_11.two_port_node_top_3;dirvalve_11.two_port_node_top_4;dirvalve_12.two_port_node_bottom_1;dirvalve_12.two_port_node_bottom_2;dirvalve_12.two_port_node_top_3;dirvalve_12.two_port_node_top_4;dirvalve_13.two_port_node_bottom_1;dirvalve_13.two_port_node_bottom_2;dirvalve_13.two_port_node_top_3;dirvalve_2.two_port_node_bottom_1;dirvalve_2.two_port_node_bottom_2;dirvalve_2.two_port_node_top_3;dirvalve_2.two_port_node_top_4;dirvalve_3.two_port_node_bottom_1;dirvalve_3.two_port_node_bottom_2;dirvalve_3.two_port_node_top_3;dirvalve_6.two_port_node_bottom_1;dirvalve_6.two_port_node_bottom_2;dirvalve_6.two_port_node_top_3;dirvalve_6.two_port_node_top_4;dirvalve_8.two_port_node_bottom_1;dirvalve_8.two_port_node_bottom_2;dirvalve_8.two_port_node_top_3;dirvalve_8.two_port_node_top_4;dirvalve_9.two_port_node_bottom_1;dirvalve_9.two_port_node_bottom_2;dirvalve_9.two_port_node_top_3;dirvalve_9.two_port_node_top_4
- Inputs/outputs: p1 [bar; ame_variable_io_output], q1 [L/min; ame_variable_io_input], vol1 [cm**3; ame_variable_io_input], q2 [L/min; ame_variable_io_output], vol2 [cm**3; ame_variable_io_output], p2 [bar; ame_variable_io_input]
- Parameters: none
- Physical states: STATELESS ALGEBRAIC ELEMENT
- Exact Amesim relation: $p_1=p_2$, $q_1+q_2=0$.
- Engineering simplified relation (LEVEL C): Same equation.
- Bond Graph: `0-junction`
- Python note/status: `READY_EXACT`. 
- Evidence directory: `hydraulic_audit/submodels/HN222A/`

## HYDCONSHTL0 — three-port hydraulic shuttle/control junction

- Truth: LEVEL A — SOURCE VERIFIED
- Actual instances: shuttle_control;shuttle_control_1;shuttle_control_2;shuttle_control_3;shuttle_control_4;shuttle_control_5
- Inputs/outputs: q1 [L/min; ame_variable_io_output], p1 [bar; ame_variable_io_input], p2 [bar; ame_variable_io_output], q2 [L/min; ame_variable_io_input], q3 [L/min; ame_variable_io_output], p3 [bar; ame_variable_io_input]
- Parameters: indexf [-]
- Physical states: STATELESS ALGEBRAIC ELEMENT
- Exact Amesim relation: Causality-dependent macros impose the shuttle selection/equality and flow conservation; no energy storage state is declared.
- Engineering simplified relation (LEVEL C): Represent as an ideal pressure selector with a complementarity condition and $\sum q=0$; validate switching orientation from port mapping.
- Bond Graph: `composite subgraph`
- Python note/status: `READY_APPROX`. Exact macro expansion is not separately exported.
- Evidence directory: `hydraulic_audit/submodels/HYDCONSHTL0/`

## HYDORF0 — fixed hydraulic orifice

- Truth: LEVEL A — SOURCE VERIFIED
- Actual instances: flowcontrol01;flowcontrol01_1;flowcontrol01_2;flowcontrol01_3;flowcontrol01_5;flowcontrol01_6;flowcontrol01_7
- Inputs/outputs: q1 [L/min; ame_variable_io_output], p1 [bar; ame_variable_io_input], q2 [L/min; ame_variable_io_output], p2 [bar; ame_variable_io_input]
- Parameters: qchar [L/min], dpchar [bar], cqmax [null], zetamin [null], cvmax [null], kvmax [null], lamc [null], rec [null], ordiam [mm], carea [mm**2], dh [mm], a [mm], b [mm], rhochar [kg/m**3], nuchar [cSt], indexf [-], nbor [-], method [-], geom [-], userfp [-]
- Physical states: STATELESS ALGEBRAIC ELEMENT
- Exact Amesim relation: $q=orif3f(p_2,p_1,A,d_h,C_{q,max},\lambda_c,\ldots)$ after parameter-method conversion.
- Engineering simplified relation (LEVEL C): $q=C_dA\,\operatorname{sgn}(\Delta p)\sqrt{2|\Delta p|/\rho}$ with a continuous laminar branch near zero.
- Bond Graph: `R`
- Python note/status: `READY_APPROX`. 
- Evidence directory: `hydraulic_audit/submodels/HYDORF0/`

## HYDORT0 — two-port calibrated restriction used as cooler/filter

- Truth: LEVEL A — SOURCE VERIFIED
- Actual instances: cooler;cooler_1;filter;filter_1;filter_2;filter_3;filter_4;filter_5
- Inputs/outputs: q1 [L/min; ame_variable_io_output], p1 [bar; ame_variable_io_input], q2 [L/min; ame_variable_io_output], p2 [bar; ame_variable_io_input]
- Parameters: hys [bar], rhochar [kg/m**3], indexf [-], nbor [-], flowr [-], interp [-], disc [-], revflow [-], userfp [-], filenameq [-], filenameexpq [-], filenameq12 [-], filenameq21 [-], filenamedm [-], filenameexpdm [-], filenamedm12 [-], filenamedm21 [-]
- Physical states: STATELESS ALGEBRAIC ELEMENT
- Exact Amesim relation: The source evaluates mass flow from the configured pressure-drop characteristic and fluid properties, then $q=\dot m/\rho_0$.
- Engineering simplified relation (LEVEL C): Use a fitted odd monotone $q=f(\Delta p)$ (linear or square-root according to the parameterized characteristic).
- Bond Graph: `R`
- Python note/status: `READY_APPROX`. 
- Evidence directory: `hydraulic_audit/submodels/HYDORT0/`

## HYDPG0 — ideal pressure gauge / effort detector

- Truth: LEVEL A — SOURCE VERIFIED
- Actual instances: pressuregauge
- Inputs/outputs: q1 [L/min; ame_variable_io_output], p1 [bar; ame_variable_io_input]
- Parameters: indexf [-]
- Physical states: STATELESS ALGEBRAIC ELEMENT
- Exact Amesim relation: $q=0$, $y=p$.
- Engineering simplified relation (LEVEL C): Same equation.
- Bond Graph: `signal block`
- Python note/status: `SIGNAL_ONLY`. 
- Evidence directory: `hydraulic_audit/submodels/HYDPG0/`

## HYDPRV0 — pilot-operated pressure reducing valve

- Truth: LEVEL A — SOURCE VERIFIED
- Actual instances: pprv_1;pprv_2;pprv_3
- Inputs/outputs: q1 [L/min; ame_variable_io_output], p1 [bar; ame_variable_io_input], q2 [L/min; ame_variable_io_output], p2 [bar; ame_variable_io_input], q3 [L/min; ame_variable_io_output], p3 [bar; ame_variable_io_input]
- Parameters: pmin [bar], padd [bar], qchar [L/min], dpchar [bar], rhochar [kg/m**3], nuchar [cSt], hyst [bar], tau [s], wn [Hz], zeta [null], lcrit [null], indexf [-], userfp [-], spooldyn [-], fareafromxv [-]
- Physical states: STATELESS ALGEBRAIC ELEMENT
- Exact Amesim relation: $u=1-(p_3-p_2-p_{min})/p_{add}$; $x=valvedyn(u)$; $A=A(x)$; $q_3=orif3f(p_1,p_3,A,d_h(x),\ldots)$. Current spooldyn=1 is static.
- Engineering simplified relation (LEVEL C): Algebraic pressure-feedback opening $x=clip(u,0,1)$ plus square-root orifice flow.
- Bond Graph: `composite subgraph`
- Python note/status: `READY_APPROX`. 
- Evidence directory: `hydraulic_audit/submodels/HYDPRV0/`

## HYDVORF0 — signal-modulated variable hydraulic orifice

- Truth: LEVEL A — SOURCE VERIFIED
- Actual instances: dirvalve_1.orifice_13;dirvalve_1.orifice_14;dirvalve_1.orifice_23;dirvalve_1.orifice_24;dirvalve_10.orifice_13;dirvalve_10.orifice_23;dirvalve_11.orifice_13;dirvalve_11.orifice_14;dirvalve_11.orifice_23;dirvalve_11.orifice_24;dirvalve_12.orifice_14;dirvalve_12.orifice_23;dirvalve_13.orifice_13;dirvalve_13.orifice_23;dirvalve_2.orifice_14;dirvalve_2.orifice_23;dirvalve_3.orifice_13;dirvalve_3.orifice_23;dirvalve_6.orifice_13;dirvalve_6.orifice_14;dirvalve_6.orifice_23;dirvalve_6.orifice_24;dirvalve_8.orifice_13;dirvalve_8.orifice_14;dirvalve_8.orifice_23;dirvalve_8.orifice_24;dirvalve_9.orifice_14;dirvalve_9.orifice_23;variableorifice;variableorifice_1;variableorifice_10;variableorifice_11;variableorifice_12;variableorifice_13;variableorifice_14;variableorifice_2;variableorifice_3;variableorifice_4;variableorifice_5;variableorifice_6;variableorifice_7;variableorifice_8;variableorifice_9
- Inputs/outputs: input [null; ame_variable_io_input], q2 [L/min; ame_variable_io_output], p2 [bar; ame_variable_io_input], q3 [L/min; ame_variable_io_output], p3 [bar; ame_variable_io_input]
- Parameters: qchar [L/min], dpchar [bar], cqmax [null], zetamin [null], cvmax [null], kvmax [null], lamc [null], rec [null], ordiammax [mm], amax [mm], bmax [mm], rhochar [kg/m**3], nuchar [cSt], sigmin [null], sigmax [null], indexf [-], nbor [-], method [-], geom [-], userfp [-], hdvar [-], areax [-], hdx [-], hdarea [-]
- Physical states: STATELESS ALGEBRAIC ELEMENT
- Exact Amesim relation: $A=A(u)$ and $d_h=d_h(u)$ from frozen expressions/tables; $q_2=orif3f(p_3,p_2,A,d_h,C_{q,max},\lambda_c,\ldots)$, $q_3=-q_2$.
- Engineering simplified relation (LEVEL C): $q=C_dA(u)\operatorname{sgn}(p_3-p_2)\sqrt{2|p_3-p_2|/\rho}$ with a regularized zero-pressure branch.
- Bond Graph: `MR`
- Python note/status: `READY_APPROX`. 
- Evidence directory: `hydraulic_audit/submodels/HYDVORF0/`

## JUN3P — three-input signal summing junction

- Truth: LEVEL A — SOURCE VERIFIED
- Actual instances: control02;control02_1;control02_2;sum
- Inputs/outputs: input1 [null; ame_variable_io_input], output [null; ame_variable_io_output], input3 [null; ame_variable_io_input]
- Parameters: none
- Physical states: STATELESS ALGEBRAIC ELEMENT
- Exact Amesim relation: $y=s_1u_1+s_2u_2+s_3u_3$ using configured signs.
- Engineering simplified relation (LEVEL C): Same equation.
- Bond Graph: `signal block`
- Python note/status: `SIGNAL_ONLY`. 
- Evidence directory: `hydraulic_audit/submodels/JUN3P/`

## MAS001 — one-port translating mass with gravity

- Truth: LEVEL A — SOURCE VERIFIED
- Actual instances: mass1port
- Inputs/outputs: v [m/s; ame_variable_io_output], x [m; ame_variable_io_output], accel [m/s/s; ame_variable_io_output], force [N; ame_variable_io_input]
- Parameters: mass [kg], theta [degree]
- Physical states: v, x
- Exact Amesim relation: $\dot v=(mg\sin\theta-F)/m$, $\dot x=v$ (Amesim port force sign retained).
- Engineering simplified relation (LEVEL C): Same equation.
- Bond Graph: `I`
- Python note/status: `READY_EXACT`. 
- Evidence directory: `hydraulic_audit/submodels/MAS001/`

## MAS004 — two-port translating mass with friction/stiction and gravity

- Truth: LEVEL A — SOURCE VERIFIED
- Actual instances: mass_friction2port;mass_friction2port_1;mass_friction2port_2;mass_friction2port_3;mass_friction2port_4;mass_friction2port_5
- Inputs/outputs: v1 [m/s; ame_variable_io_output], x1 [m; ame_variable_io_output], a1 [m/s/s; ame_variable_io_output], f1 [N; ame_variable_io_input], v2 [m/s; ame_variable_io_output], x2 [m; ame_variable_io_output], a2 [m/s/s; ame_variable_io_output], f2 [N; ame_variable_io_input]
- Parameters: mass [kg], coefv [N/(m/s)], wind [N/(m/s)**2], coul [N], stict [N], angle [degree]
- Physical states: v1, x1
- Exact Amesim relation: linert_ computes $\dot v$ from net port force, $m$, viscous/Coulomb/stiction/wind terms; $\dot x=v$.
- Engineering simplified relation (LEVEL C): $m\dot v=F_1-F_2+mg\sin\theta-cv-F_c\operatorname{sgn}_\epsilon(v)$, $\dot x=v$.
- Bond Graph: `composite subgraph`
- Python note/status: `READY_APPROX`. 
- Evidence directory: `hydraulic_audit/submodels/MAS004/`

## PM000 — constant-speed rotational prime mover

- Truth: LEVEL A — SOURCE VERIFIED
- Actual instances: pmover01;pmover01_1;pmover01_2;pmover01_3
- Inputs/outputs: speed [rev/min; ame_variable_io_output]
- Parameters: none
- Physical states: STATELESS ALGEBRAIC ELEMENT
- Exact Amesim relation: $\omega=\omega_0$; torque is imposed by the connected network.
- Engineering simplified relation (LEVEL C): Same equation.
- Bond Graph: `Sf`
- Python note/status: `READY_EXACT`. 
- Evidence directory: `hydraulic_audit/submodels/PM000/`

## PU001 — ideal fixed-displacement hydraulic pump

- Truth: LEVEL A — SOURCE VERIFIED
- Actual instances: pump01;pump01_1;pump01_2;pump01_3
- Inputs/outputs: qin [L/min; ame_variable_io_output], pin [bar; ame_variable_io_input], qout [L/min; ame_variable_io_output], pout [bar; ame_variable_io_input], torque [Nm; ame_variable_io_output], speed [rev/min; ame_variable_io_input]
- Parameters: displ [cc/rev], wtyp [rev/min], indexf [-]
- Physical states: STATELESS ALGEBRAIC ELEMENT
- Exact Amesim relation: $D_\theta=D_{cc/rev}(1.59154943091895\times10^{-7})$; $q_{nom}=D_\theta\omega$; $f=[\tanh(1000\omega/\omega_{typ})+1]/2$; $p_u=fp_{in}+(1-f)p_{out}$; $q_{out}=q_{nom}/q0top(p_u)$; $q_{in}=-q_{out}$; $\tau=(p_{out}-p_{in})D_\theta$.
- Engineering simplified relation (LEVEL C): Use $q_{out}=D_\theta\omega$, $q_{in}=-q_{out}$ and $\tau=\Delta pD_\theta$ when density/compressibility correction is negligible.
- Bond Graph: `TF`
- Python note/status: `READY_APPROX`. No leakage or mechanical loss. Exact reproduction is bounded by q0top_.
- Evidence directory: `hydraulic_audit/submodels/PU001/`

## PV00022 — signal-controlled proportional hydraulic valve

- Truth: LEVEL A — SOURCE VERIFIED
- Actual instances: valve02;valve02_1;valve02_2;valve02_3;valve02_4;valve02_5
- Inputs/outputs: qa [L/min; ame_variable_io_output], pa [bar; ame_variable_io_input], qb [L/min; ame_variable_io_output], pb [bar; ame_variable_io_input], sigin [null; ame_variable_io_input]
- Parameters: maxin [mA], tau [s], wn [Hz], zeta [null], qchar [L/min], dpchar [bar], cqmax [null], orarea [mm**2], lcrit [null], rhochar [kg/m**3], nuchar [cSt], indexf [-], method [-], userfp [-], spooldyn [-]
- Physical states: v, x
- Exact Amesim relation: Command gives target opening; spooldyn=3 uses sndlag_ and endst2_; $A=A_{max}x$, $d_h=d_{max}\sqrt{|x|}$ and $q=orif3f(p_a,p_b,A,d_h,\ldots)$.
- Engineering simplified relation (LEVEL C): Retain the second-order spool: $\ddot x+2\zeta\omega_n\dot x+\omega_n^2x=\omega_n^2u$, then square-root orifice flow.
- Bond Graph: `composite subgraph`
- Python note/status: `READY_APPROX`. 
- Evidence directory: `hydraulic_audit/submodels/PV00022/`

## RV010 — relief valve with cracking pressure and hysteresis

- Truth: LEVEL A — SOURCE VERIFIED
- Actual instances: presscontrol01;presscontrol01_1;presscontrol01_3
- Inputs/outputs: q1 [L/min; ame_variable_io_output], p1 [bar; ame_variable_io_input], q2 [L/min; ame_variable_io_output], p2 [bar; ame_variable_io_input]
- Parameters: pcrack [bar], grad [L/min/bar], hyst [bar], indexf [-]
- Physical states: STATELESS ALGEBRAIC ELEMENT
- Exact Amesim relation: Source hysteresis selects $\Delta p_h$; $q=0$ closed, otherwise $q=G\Delta p_h$, smoothed against reverse flow by polysmooth_.
- Engineering simplified relation (LEVEL C): $q=G\max(p_2-p_1-p_{crack},0)$.
- Bond Graph: `R`
- Python note/status: `READY_APPROX`. 
- Evidence directory: `hydraulic_audit/submodels/RV010/`

## RV011 — signal-operated relief valve

- Truth: LEVEL A — SOURCE VERIFIED
- Actual instances: signaloperatedrvalve
- Inputs/outputs: q1 [L/min; ame_variable_io_output], p1 [bar; ame_variable_io_input], sig [null; ame_variable_io_input], q3 [L/min; ame_variable_io_output], p3 [bar; ame_variable_io_input]
- Parameters: pcrack [bar], grad [L/min/bar], irate [mA], hyst [bar], indexf [-]
- Physical states: STATELESS ALGEBRAIC ELEMENT
- Exact Amesim relation: The command modulates the cracking threshold; the remaining hysteretic $q=G\Delta p_h$ law is the RV010 structure.
- Engineering simplified relation (LEVEL C): $q=G\max(\Delta p-p_{crack}(u),0)$.
- Bond Graph: `MR`
- Python note/status: `READY_APPROX`. 
- Evidence directory: `hydraulic_audit/submodels/RV011/`

## SC_1 — directional-valve supercomponent wrapper

- Truth: LEVEL B — MODEL METADATA VERIFIED
- Actual instances: dirvalve_1;dirvalve_10;dirvalve_11;dirvalve_12;dirvalve_13;dirvalve_2;dirvalve_3;dirvalve_6;dirvalve_8;dirvalve_9
- Inputs/outputs: q2 [L/min; ame_variable_io_output], vol2 [cm**3; ame_variable_io_output], p2 [bar; ame_variable_io_input], x [null; ame_variable_io_input]
- Parameters: qchar_P_A [L/min], dpchar_P_A [bar], lamc_P_A [null], qchar_P_B [L/min], dpchar_P_B [bar], lamc_P_B [null], qchar_T_B [L/min], dpchar_T_B [bar], lamc_T_B [null], qchar_T_A [L/min], dpchar_T_A [bar], lamc_T_A [null], tau [s], wn [Hz], zeta [null], spooldyn [-], frac_spool_pos_vs_input [-], frac_area_P_A_vs_spool_pos [-], frac_area_P_B_vs_spool_pos [-], frac_area_T_B_vs_spool_pos [-], frac_area_T_A_vs_spool_pos [-], rhochar [null], nuchar [null], indexf [-]
- Physical states: STATELESS ALGEBRAIC ELEMENT
- Exact Amesim relation: Level-2 subgraph: external signal -> mapping table -> VALVEDYNAMICS0 -> area tables -> two or four HYDVORF0 MR branches joined by internal 0-junctions. No independent wrapper equation/source file exists.
- Engineering simplified relation (LEVEL C): Use the extracted Level-2 graph and current static spool map; implement each branch as the HYDVORF0 engineering law.
- Bond Graph: `composite subgraph`
- Python note/status: `READY_APPROX`. Instances are variant-grouped from internal component and parameter signatures.
- Evidence directory: `hydraulic_audit/submodels/SC_1/`

## SIGRECEI0 — remote signal receiver

- Truth: LEVEL A — SOURCE VERIFIED
- Actual instances: dirvalve_1.dyn_receiv_frac_spool_pos;dirvalve_10.dyn_receiv_frac_spool_pos;dirvalve_11.dyn_receiv_frac_spool_pos;dirvalve_12.dyn_receiv_frac_spool_pos;dirvalve_13.dyn_receiv_frac_spool_pos;dirvalve_2.dyn_receiv_frac_spool_pos;dirvalve_3.dyn_receiv_frac_spool_pos;dirvalve_6.dyn_receiv_frac_spool_pos;dirvalve_8.dyn_receiv_frac_spool_pos;dirvalve_9.dyn_receiv_frac_spool_pos
- Inputs/outputs: output [null; ame_variable_io_output], input [null; ame_variable_io_input]
- Parameters: label [-], showDigit [-]
- Physical states: STATELESS ALGEBRAIC ELEMENT
- Exact Amesim relation: $y=u_{remote}$.
- Engineering simplified relation (LEVEL C): Replace remote pair by a direct signal link.
- Bond Graph: `signal block`
- Python note/status: `SIGNAL_ONLY`. 
- Evidence directory: `hydraulic_audit/submodels/SIGRECEI0/`

## SIGTRANS0 — remote signal transmitter

- Truth: LEVEL A — SOURCE VERIFIED
- Actual instances: dirvalve_1.trans_frac_spool_pos;dirvalve_10.trans_frac_spool_pos;dirvalve_11.trans_frac_spool_pos;dirvalve_12.trans_frac_spool_pos;dirvalve_13.trans_frac_spool_pos;dirvalve_2.trans_frac_spool_pos;dirvalve_3.trans_frac_spool_pos;dirvalve_6.trans_frac_spool_pos;dirvalve_8.trans_frac_spool_pos;dirvalve_9.trans_frac_spool_pos
- Inputs/outputs: transout [null; ame_variable_io_output], transin [null; ame_variable_io_input]
- Parameters: label [-], showDigit [-]
- Physical states: STATELESS ALGEBRAIC ELEMENT
- Exact Amesim relation: $y_{remote}=u$.
- Engineering simplified relation (LEVEL C): Replace remote pair by a direct signal link.
- Bond Graph: `signal block`
- Python note/status: `SIGNAL_ONLY`. 
- Evidence directory: `hydraulic_audit/submodels/SIGTRANS0/`

## SIN0 — sine signal generator

- Truth: LEVEL A — SOURCE VERIFIED
- Actual instances: sinewave;sinewave_1;sinewave_2;sinewave_3;sinewave_4;sinewave_5;sinewave_6;sinewave_7;sinewave_8
- Inputs/outputs: output [null; ame_variable_io_output]
- Parameters: f [Hz], level0 [null], a [null], phi [degree]
- Physical states: STATELESS ALGEBRAIC ELEMENT
- Exact Amesim relation: $y=y_0+A\sin(2\pi f t+\phi)$.
- Engineering simplified relation (LEVEL C): Same equation.
- Bond Graph: `signal block`
- Python note/status: `SIGNAL_ONLY`. 
- Evidence directory: `hydraulic_audit/submodels/SIN0/`

## SPLT0 — signal splitter

- Truth: LEVEL A — SOURCE VERIFIED
- Actual instances: control04;control04_1;dirvalve_1.frac_spool_pos_node;dirvalve_1.three_way_signal_node_13;dirvalve_1.three_way_signal_node_23;dirvalve_1.three_way_signal_node_24;dirvalve_10.frac_spool_pos_node;dirvalve_10.three_way_signal_node_23;dirvalve_11.frac_spool_pos_node;dirvalve_11.three_way_signal_node_13;dirvalve_11.three_way_signal_node_23;dirvalve_11.three_way_signal_node_24;dirvalve_12.frac_spool_pos_node;dirvalve_12.three_way_signal_node_23;dirvalve_13.frac_spool_pos_node;dirvalve_13.three_way_signal_node_23;dirvalve_2.frac_spool_pos_node;dirvalve_2.three_way_signal_node_23;dirvalve_3.frac_spool_pos_node;dirvalve_3.three_way_signal_node_23;dirvalve_6.frac_spool_pos_node;dirvalve_6.three_way_signal_node_14;dirvalve_6.three_way_signal_node_23;dirvalve_6.three_way_signal_node_24;dirvalve_8.frac_spool_pos_node;dirvalve_8.three_way_signal_node_13;dirvalve_8.three_way_signal_node_23;dirvalve_8.three_way_signal_node_24;dirvalve_9.frac_spool_pos_node;dirvalve_9.three_way_signal_node_23;splitter2p;splitter2p2;splitter2p2_1;splitter2p2_2;splitter2p2_3;splitter2p2_4;splitter2p2_5
- Inputs/outputs: out1 [null; ame_variable_io_output], out2 [null; ame_variable_io_output], in3 [null; ame_variable_io_input]
- Parameters: none
- Physical states: STATELESS ALGEBRAIC ELEMENT
- Exact Amesim relation: $y_i=u$.
- Engineering simplified relation (LEVEL C): Same equation.
- Bond Graph: `signal block`
- Python note/status: `SIGNAL_ONLY`. 
- Evidence directory: `hydraulic_audit/submodels/SPLT0/`

## SSINK — signal sink

- Truth: LEVEL A — SOURCE VERIFIED
- Actual instances: dirvalve_1.signal_sink;dirvalve_10.signal_sink;dirvalve_11.signal_sink;dirvalve_12.signal_sink;dirvalve_13.signal_sink;dirvalve_2.signal_sink;dirvalve_3.signal_sink;dirvalve_6.signal_sink;dirvalve_8.signal_sink;dirvalve_9.signal_sink
- Inputs/outputs: sink [null; ame_variable_io_input]
- Parameters: none
- Physical states: STATELESS ALGEBRAIC ELEMENT
- Exact Amesim relation: Consumes a signal; no output and no power relation.
- Engineering simplified relation (LEVEL C): Omit after graph validation.
- Bond Graph: `signal block`
- Python note/status: `SIGNAL_ONLY`. 
- Evidence directory: `hydraulic_audit/submodels/SSINK/`

## STEP0 — step signal generator

- Truth: LEVEL A — SOURCE VERIFIED
- Actual instances: step;step_1
- Inputs/outputs: out [null; ame_variable_io_output]
- Parameters: out0 [null], out1 [null], t0 [s], td [s], transitionType [-]
- Physical states: STATELESS ALGEBRAIC ELEMENT
- Exact Amesim relation: $y=y_0$ for $t<t_s$ and $y=y_1$ otherwise.
- Engineering simplified relation (LEVEL C): Same equation.
- Bond Graph: `signal block`
- Python note/status: `SIGNAL_ONLY`. 
- Evidence directory: `hydraulic_audit/submodels/STEP0/`

## TFFD04 — thermal-fluid fluid property object

- Truth: LEVEL A — SOURCE VERIFIED
- Actual instances: elementaryhydraulicprops
- Inputs/outputs: connectivity/configuration only
- Parameters: top [degC], psat [barA], pvaph [barA], pvapl [barA], xair [%], gamma [null], muair [cP], muvap [cP], mvap [g/mol], rhoair [kg/m**3], cpgas [J/kg/K], cpvap [J/kg/K], lambdagas [W/m/K], lambdavap [W/m/K], aeratau [s], disstau [s], rhob [kg/m**3], alph [1/K], A [null], B1 [bar], B2 [bar/K], B3 [bar/K**2], B4 [bar/K**3], cp00 [J/kg/K], cp0t [J/kg/K**2], cp0t2 [J/kg/K**3], cs00 [m/s], cs0t [m/s/K], cs0t2 [m/s/K**2], fpd [kg/m**3]
- Physical states: STATELESS ALGEBRAIC ELEMENT
- Exact Amesim relation: Provides fluid-property configuration; it is not a power port element.
- Engineering simplified relation (LEVEL C): Read properties into a fluid configuration object.
- Bond Graph: `non-power property object`
- Python note/status: `NON_POWER`. 
- Evidence directory: `hydraulic_audit/submodels/TFFD04/`

## TK000 — constant-pressure hydraulic reservoir

- Truth: LEVEL A — SOURCE VERIFIED
- Actual instances: tank01;tank01_1;tank01_5;tank01_6;tank01_7
- Inputs/outputs: press [bar; ame_variable_io_output]
- Parameters: none
- Physical states: STATELESS ALGEBRAIC ELEMENT
- Exact Amesim relation: $p=p_{tank}$, with $p\ge -p_{atm}$ gauge; flow is determined by the network.
- Engineering simplified relation (LEVEL C): Same equation.
- Bond Graph: `Se`
- Python note/status: `READY_EXACT`. 
- Evidence directory: `hydraulic_audit/submodels/TK000/`

## UD00 — piecewise-linear signal table

- Truth: LEVEL A — SOURCE VERIFIED
- Actual instances: dirvalve_1_piecewiselinear;dirvalve_1_piecewiselinear_1;dirvalve_1_piecewiselinear_2;dirvalve_1_piecewiselinear_5;dirvalve_1_piecewiselinear_6;piecewiselinear_4;piecewiselinear_5
- Inputs/outputs: output [null; ame_variable_io_output]
- Parameters: tstart [s], start1 [null], end1 [null], t1 [s], start2 [null], end2 [null], t2 [s], start3 [null], end3 [null], t3 [s], start4 [null], end4 [null], t4 [s], start5 [null], end5 [null], t5 [s], start6 [null], end6 [null], t6 [s], start7 [null], end7 [null], t7 [s], start8 [null], end8 [null], t8 [s], nstages [-], iscyclic [-]
- Physical states: STATELESS ALGEBRAIC ELEMENT
- Exact Amesim relation: $y=\operatorname{interp1}(x;\{x_i,y_i\})$ with Amesim table extrapolation rules.
- Engineering simplified relation (LEVEL C): Piecewise-linear interpolation; clamp outside table if model metadata requests it.
- Bond Graph: `signal block`
- Python note/status: `SIGNAL_ONLY`. 
- Evidence directory: `hydraulic_audit/submodels/UD00/`

## VALVEDYNAMICS0 — fractional spool-position dynamics

- Truth: LEVEL A — SOURCE VERIFIED
- Actual instances: dirvalve_1.fractional_spool_position_dynamics;dirvalve_10.fractional_spool_position_dynamics;dirvalve_11.fractional_spool_position_dynamics;dirvalve_12.fractional_spool_position_dynamics;dirvalve_13.fractional_spool_position_dynamics;dirvalve_2.fractional_spool_position_dynamics;dirvalve_3.fractional_spool_position_dynamics;dirvalve_6.fractional_spool_position_dynamics;dirvalve_8.fractional_spool_position_dynamics;dirvalve_9.fractional_spool_position_dynamics
- Inputs/outputs: output [null; ame_variable_io_output], input [null; ame_variable_io_input]
- Parameters: tau [s], wn [Hz], zeta [null], xmin [null], xmax [null], spooldyn [-]
- Physical states: STATELESS ALGEBRAIC ELEMENT
- Exact Amesim relation: `spooldyn=1`: static limited/hysteretic map; `2`: $\tau\dot x=u-x$; `3`: $\ddot x+2\zeta\omega_n\dot x+\omega_n^2x=\omega_n^2u$, with limits/end stops.
- Engineering simplified relation (LEVEL C): For the present SC_1 instances spooldyn=1, use the static limited map; there are no active states.
- Bond Graph: `signal block`
- Python note/status: `SIGNAL_ONLY`. Current-model spooldyn=1 is source-verified stateless.
- Evidence directory: `hydraulic_audit/submodels/VALVEDYNAMICS0/`

