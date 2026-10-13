"""PHASE D1：任务谱驱动的部件级确定性退化预测。"""

from .damage import (ComponentDamageState, DegradationModelConfig,
                     DegradationState, load_degradation_config)
from .prediction import (D1Prediction, D1Predictor, checkpoint_states,
                         state_from_record)
from .spectrum import (SpectrumError, TaskSegment, TaskSpectrum,
                       load_task_spectrum)
from .multimode import (D3Config, MultiModeDegradationState,
                        component_mode_rows, load_d3_config,
                        mode_key, parameters_from_multimode)
from .rainflow import (RainflowCycle, count_rainflow, equivalent_cycle_load,
                       rainflow_matrix, turning_points)
from .rul import (MissionCycleProfile, RULPrediction,
                  RepeatedMissionRULPredictor, build_cycle_profile)
from .stochastic import (MonteCarloRULResult, gamma_damage_increment,
                         monte_carlo_rul)

__all__ = [
    "ComponentDamageState", "D1Prediction", "D1Predictor",
    "DegradationModelConfig", "DegradationState", "SpectrumError",
    "TaskSegment", "TaskSpectrum", "checkpoint_states",
    "load_degradation_config", "load_task_spectrum", "state_from_record",
    "D3Config", "MultiModeDegradationState", "component_mode_rows",
    "load_d3_config", "mode_key", "parameters_from_multimode",
    "RainflowCycle", "count_rainflow", "equivalent_cycle_load",
    "rainflow_matrix", "turning_points", "MissionCycleProfile",
    "RULPrediction", "RepeatedMissionRULPredictor", "build_cycle_profile",
    "MonteCarloRULResult", "gamma_damage_increment", "monte_carlo_rul",
]
