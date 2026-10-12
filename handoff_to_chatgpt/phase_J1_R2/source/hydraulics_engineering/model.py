"""PHASE J1-R2 工程电液伺服模型：阀控对称双腔缸 + 共用恒压供油轨。

计算链条（任务书第三节要求的那一条，逐字对应）
----------------------------------------------

    控制命令 u
      → 阀芯一阶响应 → 阀口流量 Q(pA, pB, ps, u)
      → 双腔压力变化 dpA/dt, dpB/dt
      → 液压缸推力 F_hyd = pA·Aa − pB·Ab
      → 活塞加速度 / 速度 / 位移 (v, x)
      → 机械映射 → 十二轮实际转角

状态向量（每通道 5 个 + 每条供油轨 1 个）
-----------------------------------------

    通道 i 在偏移 5i 处： ``[pA, pB, x, v, u_f]``
    供油轨 j 在偏移 5N+j 处： ``[ps]``

``u_f`` 是阀芯的一阶响应状态。**保留真实伺服阀的有限带宽是必要的**：理想阀会让
流量出现阶跃，激励出未建模的高频模态，实际调试中表现为活塞速度与腔压的高频振荡
（J1 报告里已经观察到）。``ps`` 是蓄能器/高压腔的压力状态，需求流量超过泵能力时
它会真实下跌 —— 这就是"共用供油总量"约束，不允许无限流量。

明确禁止的两件事
----------------

* ``x`` 与 ``v`` 只由微分方程积分产生，**任何地方都不允许赋值为目标行程**；
* 轮角由同一套机械映射从**真实缸位移**反推（在 ``j0_coupling`` 层完成），
  本模块不产生任何"显示专用"的角度。
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Mapping, Sequence

import numpy as np

from .parameters import (ASSUMPTION_TAG, EngineeringHydraulicParameters,
                         ParameterError, load_parameters)

#: 通道状态个数：pA, pB, x, v, u_f
CHANNEL_STATE_SIZE = 5
#: 库仑摩擦的 tanh 正则化速度尺度（m/s）。
FRICTION_VELOCITY_EPS_M_S = 1.0e-3
#: 溢流阀流量系数（固定）。
RELIEF_DISCHARGE_COEFFICIENT = 0.62


class EngineeringHydraulicError(RuntimeError):
    """工程液压模型遇到无法继续的物理/数值状态（显式失败，不静默裁剪）。"""


def state_layout(parameters: EngineeringHydraulicParameters) -> dict[str, int]:
    """状态向量布局（供调试与报告引用）。"""
    layout = {channel.name: CHANNEL_STATE_SIZE * index
              for index, channel in enumerate(parameters.channels)}
    offset = CHANNEL_STATE_SIZE * len(parameters.channels)
    for index, name in enumerate(parameters.supply_names):
        layout[f"supply_{name}"] = offset + index
    return layout


def _soft_orifice(delta_p_pa: float, area_m2: float, density_kg_m3: float,
                  discharge_coefficient: float, regularisation_pa: float) -> float:
    """等效节流口的体积流量（m³/s，正号 = 沿 ``delta_p`` 正方向流动）。

    ``Q = Cd·A·sqrt(2/ρ)·Δp / sqrt(sqrt(Δp² + ε²))``

    ``Δp`` 较大时退化为标准 ``Cd·A·sqrt(2|Δp|/ρ)·sign(Δp)``；``Δp → 0`` 时
    变成线性，导数有界 —— 否则中位附近 ``sqrt`` 的无穷导数会让 RK4 失稳。
    """
    if area_m2 <= 0.0:
        return 0.0
    scale = discharge_coefficient * area_m2 * math.sqrt(2.0 / density_kg_m3)
    return scale * delta_p_pa / math.sqrt(math.hypot(delta_p_pa, regularisation_pa))


@dataclass(frozen=True, slots=True)
class ChannelOutput:
    """单通道输出（单位全部 SI；压力为表压 Pa）。"""

    name: str
    position_m: float
    velocity_m_s: float
    hydraulic_force_n: float
    pressure_a_pa_g: float
    pressure_b_pa_g: float
    #: 有符号流入量（正 = 流入该腔）
    flow_a_m3_s: float
    flow_b_m3_s: float
    #: 从供油轨取用的流量（正 = 从泵取油）
    supply_flow_m3_s: float
    valve_command: float
    load_force_n: float
    friction_force_n: float
    end_stop_force_n: float
    #: |x| / (stroke/2)
    stroke_utilisation: float
    at_stroke_limit: bool


@dataclass(frozen=True, slots=True)
class EngineeringOutput:
    channels: tuple[ChannelOutput, ...]
    supply_pressures_pa_g: tuple[float, ...]
    pump_capacity_insufficient: tuple[bool, ...]
    pump_capacity_margin_m3_s: tuple[float, ...]
    demand_flow_m3_s: tuple[float, ...]
    pump_flow_m3_s: tuple[float, ...]


class EngineeringHydraulicSystem:
    """四通道工程电液伺服系统（16 个基本动态状态 + 阀芯响应 + 共用供油状态）。"""

    tag = "ENGINEERING_HYDRAULIC_V1"

    def __init__(self, parameters: EngineeringHydraulicParameters) -> None:
        self.parameters = parameters
        self.channels = parameters.channels
        self.supply_names = parameters.supply_names
        self.state_size = (CHANNEL_STATE_SIZE * len(parameters.channels)
                           + len(self.supply_names))
        self._supply_offset = CHANNEL_STATE_SIZE * len(parameters.channels)
        self._supply_index = {name: self._supply_offset + index
                              for index, name in enumerate(self.supply_names)}
        self.layout = state_layout(parameters)

    # ------------------------------------------------------------------ 初值
    def neutral_state(self) -> np.ndarray:
        """零位健康状态：两腔预充压相等 ⇒ 零位无净力，t=0 是真正的平衡点。

        供油轨初值取溢流压力上限，使泵与溢流阀立刻处于工作点，不制造虚假瞬态。
        """
        parameters = self.parameters
        state = np.zeros(self.state_size)
        for index, channel in enumerate(parameters.channels):
            base = CHANNEL_STATE_SIZE * index
            state[base] = parameters.precharge_pressure_pa
            state[base + 1] = parameters.precharge_pressure_pa
            state[base + 2] = 0.0
            state[base + 3] = 0.0
            state[base + 4] = 0.0
        for name in self.supply_names:
            state[self._supply_index[name]] = self._supply_equilibrium_pressure(name)
        return state

    def _supply_equilibrium_pressure(self, name: str) -> float:
        """泵流量与溢流阀流量相等的供油压力（Pa 表压）。

        从"溢流阀设定压力"起步会让泵不停给蓄能器充液，t=0 就不是真正的平衡点，
        白白制造一段几个毫秒的充液瞬态。这里解一元二次方程
        ``K⁴w² − Q⁴w − Q⁴ε² = 0``（``w = Δp²``）得到精确的平衡点。
        """
        parameters = self.parameters
        degradation = parameters.degradation
        pump = parameters.supplies[name]
        setpoint = pump.relief_pressure_pa * degradation.supply_pressure_scale
        flow = pump.ideal_flow_m3_s * degradation.pump_volumetric_efficiency
        if flow <= 0.0:
            return setpoint
        gain = (RELIEF_DISCHARGE_COEFFICIENT * pump.relief_area_m2
                * math.sqrt(2.0 / parameters.fluid_density_kg_m3))
        epsilon = parameters.orifice_pressure_regularisation_pa
        # K⁴·w² − Q⁴·w − Q⁴·ε² = 0
        a = gain ** 4
        q4 = flow ** 4
        w = (q4 + math.sqrt(q4 * q4 + 4.0 * a * q4 * epsilon * epsilon)) / (2.0 * a)
        return setpoint + math.sqrt(max(0.0, w))

    #: 兼容 J0 集成层的命名（L1-Fast 里叫 ``working_point``）。
    def working_point(self) -> tuple[np.ndarray, tuple[float, float, float, float]]:
        """返回 ``(零位状态, 零位外部负载)``。

        零位两腔预充压相等、外部负载为零，所以不需要 L1-Fast 那种"初始化装置"
        偏置去抵消预建压力。
        """
        return self.neutral_state(), (0.0, 0.0, 0.0, 0.0)

    @property
    def pump_speeds_rad_s(self) -> tuple[float, float, float, float]:
        speeds = []
        for channel in self.parameters.channels:
            speeds.append(self.parameters.supplies[channel.supply].nominal_speed_rad_s)
        while len(speeds) < 4:
            speeds.append(0.0)
        return tuple(speeds)  # type: ignore[return-value]

    # ---------------------------------------------------------------- 评价
    def evaluate(self, t: float, state: np.ndarray, inputs: Any
                 ) -> tuple[np.ndarray, EngineeringOutput]:
        """计算状态导数与输出。``inputs`` 只需鸭子类型地提供
        ``valve_commands`` 与 ``external_load_forces_n``（长度 = 通道数）。
        """
        parameters = self.parameters
        degradation = parameters.degradation
        state = np.asarray(state, dtype=float)
        if state.shape != (self.state_size,):
            raise EngineeringHydraulicError(
                f"状态维数不符：期望 {self.state_size}，得到 {state.shape}")
        commands = tuple(float(value) for value in inputs.valve_commands)
        loads = tuple(float(value) for value in inputs.external_load_forces_n)
        if len(commands) != len(parameters.channels) or \
                len(loads) != len(parameters.channels):
            raise EngineeringHydraulicError("输入通道数与参数不符")

        beta = parameters.fluid_bulk_modulus_pa
        density = parameters.fluid_density_kg_m3
        tank = parameters.tank_pressure_pa
        regularisation = parameters.orifice_pressure_regularisation_pa
        derivative = np.zeros(self.state_size)
        demand = {name: 0.0 for name in self.supply_names}
        outputs: list[ChannelOutput] = []

        for index, channel in enumerate(parameters.channels):
            base = CHANNEL_STATE_SIZE * index
            cylinder = channel.cylinder
            valve = channel.valve
            p_a = float(state[base])
            p_b = float(state[base + 1])
            x = float(state[base + 2])
            v = float(state[base + 3])
            u_f = float(state[base + 4])
            supply_pressure = float(state[self._supply_index[channel.supply]]) * \
                degradation.supply_pressure_scale

            # --- 阀芯一阶响应（含死区）
            raw = float(np.clip(commands[index], -channel.command_limit,
                                channel.command_limit))
            deadband = float(valve.deadband)
            if deadband > 0.0:
                magnitude = max(0.0, abs(raw) - deadband) / max(1.0e-9, 1.0 - deadband)
                raw = math.copysign(magnitude, raw) if raw != 0.0 else 0.0
            tau = max(1.0e-4, valve.lag_time_s * degradation.valve_lag_scale)
            derivative[base + 4] = (raw - u_f) / tau
            u = float(np.clip(u_f, -1.0, 1.0))
            u_pos = max(u, 0.0)
            u_neg = max(-u, 0.0)

            area = valve.maximum_area_m2 * degradation.valve_flow_coefficient_scale
            coefficient = valve.discharge_coefficient
            # --- 四通阀：u > 0 时 P→A、B→T；u < 0 时 P→B、A→T
            flow_a_in = (
                _soft_orifice(supply_pressure - p_a, area * u_pos, density,
                              coefficient, regularisation)
                - _soft_orifice(p_a - tank, area * u_neg, density,
                                coefficient, regularisation))
            flow_b_in = (
                _soft_orifice(supply_pressure - p_b, area * u_neg, density,
                              coefficient, regularisation)
                - _soft_orifice(p_b - tank, area * u_pos, density,
                                coefficient, regularisation))
            supply_flow = (
                _soft_orifice(supply_pressure - p_a, area * u_pos, density,
                              coefficient, regularisation)
                + _soft_orifice(supply_pressure - p_b, area * u_neg, density,
                                coefficient, regularisation))
            # --- 缸内泄漏（退化接口；新件为 0）
            leak = degradation.cylinder_internal_leakage_m3_s_per_pa * (p_a - p_b)
            flow_a_in -= leak
            flow_b_in += leak

            # --- 腔容积：绝不能非正。用**相对活塞中位**的位移 xc，
            #     因为缸中位相对机构坐标是偏置的（机构行程区间不对称）。
            xc = x - cylinder.stroke_offset_m
            volume_a = cylinder.dead_volume_m3 + cylinder.area_a_m2 * (
                cylinder.half_stroke_m + xc)
            volume_b = cylinder.dead_volume_m3 + cylinder.area_b_m2 * (
                cylinder.half_stroke_m - xc)
            if volume_a <= 0.0 or volume_b <= 0.0:
                raise EngineeringHydraulicError(
                    f"{channel.name}: 腔容积非正（VA={volume_a:.3e}, VB={volume_b:.3e}, "
                    f"x={x:+.4f} m）—— 状态已发散，不静默裁剪")
            derivative[base] = beta / volume_a * (
                flow_a_in - cylinder.area_a_m2 * v)
            derivative[base + 1] = beta / volume_b * (
                flow_b_in + cylinder.area_b_m2 * v)

            # --- 活塞动力学
            hydraulic_force = p_a * cylinder.area_a_m2 - p_b * cylinder.area_b_m2
            friction = degradation.cylinder_friction_scale * (
                cylinder.coulomb_friction_n * math.tanh(v / FRICTION_VELOCITY_EPS_M_S)
                + cylinder.viscous_damping_n_s_per_m * v)
            over = abs(xc) - cylinder.half_stroke_m
            end_stop = 0.0
            if over > 0.0:
                end_stop = (math.copysign(
                    cylinder.end_stop_stiffness_n_per_m * over, xc)
                    + cylinder.end_stop_damping_n_s_per_m * v)
            derivative[base + 3] = (hydraulic_force - loads[index] - friction
                                    - end_stop) / cylinder.mass_kg
            derivative[base + 2] = v

            demand[channel.supply] += supply_flow
            outputs.append(ChannelOutput(
                name=channel.name, position_m=x, velocity_m_s=v,
                hydraulic_force_n=hydraulic_force,
                pressure_a_pa_g=p_a, pressure_b_pa_g=p_b,
                flow_a_m3_s=flow_a_in, flow_b_m3_s=flow_b_in,
                supply_flow_m3_s=supply_flow,
                valve_command=u, load_force_n=loads[index],
                friction_force_n=friction, end_stop_force_n=end_stop,
                stroke_utilisation=abs(xc) / cylinder.half_stroke_m,
                at_stroke_limit=over > 0.0))

        # --- 共用供油轨：泵 → 蓄能器 → 溢流阀 → 各通道
        pressures: list[float] = []
        insufficient: list[bool] = []
        margins: list[float] = []
        pump_flows: list[float] = []
        demands: list[float] = []
        for name in self.supply_names:
            pump = parameters.supplies[name]
            offset = self._supply_index[name]
            pressure = float(state[offset])
            pump_flow = pump.ideal_flow_m3_s * \
                degradation.pump_volumetric_efficiency
            pump_flow -= degradation.pump_internal_leakage_m3_s_per_pa * pressure
            pump_flow = max(0.0, pump_flow)
            relief_set = pump.relief_pressure_pa * degradation.supply_pressure_scale
            relief_flow = max(0.0, _soft_orifice(
                pressure - relief_set, pump.relief_area_m2, density,
                RELIEF_DISCHARGE_COEFFICIENT, regularisation))
            derivative[offset] = (pump.bulk_modulus_pa / pump.plenum_volume_m3) * (
                pump_flow - relief_flow - demand[name])
            pressures.append(pressure)
            pump_flows.append(pump_flow)
            demands.append(demand[name])
            margins.append(pump_flow - demand[name])
            insufficient.append(demand[name] > pump_flow)

        if not np.all(np.isfinite(derivative)):
            raise EngineeringHydraulicError("状态导数出现非有限值")

        return derivative, EngineeringOutput(
            channels=tuple(outputs),
            supply_pressures_pa_g=tuple(pressures),
            pump_capacity_insufficient=tuple(insufficient),
            pump_capacity_margin_m3_s=tuple(margins),
            demand_flow_m3_s=tuple(demands),
            pump_flow_m3_s=tuple(pump_flow_s for pump_flow_s in pump_flows))


def evaluate_hydraulic_engineering(system: EngineeringHydraulicSystem, t: float,
                                   state: np.ndarray, inputs: Any
                                   ) -> tuple[np.ndarray, EngineeringOutput]:
    """与 ``hydraulics_lumped.evaluate_hydraulic`` 同签名的评价入口。"""
    return system.evaluate(t, state, inputs)


def build_system(path: str | Any) -> EngineeringHydraulicSystem:
    return EngineeringHydraulicSystem(load_parameters(path))
