"""Small component protocols; concrete pump/valve/cylinder/volume laws arrive in R03."""

from __future__ import annotations

from abc import ABC, abstractmethod

from steering_sim.core.ports import HydraulicPowerPort, TranslationalPowerPort


class HydraulicPump(ABC):
    @abstractmethod
    def outlet(self, shaft_speed: float, command: float, pressure: float) -> HydraulicPowerPort: ...


class HydraulicValve(ABC):
    @abstractmethod
    def flows(self, command: float, pressures: tuple[float, ...]) -> tuple[float, ...]: ...


class HydraulicCylinder(ABC):
    @abstractmethod
    def mechanical_port(
        self, pressures: tuple[float, float], position: float, velocity: float
    ) -> TranslationalPowerPort: ...


class HydraulicVolume(ABC):
    @abstractmethod
    def pressure_derivative(self, pressure: float, net_flow: float, volume: float) -> float: ...

