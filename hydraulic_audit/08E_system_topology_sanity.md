# System Topology V4 Sanity Audit

- Components with hydraulic edges: 79
- Same-component multi-port collapse cases: 4

## Same-component multi-port cases

- `dirvalve_12`: ports ['0', '1'] → `SHJ_008`
- `dirvalve_2`: ports ['0', '1'] → `SHJ_008`
- `dirvalve_9`: ports ['0', '1'] → `SHJ_008`
- `variableorifice_14`: ports ['1', '2'] → `SHJ_003`

## Affected junctions

### SHJ_003

- net_count: 11
- topology_node_count: 4
- member_nets: hydraulic_10; hydraulic_164; hydraulic_165; hydraulic_166; hydraulic_185; hydraulic_27; hydraulic_40; hydraulic_41; hydraulic_42; hydraulic_43; hydraulic_77
- member_topology_nodes: hydrnode3_20; hydrnode3_21; hydrnode4; hydrnode4_1

### SHJ_008

- net_count: 28
- topology_node_count: 14
- member_nets: hydraulic_108; hydraulic_118; hydraulic_135; hydraulic_139; hydraulic_14; hydraulic_149; hydraulic_170; hydraulic_28; hydraulic_29; hydraulic_50; hydraulic_54; hydraulic_55; hydraulic_56; hydraulic_57; hydraulic_58; hydraulic_60; hydraulic_61; hydraulic_62; hydraulic_63; hydraulic_64; hydraulic_65; hydraulic_67; hydraulic_68; hydraulic_70; hydraulic_71; hydraulic_72; hydraulic_79; hydraulic_99
- member_topology_nodes: hydrnode3_11; hydrnode3_12; hydrnode3_13; hydrnode3_14; hydrnode3_15; hydrnode3_17; hydrnode3_23; hydrnode3_31; hydrnode3_35; hydrnode3_41; hydrnode3_46; hydrnode3_7; hydrnode3_8; hydrnode3_9

