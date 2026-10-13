"""Gamma-process multi-mode degradation and right-censored Monte Carlo RUL."""
from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Any, Callable, Mapping

import numpy as np

from .damage import ComponentDamageState
from .multimode import D3Config, MultiModeDegradationState
from .rul import MissionCycleProfile, hard_failure_factors


def gamma_damage_increment(mean_increment: float, scale_damage: float,
                           rng: np.random.Generator) -> float:
    """Gamma process increment with E[dD]=mean and Var[dD]=mean*scale.

    A shared scale per mode makes independent increments additive under an
    equivalent exposure split (same Gamma process law).
    """
    if mean_increment < 0.0 or scale_damage <= 0.0:
        raise ValueError("Gamma mean must be nonnegative and scale positive")
    if mean_increment == 0.0:
        return 0.0
    return float(rng.gamma(shape=mean_increment / scale_damage,
                           scale=scale_damage))


@dataclass(frozen=True, slots=True)
class MonteCarloRULResult:
    sample_rows: tuple[Mapping[str, Any], ...]
    path_rows: tuple[Mapping[str, Any], ...]
    quantiles: Mapping[str, float | None]
    limiting_factor_counts: Mapping[str, int]
    censored_count: int
    censored_fraction: float
    sample_count: int
    random_seed: int
    runtime_s: float


SystemFailure = Callable[[MultiModeDegradationState], tuple[bool, str]]


def monte_carlo_rul(initial_state: MultiModeDegradationState,
                    profile: MissionCycleProfile, config: D3Config,
                    *, sample_count: int | None = None,
                    random_seed: int | None = None,
                    maximum_cycles: int | None = None,
                    system_failure: SystemFailure | None = None,
                    stored_paths: int = 12) -> MonteCarloRULResult:
    started = time.perf_counter()
    stochastic = config.raw["stochastic"]
    mission = config.raw["mission"]
    n = int(sample_count or stochastic["sample_count"])
    seed = int(random_seed if random_seed is not None else stochastic["random_seed"])
    horizon = int(maximum_cycles or mission["maximum_cycles"])
    if n < 1 or horizon < 1:
        raise ValueError("sample_count and maximum_cycles must be positive")
    rng = np.random.default_rng(seed)
    aggregate = {key: 0.0 for key in initial_state.modes}
    for segment in profile.segments:
        for key, exposure in segment.exposures.items():
            aggregate[key] += float(exposure)

    rows: list[Mapping[str, Any]] = []
    paths: list[Mapping[str, Any]] = []
    limiter_counts: dict[str, int] = {}
    lifetimes: list[int] = []
    censored = 0
    keys = tuple(initial_state.modes)
    for sample in range(n):
        state = initial_state
        failure_cycle: int | None = None
        limiters: tuple[str, ...] = ()
        reason = ""
        for cycle in range(1, horizon + 1):
            updated = dict(state.modes)
            for key in keys:
                kind, _, mode = key.split(":")
                mode_cfg = config.mode(kind, mode)
                deterministic, _ = updated[key].advanced(
                    rate=float(mode_cfg["rate"]),
                    equivalent_exposure=aggregate[key],
                    state_factor_alpha=float(mode_cfg["state_factor_alpha"]),
                    maximum_damage=float(mode_cfg["maximum_damage"]))
                mean = deterministic.damage - updated[key].damage
                increment = gamma_damage_increment(
                    mean, float(mode_cfg["gamma_scale_damage"]), rng)
                updated[key] = ComponentDamageState(
                    damage=min(float(mode_cfg["maximum_damage"]),
                               updated[key].damage + increment),
                    exposure=updated[key].exposure + aggregate[key])
            state = MultiModeDegradationState(updated)
            if sample < stored_paths:
                paths.append({"sample_id": sample, "mission_cycle": cycle,
                              "maximum_damage": state.max_damage,
                              **state.flat_damage()})
            factors, reasons = hard_failure_factors(state, config)
            if factors:
                failure_cycle = cycle
                limiters = tuple(dict.fromkeys(factors))
                reason = "|".join(reasons)
            elif system_failure is not None:
                failed, system_reason = system_failure(state)
                if failed:
                    failure_cycle = cycle
                    limiters = ("system_quality_surrogate",)
                    reason = system_reason
            if failure_cycle is not None:
                break
        if failure_cycle is None:
            censored += 1
            row = {"sample_id": sample, "status": "RIGHT_CENSORED",
                   "failure_cycle": "", "remaining_complete_cycles": f">={horizon}",
                   "limiting_factors": "", "failure_reason": "",
                   "horizon_cycles": horizon, "random_seed": seed}
        else:
            lifetimes.append(failure_cycle)
            for limiter in limiters:
                limiter_counts[limiter] = limiter_counts.get(limiter, 0) + 1
            row = {"sample_id": sample, "status": "FAILURE_REACHED",
                   "failure_cycle": failure_cycle,
                   "remaining_complete_cycles": failure_cycle - 1,
                   "limiting_factors": "|".join(limiters),
                   "failure_reason": reason, "horizon_cycles": horizon,
                   "random_seed": seed}
        rows.append(row)

    quantiles: dict[str, float | None] = {}
    # These are quantiles of observed stochastic-path lifetimes, not confidence
    # intervals on an estimated mean.  Censored paths remain explicitly separate.
    for label, probability in (("p05", 0.05), ("p10", 0.10), ("p50", 0.50),
                               ("p90", 0.90), ("p95", 0.95)):
        quantiles[label] = (float(np.quantile(lifetimes, probability,
                                              method="linear"))
                            if lifetimes else None)
    return MonteCarloRULResult(
        sample_rows=tuple(rows), path_rows=tuple(paths), quantiles=quantiles,
        limiting_factor_counts=limiter_counts, censored_count=censored,
        censored_fraction=censored / n, sample_count=n, random_seed=seed,
        runtime_s=time.perf_counter() - started)
