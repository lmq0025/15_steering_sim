# Bond Graph IR Freeze V3

## Scope

This is a local, traceable structural correction to IR V2.  It does not change
the frozen constitutive equations.  Amesim `ame_line` objects are classified by
metadata: `DIRECT` remains ideal connectivity, while HL0000, HL0002, HL011 and
HL012 are restored as two-port power elements.

## Physical line recovery

- Physical line elements: **65**
- Physical line ports: **130**
- Original line pressure states: **323**
- FAST line pressure states: **67**
- Original total physical states: **365**
- FAST total states: **109**

The rebuilt Level-1 hydraulic topology unions only DIRECT lines and ideal
hydraulic topology nodes.  It never unions the two ports of a physical HL line.
Level-2 SC_1 and mechanical junctions are carried forward unchanged from V2.

## variableorifice_14 correction

After restoring `hydraulic_165` (HL0000) and `hydraulic_166` (HL0002), the two
hydraulic ports of `variableorifice_14` connect to **V3_HJ_100, V3_HJ_101**.
They are distinct, so the previous “shorted redundant MR branch” conclusion is
withdrawn.

## Gate results

- physical_lines_in_elements: **PASS** — 65/65
- physical_line_ports_present: **PASS** — 130/130
- line_states_have_owner: **PASS** — 323/323
- every_physical_state_has_owner: **PASS** — 365/365
- every_stateful_line_is_power_element: **PASS** — 65/65
- every_physical_line_has_two_external_endpoints: **PASS** — 65/65
- pure_connectivity_lines_not_power_elements: **PASS** — 305 DIRECT aliases excluded
- no_physical_line_collapsed_as_junction: **PASS** — 65/65 two distinct junctions
- pump_ports_separated: **PASS** — 4/4
- actuator_chambers_separated: **PASS** — 7/7
- all_power_ports_connected: **PASS** — 408/408
- all_physical_states_owned: **PASS** — 365/365
- SC_1 hierarchy: **PASS** — Level 1 parent aliases remain opaque; Level 2 retained
- variableorifice_14_rechecked: **PASS** — V3_HJ_100;V3_HJ_101

## Freeze decision

**BOND GRAPH IR FREEZE V3 = PASS**
