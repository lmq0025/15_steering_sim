"""Minimal power-port value objects used at subsystem boundaries.

Sign convention: ``power > 0`` means power entering the component that owns the
port. A coupler must reverse one side's orientation when connecting two ports.
All values use SI units.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class HydraulicPowerPort:
    """Hydraulic effort/flow pair: pressure [Pa], volume flow [m^3/s]."""

    pressure: float
    flow: float

    @property
    def power(self) -> float:
        """Instantaneous hydraulic power ``p * Q`` [W]."""
        return float(self.pressure * self.flow)


@dataclass(frozen=True, slots=True)
class TranslationalPowerPort:
    """Translational effort/flow pair: force [N], velocity [m/s]."""

    force: float
    velocity: float

    @property
    def power(self) -> float:
        """Instantaneous translational power ``F * v`` [W]."""
        return float(self.force * self.velocity)


@dataclass(frozen=True, slots=True)
class RotationalPowerPort:
    """Rotational effort/flow pair: torque [N m], angular velocity [rad/s]."""

    torque: float
    angular_velocity: float

    @property
    def power(self) -> float:
        """Instantaneous rotational power ``T * omega`` [W]."""
        return float(self.torque * self.angular_velocity)

