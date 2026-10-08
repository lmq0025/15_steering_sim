# System-Level Bond Graph Topology V4

本版本只使用顶层 Amesim alias，supercomponent 内部 alias 被明确排除。

- Top-level hydraulic nets: 177
- Top-level pure topology nodes: 62
- Canonical system hydraulic junctions: 59
- System hydraulic component edges: 174
- Pump same-junction errors: 0

## Junction original-net distribution

- 1 net(s): 30
- 2 net(s): 3
- 3 net(s): 15
- 4 net(s): 2
- 5 net(s): 1
- 7 net(s): 5
- 9 net(s): 1
- 11 net(s): 1
- 28 net(s): 1

## Pump port sanity check

- `pump01`: {'0': 'SHJ_016', '1': 'SHJ_001'}
- `pump01_1`: {'0': 'SHJ_016', '1': 'SHJ_002'}
- `pump01_2`: {'0': 'SHJ_046', '1': 'SHJ_047'}
- `pump01_3`: {'0': 'SHJ_046', '1': 'SHJ_048'}

- PASS: no pump hydraulic ports were collapsed onto the same canonical junction.
