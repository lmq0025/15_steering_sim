from __future__ import annotations

from dataclasses import dataclass
import numpy as np


@dataclass(frozen=True)
class SecondOrderModel:
    poles: tuple[complex, complex]
    natural_frequency: float
    damping_ratio: float
    dc_gain: float


def dominant_second_order(a: np.ndarray, dc_gain: float = 1.0) -> SecondOrderModel | None:
    eig = np.linalg.eigvals(a)
    stable = [complex(v) for v in eig if v.real < -1e-9 and abs(v.imag) > 1e-7]
    if len(stable) < 2:
        return None
    pole = max(stable, key=lambda v: v.real)
    mate = min(stable, key=lambda v: abs(v - pole.conjugate()))
    wn = abs(pole)
    return SecondOrderModel((pole, mate), wn, -pole.real / wn, float(dc_gain))
