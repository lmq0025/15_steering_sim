# Actual Submodel Audit Inventory

Final reviewed inventory generated from model metadata, V4 topology, direct-connection correction, and installed Amesim sources.

- TOTAL UNIQUE SUBMODELS: 47
- SYSTEM-LEVEL SUBMODELS: 41
- SUPERCOMPONENT INTERNAL SUBMODELS: 10
- READY_EXACT: 10
- READY_APPROX: 21
- BLOCKED: 0
- SIGNAL_ONLY: 12
- NON_POWER: 4

`ame_state_variable` metadata contains diagnostic/fixed/zero-sized entries; only active physical integration states are counted in 11A.

| Submodel | Instances | Library | Level-1 | Internal | Candidate | Priority | Final status |
|---|---:|---|---|---|---|---|---|
| CONS00 | 15 | sig | yes | no | SIGNAL | P3 | SIGNAL_ONLY |
| CV010 | 6 | hydr | yes | no | R/MR | P1 | READY_APPROX |
| CV012 | 1 | hydr | yes | no | R/MR | P3 | READY_APPROX |
| DIRECT | 305 | - | yes | no | unresolved | P3 | NON_POWER |
| FORC | 6 | meca | yes | no | DETECTOR / MSe / MSf candidate | P3 | READY_EXACT |
| FP04 | 1 | hydr | yes | no | UNRESOLVED | P3 | NON_POWER |
| FX00 | 38 | sig | no | yes | SIGNAL | P2 | SIGNAL_ONLY |
| GRAV0 | 1 | meca | yes | no | UNRESOLVED | P3 | NON_POWER |
| H3NODE1 | 59 | hydr | yes | yes | 0-JUNCTION candidate | P2 | READY_EXACT |
| H3NODE2 | 2 | hydr | yes | no | 0-JUNCTION candidate | P3 | READY_EXACT |
| H3NODE3 | 14 | hydr | yes | yes | 0-JUNCTION candidate | P2 | READY_EXACT |
| H4NODE1 | 2 | hydr | yes | no | 0-JUNCTION candidate | P3 | READY_EXACT |
| H4NODE4 | 4 | hydr | yes | no | 0-JUNCTION candidate | P3 | READY_EXACT |
| HA001 | 2 | hydr | yes | no | HYDRAULIC_ELEMENT | P3 | READY_APPROX |
| HJ0022 | 3 | hydr | yes | no | TF/MTF | P0 | READY_APPROX |
| HJ020 | 3 | hydr | yes | no | TF/MTF | P0 | READY_APPROX |
| HJ021 | 1 | hydr | yes | no | TF/MTF | P0 | READY_APPROX |
| HL0000 | 12 | hydr | yes | no | unresolved | P3 | READY_APPROX |
| HL0002 | 10 | hydr | yes | no | unresolved | P3 | READY_APPROX |
| HL011 | 6 | hydr | yes | no | unresolved | P3 | READY_APPROX |
| HL012 | 37 | hydr | yes | no | unresolved | P3 | READY_APPROX |
| HN222A | 37 | hydr | no | yes | 0-JUNCTION candidate | P2 | READY_EXACT |
| HYDCONSHTL0 | 6 | hydr | yes | no | HYDRAULIC_ELEMENT | P1 | READY_APPROX |
| HYDORF0 | 7 | hydr | yes | no | R/MR | P1 | READY_APPROX |
| HYDORT0 | 8 | hydr | yes | no | R/MR | P1 | READY_APPROX |
| HYDPG0 | 1 | hydr | yes | no | HYDRAULIC_ELEMENT | P1 | SIGNAL_ONLY |
| HYDPRV0 | 3 | hydr | yes | no | HYDRAULIC_ELEMENT | P1 | READY_APPROX |
| HYDVORF0 | 43 | hydr | yes | yes | MR;MR / COMPOSITE | P0 | READY_APPROX |
| JUN3P | 4 | sig | yes | no | SIGNAL | P3 | SIGNAL_ONLY |
| MAS001 | 1 | meca | yes | no | I | P3 | READY_EXACT |
| MAS004 | 6 | meca | yes | no | I | P3 | READY_APPROX |
| PM000 | 4 | meca | yes | no | Se/Sf candidate | P3 | READY_EXACT |
| PU001 | 4 | hydr | yes | no | TF/MTF | P0 | READY_APPROX |
| PV00022 | 6 | hydr | yes | no | MR / COMPOSITE | P1 | READY_APPROX |
| RV010 | 3 | hydr | yes | no | R/MR | P1 | READY_APPROX |
| RV011 | 1 | hydr | yes | no | MR / COMPOSITE | P1 | READY_APPROX |
| SC_1 | 10 | - | yes | no | MR / COMPOSITE | P0 | READY_APPROX |
| SIGRECEI0 | 10 | sig | no | yes | SIGNAL | P2 | SIGNAL_ONLY |
| SIGTRANS0 | 10 | sig | no | yes | SIGNAL | P2 | SIGNAL_ONLY |
| SIN0 | 9 | sig | yes | no | SIGNAL | P3 | SIGNAL_ONLY |
| SPLT0 | 37 | sig | yes | yes | SIGNAL | P2 | SIGNAL_ONLY |
| SSINK | 10 | sig | no | yes | SIGNAL | P2 | SIGNAL_ONLY |
| STEP0 | 2 | sig | yes | no | SIGNAL | P3 | SIGNAL_ONLY |
| TFFD04 | 1 | tf | yes | no | UNRESOLVED | P3 | NON_POWER |
| TK000 | 5 | hydr | yes | no | Se/C candidate | P1 | READY_EXACT |
| UD00 | 7 | sig | yes | no | SIGNAL | P3 | SIGNAL_ONLY |
| VALVEDYNAMICS0 | 10 | sig | no | yes | SIGNAL | P2 | SIGNAL_ONLY |
