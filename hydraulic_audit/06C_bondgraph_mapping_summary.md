# Amesim → Bond Graph 初始映射审计

本文件由 `scripts/hydraulics/build_bondgraph_mapping.py` 自动生成。

> 注意：当前结果是候选映射，不是最终 Bond Graph。最终分类必须结合元件方程、参数和因果关系确认。

## 1. 总体统计

- Component objects: 773
- Internal objects: 311
- Nets: 370
- Low-confidence components: 405

## 2. Component Bond Graph 候选类型

- `UNRESOLVED`: 373
- `SIGNAL`: 132
- `0-JUNCTION candidate`: 118
- `MR / COMPOSITE`: 45
- `R/MR`: 25
- `COMPOSITE`: 20
- `MR`: 15
- `HYDRAULIC_ELEMENT`: 12
- `TF/MTF`: 11
- `I`: 7
- `DETECTOR / MSe / MSf candidate`: 6
- `Se/C candidate`: 5
- `Se/Sf candidate`: 4

## 3. Component 物理域组合

- `EMPTY`: 373
- `hflow`: 160
- `signal`: 132
- `hflow+signal`: 60
- `remote+signal`: 20
- `hflow+lshaft`: 7
- `lshaft`: 7
- `lshaft+signal`: 6
- `hflow+rshaft`: 4
- `rshaft`: 4

## 4. Net 物理域

- `hflow`: 252
- `signal`: 101
- `lshaft`: 13
- `rshaft`: 4

## 5. 低置信度、需要人工复核的元件

- `accumulator`: hflow → HYDRAULIC_ELEMENT
- `accumulator_1`: hflow → HYDRAULIC_ELEMENT
- `control`:  → UNRESOLVED
- `control_1`:  → UNRESOLVED
- `control_10`:  → UNRESOLVED
- `control_11`:  → UNRESOLVED
- `control_12`:  → UNRESOLVED
- `control_13`:  → UNRESOLVED
- `control_14`:  → UNRESOLVED
- `control_15`:  → UNRESOLVED
- `control_16`:  → UNRESOLVED
- `control_17`:  → UNRESOLVED
- `control_18`:  → UNRESOLVED
- `control_19`:  → UNRESOLVED
- `control_2`:  → UNRESOLVED
- `control_20`:  → UNRESOLVED
- `control_21`:  → UNRESOLVED
- `control_22`:  → UNRESOLVED
- `control_23`:  → UNRESOLVED
- `control_24`:  → UNRESOLVED
- `control_25`:  → UNRESOLVED
- `control_26`:  → UNRESOLVED
- `control_27`:  → UNRESOLVED
- `control_28`:  → UNRESOLVED
- `control_29`:  → UNRESOLVED
- `control_3`:  → UNRESOLVED
- `control_30`:  → UNRESOLVED
- `control_31`:  → UNRESOLVED
- `control_32`:  → UNRESOLVED
- `control_33`:  → UNRESOLVED
- `control_34`:  → UNRESOLVED
- `control_35`:  → UNRESOLVED
- `control_36`:  → UNRESOLVED
- `control_37`:  → UNRESOLVED
- `control_38`:  → UNRESOLVED
- `control_39`:  → UNRESOLVED
- `control_4`:  → UNRESOLVED
- `control_40`:  → UNRESOLVED
- `control_41`:  → UNRESOLVED
- `control_42`:  → UNRESOLVED
- `control_43`:  → UNRESOLVED
- `control_44`:  → UNRESOLVED
- `control_45`:  → UNRESOLVED
- `control_46`:  → UNRESOLVED
- `control_47`:  → UNRESOLVED
- `control_48`:  → UNRESOLVED
- `control_49`:  → UNRESOLVED
- `control_5`:  → UNRESOLVED
- `control_50`:  → UNRESOLVED
- `control_51`:  → UNRESOLVED
- `control_52`:  → UNRESOLVED
- `control_53`:  → UNRESOLVED
- `control_54`:  → UNRESOLVED
- `control_6`:  → UNRESOLVED
- `control_7`:  → UNRESOLVED
- `control_8`:  → UNRESOLVED
- `control_9`:  → UNRESOLVED
- `dirvalve_1.control`:  → UNRESOLVED
- `dirvalve_1.control_1`:  → UNRESOLVED
- `dirvalve_1.control_2`:  → UNRESOLVED
- `dirvalve_1.control_3`:  → UNRESOLVED
- `dirvalve_1.control_4`:  → UNRESOLVED
- `dirvalve_1.control_5`:  → UNRESOLVED
- `dirvalve_1.control_6`:  → UNRESOLVED
- `dirvalve_1.dyn_receiv_frac_spool_pos`: remote+signal → COMPOSITE
- `dirvalve_1.hydraulic`:  → UNRESOLVED
- `dirvalve_1.hydraulic_1`:  → UNRESOLVED
- `dirvalve_1.hydraulic_10`:  → UNRESOLVED
- `dirvalve_1.hydraulic_11`:  → UNRESOLVED
- `dirvalve_1.hydraulic_2`:  → UNRESOLVED
- `dirvalve_1.hydraulic_3`:  → UNRESOLVED
- `dirvalve_1.hydraulic_4`:  → UNRESOLVED
- `dirvalve_1.hydraulic_5`:  → UNRESOLVED
- `dirvalve_1.hydraulic_6`:  → UNRESOLVED
- `dirvalve_1.hydraulic_7`:  → UNRESOLVED
- `dirvalve_1.hydraulic_8`:  → UNRESOLVED
- `dirvalve_1.hydraulic_9`:  → UNRESOLVED
- `dirvalve_1.trans_frac_spool_pos`: remote+signal → COMPOSITE
- `dirvalve_10.control`:  → UNRESOLVED
- `dirvalve_10.control_1`:  → UNRESOLVED
- `dirvalve_10.control_2`:  → UNRESOLVED
- `dirvalve_10.dyn_receiv_frac_spool_pos`: remote+signal → COMPOSITE
- `dirvalve_10.hydraulic`:  → UNRESOLVED
- `dirvalve_10.hydraulic_1`:  → UNRESOLVED
- `dirvalve_10.hydraulic_2`:  → UNRESOLVED
- `dirvalve_10.hydraulic_3`:  → UNRESOLVED
- `dirvalve_10.hydraulic_4`:  → UNRESOLVED
- `dirvalve_10.trans_frac_spool_pos`: remote+signal → COMPOSITE
- `dirvalve_11.control`:  → UNRESOLVED
- `dirvalve_11.control_1`:  → UNRESOLVED
- `dirvalve_11.control_2`:  → UNRESOLVED
- `dirvalve_11.control_3`:  → UNRESOLVED
- `dirvalve_11.control_4`:  → UNRESOLVED
- `dirvalve_11.control_5`:  → UNRESOLVED
- `dirvalve_11.control_6`:  → UNRESOLVED
- `dirvalve_11.dyn_receiv_frac_spool_pos`: remote+signal → COMPOSITE
- `dirvalve_11.hydraulic`:  → UNRESOLVED
- `dirvalve_11.hydraulic_1`:  → UNRESOLVED
- `dirvalve_11.hydraulic_10`:  → UNRESOLVED
- `dirvalve_11.hydraulic_11`:  → UNRESOLVED
