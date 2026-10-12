"""Small vector PID baseline; tuning and actuator-specific logic are out of scope for R01.

PHASE J1 起 ``step`` 同时记录**未限幅请求**与**实际阀命令**：``Command`` 只返回
限幅后的命令，因此调用方如果拿它来判断"是否饱和"，永远得到 0 —— 这正是 PHASE M3
里"报告 0% 饱和、而 CSV 里大量阀命令已经贴到 ±1"的根因。饱和诊断现在由
:class:`PIDDiagnostics` 单独给出。
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from .base import Command, Controller, Measurement, Reference


@dataclass(frozen=True, slots=True)
class PIDDiagnostics:
    """一个控制周期的真实饱和诊断（全部是数组，逐通道）。"""

    #: PID 未限幅输出（就是"请求"）
    unclipped_request: NDArray[np.float64]
    #: 限幅后、经阀极性与命令窗口映射之前的命令
    clipped_command: NDArray[np.float64]
    #: 该通道本轮是否被限幅器削顶
    at_limit: NDArray[np.bool_]
    #: 该通道本轮是否触发积分抗饱和（错误方向与饱和方向一致）
    anti_windup_active: NDArray[np.bool_]
    #: 限幅余量（= limit − |request|，负值表示被削了多少）
    margin: NDArray[np.float64]


class PIDController(Controller):
    def __init__(self, kp: float, ki: float = 0.0, kd: float = 0.0, limit: float = 1.0):
        self.kp = float(kp)
        self.ki = float(ki)
        self.kd = float(kd)
        self.limit = float(limit)
        if self.limit <= 0.0:
            raise ValueError("limit must be positive")
        self.reset()

    def reset(self) -> None:
        self._integral: np.ndarray | None = None
        self._previous_error: np.ndarray | None = None
        self.diagnostics: PIDDiagnostics | None = None

    def step(self, measurement: Measurement, reference: Reference, dt: float) -> Command:
        if dt <= 0.0:
            raise ValueError("dt must be positive")
        error = np.asarray(reference.values, dtype=float) - np.asarray(measurement.values, dtype=float)
        if self._integral is None:
            self._integral = np.zeros_like(error)
        derivative = (
            np.zeros_like(error)
            if self._previous_error is None
            else (error - self._previous_error) / dt
        )
        candidate_integral = self._integral + error * dt
        raw = self.kp * error + self.ki * candidate_integral + self.kd * derivative
        command = np.clip(raw, -self.limit, self.limit)
        at_limit = np.abs(raw) > self.limit + 1.0e-12
        # Conditional integration: do not wind up further into saturation.
        integrate = (~at_limit) | (np.sign(error) != np.sign(raw))
        anti_windup = at_limit & ~integrate
        self._integral = np.where(integrate, candidate_integral, self._integral)
        self._previous_error = error.copy()
        self.diagnostics = PIDDiagnostics(
            unclipped_request=np.asarray(raw, dtype=float),
            clipped_command=np.asarray(command, dtype=float),
            at_limit=np.asarray(at_limit, dtype=bool),
            anti_windup_active=np.asarray(anti_windup, dtype=bool),
            margin=np.asarray(self.limit - np.abs(raw), dtype=float))
        return Command(np.asarray(command, dtype=float))
