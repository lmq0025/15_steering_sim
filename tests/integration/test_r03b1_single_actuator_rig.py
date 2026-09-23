from pathlib import Path

import numpy as np
import pytest

from steering_sim.hydraulics.r03b1_errors import UnresolvedAmesimUtilityError
from steering_sim.hydraulics.r03b1_factory import build_r03b1_rig
from steering_sim.hydraulics.single_actuator_rig import PrescribedBoundary

ROOT = Path(__file__).resolve().parents[2]


def test_single_actuator_rig_has_two_pressure_states_and_fails_closed():
    rig = build_r03b1_rig(ROOT / "configs" / "hydraulics" / "r03b1")
    assert rig.state_names == ("p1_pa", "p2_pa")
    boundary = PrescribedBoundary(0.5, 10e6, 0.0, 0.05, 0.0)
    with pytest.raises(UnresolvedAmesimUtilityError, match="orif3f"):
        rig.rhs(0.0, np.array([0.0, 0.0]), boundary)

