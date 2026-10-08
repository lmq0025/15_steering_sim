# Bond Graph IR Freeze V2

**BOND GRAPH IR FREEZE V2 = PASS**

This V2 does not overwrite 08A–08E or the 10–14 V1 artifacts. It adds formal mechanical junctions, audits direct Level-2 hydraulic connections, and freezes signal causality.

## Acceptance gates

| Gate | Result | Evidence |
|---|---|---|
| Level-1 hydraulic topology | PASS | V4 baseline plus recorded 10D direct-connection correction |
| Level-2 SC_1 topology | PASS | SC_1 junctions present and direct audit complete |
| all power ports reference existing junction | PASS | 12B_v2 -> 12C_v2 referential integrity |
| mechanical junction registry | PASS | 17 formal mechanical 1-junctions |
| signal direction | PASS | 192 output-to-input links |
| pump hydraulic ports separated | PASS | all PU001 instances have >=2 distinct hydraulic junctions |
| actuator chambers separated | PASS | all HJ020/HJ021/HJ0022 instances have >=2 distinct hydraulic junctions |
| state registry consistency | PASS | 365 unique active physical states |
| no internal SC_1 alias leaked to Level 1 | PASS | element level/parent separation |
| all direct hydraulic connections accounted | PASS | Level 1 10D plus Level 2 12G |

## Mechanical junctions

- Translation 1-junctions: 13
- Rotation 1-junctions: 4
- External mechanical boundaries: 0

## SC_1 direct hydraulic audit

- Parents audited: 10
- Direct internal hflow connections found: 0
- Every parent has an explicit PASS row in 12G.

## Signal causality

- Directed links: 192
- Unresolved links: 0
- SC_1 command-to-dynamics-to-all-MR reachability: 10/10 PASS
- Direction is based on component port causality and 05_variables io_type, with explicit rules for splitter, sum, table, remote links, valve dynamics and SC_1 boundaries.

## Exact-equivalence boundary

q0top_, pcdyn*, pipefr1_ and orif3f_ remain exact-equivalence boundaries. IR V2 permits the already-approved LEVEL C surrogates for Phase 1.
