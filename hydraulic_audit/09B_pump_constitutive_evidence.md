# Pump PU001 Constitutive Evidence

本报告只整理 Amesim 审计数据中已经存在的证据，不额外假设 PU001 的最终本构方程。

- Pump instances: 4

## pump01

- base_alias: `pump01`
- submodel: `PU001`
- library: `hydr`

### Parameters

- `displ@pump01`
  - title: pump displacement
  - unit: cc/rev
  - raw_value: `pd`
  - resolved_value: `10`
  - global_reference: `pd`
  - global_value: `10`

- `wtyp@pump01`
  - title: typical pump speed
  - unit: rev/min
  - raw_value: `tps`
  - resolved_value: `1350`
  - global_reference: `tps`
  - global_value: `1350`

- `indexf@pump01`
  - title: index of hydraulic fluid
  - unit: 
  - raw_value: `0`
  - resolved_value: `0`

### Variables

- `qin@pump01`
  - title: flow rate at port 2
  - unit: L/min
  - basic_type: `ame_basic_variable`
  - io_type: `ame_variable_io_output`

- `pin@pump01`
  - title: pressure at port 1
  - unit: bar
  - basic_type: `ame_basic_variable`
  - io_type: `ame_variable_io_input`

- `qout@pump01`
  - title: flow rate at port 2
  - unit: L/min
  - basic_type: `ame_basic_variable`
  - io_type: `ame_variable_io_output`

- `pout@pump01`
  - title: pressure at port 2
  - unit: bar
  - basic_type: `ame_basic_variable`
  - io_type: `ame_variable_io_input`

- `torque@pump01`
  - title: shaft torque at port 3
  - unit: Nm
  - basic_type: `ame_basic_variable`
  - io_type: `ame_variable_io_output`

- `speed@pump01`
  - title: shaft speed at port 3
  - unit: rev/min
  - basic_type: `ame_basic_variable`
  - io_type: `ame_variable_io_input`

### State variables

- No explicit state variables detected.

### System-level hydraulic connections

- port `0` → `SHJ_016` (source net `hydraulic_12`)
- port `1` → `SHJ_001` (source net `hydraulic`)

### Preliminary Bond Graph interpretation

- Hydraulic effort candidate: pressure `p`
- Hydraulic flow candidate: volume flow `q`
- Rotational effort candidate: torque `T`
- Rotational flow candidate: angular speed `ω`
- Current candidate element: `TF/MTF`
- Final constitutive relation: TODO, must be confirmed from PU001 equations/behavior.

## pump01_1

- base_alias: `pump01`
- submodel: `PU001`
- library: `hydr`

### Parameters

- `displ@pump01_1`
  - title: pump displacement
  - unit: cc/rev
  - raw_value: `pd`
  - resolved_value: `10`
  - global_reference: `pd`
  - global_value: `10`

- `wtyp@pump01_1`
  - title: typical pump speed
  - unit: rev/min
  - raw_value: `tps`
  - resolved_value: `1350`
  - global_reference: `tps`
  - global_value: `1350`

- `indexf@pump01_1`
  - title: index of hydraulic fluid
  - unit: 
  - raw_value: `0`
  - resolved_value: `0`

### Variables

- `qin@pump01_1`
  - title: flow rate at port 2
  - unit: L/min
  - basic_type: `ame_basic_variable`
  - io_type: `ame_variable_io_output`

- `pin@pump01_1`
  - title: pressure at port 1
  - unit: bar
  - basic_type: `ame_basic_variable`
  - io_type: `ame_variable_io_input`

- `qout@pump01_1`
  - title: flow rate at port 2
  - unit: L/min
  - basic_type: `ame_basic_variable`
  - io_type: `ame_variable_io_output`

- `pout@pump01_1`
  - title: pressure at port 2
  - unit: bar
  - basic_type: `ame_basic_variable`
  - io_type: `ame_variable_io_input`

- `torque@pump01_1`
  - title: shaft torque at port 3
  - unit: Nm
  - basic_type: `ame_basic_variable`
  - io_type: `ame_variable_io_output`

- `speed@pump01_1`
  - title: shaft speed at port 3
  - unit: rev/min
  - basic_type: `ame_basic_variable`
  - io_type: `ame_variable_io_input`

### State variables

- No explicit state variables detected.

### System-level hydraulic connections

- port `0` → `SHJ_016` (source net `hydraulic_13`)
- port `1` → `SHJ_002` (source net `hydraulic_1`)

### Preliminary Bond Graph interpretation

- Hydraulic effort candidate: pressure `p`
- Hydraulic flow candidate: volume flow `q`
- Rotational effort candidate: torque `T`
- Rotational flow candidate: angular speed `ω`
- Current candidate element: `TF/MTF`
- Final constitutive relation: TODO, must be confirmed from PU001 equations/behavior.

## pump01_2

- base_alias: `pump01`
- submodel: `PU001`
- library: `hydr`

### Parameters

- `displ@pump01_2`
  - title: pump displacement
  - unit: cc/rev
  - raw_value: `pd`
  - resolved_value: `10`
  - global_reference: `pd`
  - global_value: `10`

- `wtyp@pump01_2`
  - title: typical pump speed
  - unit: rev/min
  - raw_value: `tps`
  - resolved_value: `1350`
  - global_reference: `tps`
  - global_value: `1350`

- `indexf@pump01_2`
  - title: index of hydraulic fluid
  - unit: 
  - raw_value: `0`
  - resolved_value: `0`

### Variables

- `qin@pump01_2`
  - title: flow rate at port 2
  - unit: L/min
  - basic_type: `ame_basic_variable`
  - io_type: `ame_variable_io_output`

- `pin@pump01_2`
  - title: pressure at port 1
  - unit: bar
  - basic_type: `ame_basic_variable`
  - io_type: `ame_variable_io_input`

- `qout@pump01_2`
  - title: flow rate at port 2
  - unit: L/min
  - basic_type: `ame_basic_variable`
  - io_type: `ame_variable_io_output`

- `pout@pump01_2`
  - title: pressure at port 2
  - unit: bar
  - basic_type: `ame_basic_variable`
  - io_type: `ame_variable_io_input`

- `torque@pump01_2`
  - title: shaft torque at port 3
  - unit: Nm
  - basic_type: `ame_basic_variable`
  - io_type: `ame_variable_io_output`

- `speed@pump01_2`
  - title: shaft speed at port 3
  - unit: rev/min
  - basic_type: `ame_basic_variable`
  - io_type: `ame_variable_io_input`

### State variables

- No explicit state variables detected.

### System-level hydraulic connections

- port `0` → `SHJ_046` (source net `hydraulic_44`)
- port `1` → `SHJ_047` (source net `hydraulic_34`)

### Preliminary Bond Graph interpretation

- Hydraulic effort candidate: pressure `p`
- Hydraulic flow candidate: volume flow `q`
- Rotational effort candidate: torque `T`
- Rotational flow candidate: angular speed `ω`
- Current candidate element: `TF/MTF`
- Final constitutive relation: TODO, must be confirmed from PU001 equations/behavior.

## pump01_3

- base_alias: `pump01`
- submodel: `PU001`
- library: `hydr`

### Parameters

- `displ@pump01_3`
  - title: pump displacement
  - unit: cc/rev
  - raw_value: `pd`
  - resolved_value: `10`
  - global_reference: `pd`
  - global_value: `10`

- `wtyp@pump01_3`
  - title: typical pump speed
  - unit: rev/min
  - raw_value: `tps`
  - resolved_value: `1350`
  - global_reference: `tps`
  - global_value: `1350`

- `indexf@pump01_3`
  - title: index of hydraulic fluid
  - unit: 
  - raw_value: `0`
  - resolved_value: `0`

### Variables

- `qin@pump01_3`
  - title: flow rate at port 2
  - unit: L/min
  - basic_type: `ame_basic_variable`
  - io_type: `ame_variable_io_output`

- `pin@pump01_3`
  - title: pressure at port 1
  - unit: bar
  - basic_type: `ame_basic_variable`
  - io_type: `ame_variable_io_input`

- `qout@pump01_3`
  - title: flow rate at port 2
  - unit: L/min
  - basic_type: `ame_basic_variable`
  - io_type: `ame_variable_io_output`

- `pout@pump01_3`
  - title: pressure at port 2
  - unit: bar
  - basic_type: `ame_basic_variable`
  - io_type: `ame_variable_io_input`

- `torque@pump01_3`
  - title: shaft torque at port 3
  - unit: Nm
  - basic_type: `ame_basic_variable`
  - io_type: `ame_variable_io_output`

- `speed@pump01_3`
  - title: shaft speed at port 3
  - unit: rev/min
  - basic_type: `ame_basic_variable`
  - io_type: `ame_variable_io_input`

### State variables

- No explicit state variables detected.

### System-level hydraulic connections

- port `0` → `SHJ_046` (source net `hydraulic_45`)
- port `1` → `SHJ_048` (source net `hydraulic_35`)

### Preliminary Bond Graph interpretation

- Hydraulic effort candidate: pressure `p`
- Hydraulic flow candidate: volume flow `q`
- Rotational effort candidate: torque `T`
- Rotational flow candidate: angular speed `ω`
- Current candidate element: `TF/MTF`
- Final constitutive relation: TODO, must be confirmed from PU001 equations/behavior.

