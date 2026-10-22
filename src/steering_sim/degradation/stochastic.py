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
    mean = np.asarray(mean_increment, dtype=float)
    if np.any(mean < 0.0) or scale_damage <= 0.0:
        raise ValueError("Gamma mean must be nonnegative and scale positive")
    if mean.ndim == 0 and mean == 0.0:
        return 0.0
    value = rng.gamma(shape=mean / scale_damage, scale=scale_damage)
    return float(value) if mean.ndim == 0 else value


def gamma_advance(damage, exposure, mode_config, rng):
    """Shared scalar/vector conditional-mean transition for D3 and desktop.

    The unbounded Gamma mean is the capped deterministic increment at the
    current state. Capping the sampled new state reduces its mean near the
    upper boundary; no post-hoc mean matching is performed.
    """
    old = np.asarray(damage, dtype=float)
    maximum = float(mode_config['maximum_damage'])
    alpha = float(mode_config['state_factor_alpha'])
    dose = float(mode_config['rate'])*exposure
    increment = (dose if alpha == 0 else (old+1/alpha)*np.expm1(alpha*dose))
    mean = np.maximum(0, np.minimum(maximum-old, increment))
    return np.minimum(maximum, old+gamma_damage_increment(
        mean, float(mode_config['gamma_scale_damage']), rng))


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
    checkpoint_damage: Any = None
    mode_keys: tuple[str,...] = ()
    terminal_cycles: Any = None
    first_mode_crossings: Any = None


SystemFailure = Callable[[MultiModeDegradationState], tuple[bool, str]]


def monte_carlo_rul(initial_state: MultiModeDegradationState,
                    profile: MissionCycleProfile, config: D3Config,
                    *, sample_count: int | None = None,
                    random_seed: int | None = None,
                    maximum_cycles: int | None = None,
                    system_failure: SystemFailure | None = None,
                    stored_paths: int = 12, should_stop=lambda:False,
                    on_progress=lambda *_:None,record_all_states: bool=False) -> MonteCarloRULResult:
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
    checkpoints=None;terminals=None;crossings=None
    if record_all_states:
        required=(horizon+1)*n*len(keys)*8
        if required>512*1024*1024:
            raise ValueError('循环检查点记录预计超过512 MiB，请减少路径数或预测循环上限；未省略任何路径')
        checkpoints=np.full((horizon+1,n,len(keys)),np.nan)
        checkpoints[0]=[initial_state.modes[k].damage for k in keys]
        terminals=np.zeros(n,dtype=np.int32);crossings=np.full((n,len(keys)),-1,dtype=np.int32)
    for sample in range(n):
        if should_stop():
            raise InterruptedError('随机寿命分析已在路径安全检查点取消')
        if sample%8==0:
            on_progress(.8+.1*sample/n,f'随机寿命路径 {sample+1}/{n}')
        state = initial_state
        failure_cycle: int | None = None
        limiters: tuple[str, ...] = ()
        reason = ""
        for cycle in range(1, horizon + 1):
            if should_stop():
                raise InterruptedError('随机寿命分析已在循环安全检查点取消')
            updated = dict(state.modes)
            for key in keys:
                kind, _, mode = key.split(":")
                mode_cfg = config.mode(kind, mode)
                updated[key] = ComponentDamageState(
                    damage=float(gamma_advance(updated[key].damage, aggregate[key], mode_cfg, rng)),
                    exposure=updated[key].exposure + aggregate[key])
            state = MultiModeDegradationState(updated)
            if checkpoints is not None:
                checkpoints[cycle,sample]=[state.modes[k].damage for k in keys]
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
        if checkpoints is not None:
            terminals[sample]=cycle
            modes=[]
            if failure_cycle is not None:
                for j,key in enumerate(keys):
                    kind,_,mode=key.split(':')
                    if state.modes[key].damage+1e-15>=float(config.mode(kind,mode)['failure_damage']):
                        crossings[sample,j]=failure_cycle;modes.append(key)
            row.update(last_safe_checkpoint=(failure_cycle-1 if failure_cycle is not None else horizon),
                       first_exceedance_checkpoint=failure_cycle,
                       failure_mode_keys='|'.join(modes),detection_resolution='CYCLE_END_CHECKPOINT')

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
        runtime_s=time.perf_counter() - started,
        checkpoint_damage=(checkpoints[:int(terminals.max())+1].copy() if checkpoints is not None else None),
        mode_keys=keys if record_all_states else (),terminal_cycles=terminals,first_mode_crossings=crossings)
