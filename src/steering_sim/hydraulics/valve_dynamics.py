"""Evidence-backed active VALVEDYNAMICS0 mode for R03-B1."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class StaticValveObservation:
    spool: float
    clipped: bool
    active_endstop: str | None


@dataclass(frozen=True, slots=True)
class StaticValveDynamics:
    """VALVEDYNAMICS0 ``spool dynamics=1``: static, order zero."""

    minimum: float
    maximum: float
    mode: int = 1

    @property
    def state_size(self) -> int:
        return 0

    def evaluate(self, command: float) -> StaticValveObservation:
        if self.mode != 1:
            raise NotImplementedError("R03-B1 implements VALVEDYNAMICS0 mode 1 only")
        spool = min(max(float(command), self.minimum), self.maximum)
        clipped = spool != float(command)
        endstop = "minimum" if spool == self.minimum and clipped else "maximum" if spool == self.maximum and clipped else None
        return StaticValveObservation(spool=spool, clipped=clipped, active_endstop=endstop)

