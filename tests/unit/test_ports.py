import pytest

from steering_sim.core.ports import HydraulicPowerPort, RotationalPowerPort, TranslationalPowerPort


@pytest.mark.parametrize(
    ("port", "expected"),
    [
        (HydraulicPowerPort(pressure=2.0e6, flow=3.0e-4), 600.0),
        (TranslationalPowerPort(force=1200.0, velocity=-0.25), -300.0),
        (RotationalPowerPort(torque=40.0, angular_velocity=5.0), 200.0),
    ],
)
def test_instantaneous_power(port, expected: float) -> None:
    assert port.power == pytest.approx(expected)

