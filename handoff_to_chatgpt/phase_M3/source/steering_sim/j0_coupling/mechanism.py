"""PHASE M3：机械机构模式选择（``AS_BUILT_REFERENCE`` / ``REDESIGNED_ACKERMANN``）。

两种机构并存，**互不覆盖**：

``AS_BUILT_REFERENCE``
    甲方原始铰点与原始杆件拓扑（``mechanics_ackermann_v2``）。五、六桥的
    "摆臂—长边拉杆—车轮"四杆机构距死点只有 6.6°/9.7°，同桥左右轮无法同向，
    这是甲方硬点本身的几何硬约束，作为对照保留。

``REDESIGNED_ACKERMANN``
    PHASE M3 的工程设计提案（``mechanics_ackermann_redesigned``）。在不改动
    任何甲方原始坐标的前提下，增加中间摇臂与转向节之间的阿克曼转向梯形。
    结果一律标记 ``ENGINEERING_REDESIGN_PROPOSAL``，不得冒充原车结构。

两种模型都实现 ``centers`` / ``config`` / ``reference`` / ``ideal_ackermann``
/ ``q_envelopes`` / ``mechanism_state`` / ``solve_geometry``，因此 J0 集成层
不需要任何分支。
"""
from __future__ import annotations

from pathlib import Path

AS_BUILT_REFERENCE = "AS_BUILT_REFERENCE"
REDESIGNED_ACKERMANN = "REDESIGNED_ACKERMANN"
MODES = (AS_BUILT_REFERENCE, REDESIGNED_ACKERMANN)

#: 界面与报告使用的模式说明（中文）。
MODE_LABELS = {
    AS_BUILT_REFERENCE: "原始机构复现（甲方原始硬点，对照用）",
    REDESIGNED_ACKERMANN: "优化设计机构（ENGINEERING_REDESIGN_PROPOSAL）",
}

REDESIGN_DISCLAIMER = (
    "该机构为基于甲方硬点与工程假设提出的优化设计方案，尚未通过实车验证。"
    "图中「优化机构」角度是设计计算值，不是甲方原始结构的实测或复现结果。"
)


class UnknownMechanicalMode(ValueError):
    pass


def normalise_mode(value: str | None) -> str:
    mode = str(value or REDESIGNED_ACKERMANN).strip().upper()
    if mode not in MODES:
        raise UnknownMechanicalMode(
            f"未知的机械模式 {value!r}；可用：{', '.join(MODES)}")
    return mode


def build_mechanism_model(mode: str, spec_path: str | Path,
                          mech_config_path: str | Path | None = None,
                          redesign_config_path: str | Path | None = None,
                          design_path: str | Path | None = None):
    """按模式构造机构模型。"""
    selected = normalise_mode(mode)
    if selected == AS_BUILT_REFERENCE:
        from mechanics_ackermann_v2.model import PhaseM1Model
        if mech_config_path is None:
            raise ValueError("AS_BUILT_REFERENCE 需要 mechanics_ackermann_v2/config.json")
        return PhaseM1Model(spec_path, mech_config_path)
    from mechanics_ackermann_redesigned.model import RedesignedAckermannModel
    if redesign_config_path is None:
        raise ValueError("REDESIGNED_ACKERMANN 需要 mechanics_ackermann_redesigned/config.json")
    return RedesignedAckermannModel(spec_path, redesign_config_path, design_path)
