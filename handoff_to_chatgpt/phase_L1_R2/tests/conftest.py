import pytest

from steering_sim.hydraulics_lumped import LumpedHydraulicSystem, SystemInputs


@pytest.fixture
def model():
    return LumpedHydraulicSystem()


@pytest.fixture
def neutral(model):
    return SystemInputs([0.0]*4, [c.pump.nominal_speed for c in model.channels], [0.0]*4)
