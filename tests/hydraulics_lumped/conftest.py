import pytest

from steering_sim.hydraulics_lumped import LumpedHydraulicSystem, SystemInputs


@pytest.fixture
def model():
    return LumpedHydraulicSystem()


@pytest.fixture
def neutral(model):
    # The installed SC_1 coordinate is x=1 for the captured healthy baseline,
    # not x=0.  R3 hydraulic-only tests prescribe the mechanical boundary.
    motion = {c.actuator_alias: (0.0, 0.0, 0.0) for c in model.channels}
    return SystemInputs([1.0]*4, [c.pump.nominal_speed for c in model.channels],
                        [0.0]*4, prescribed_motion_by_alias=motion)
