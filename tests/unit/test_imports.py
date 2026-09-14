import steering_sim
from steering_sim import control, core, coupling, hydraulics, io, mechanics, solvers


def test_public_packages_import() -> None:
    assert steering_sim.__version__ == "0.1.0"
    assert all(module is not None for module in (control, core, coupling, hydraulics, io, mechanics, solvers))

