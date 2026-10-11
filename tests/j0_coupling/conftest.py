"""Session-scoped fixtures for the PHASE J0 coupling tests.

Building ``PhaseM1Model`` rebuilds the M1 continuation lookups (~15 s) and the
J0 adapter adds its own tables, so both are shared across the whole module.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from mechanics_ackermann_v2.model import PhaseM1Model
from steering_sim.hydraulics_lumped import LumpedHydraulicSystem
from steering_sim.j0_coupling.config import load_j0_config
from steering_sim.j0_coupling.geometry import J0GeometryAdapter
from steering_sim.j0_coupling.runner import J0Runner


def pytest_configure(config):
    """Register the local ``slow`` marker without touching the shared pyproject."""
    config.addinivalue_line(
        "markers", "slow: J0 checks that run longer hydraulic/mechanical simulations")


ROOT = Path(__file__).parents[2]
SPEC = ROOT / "mechanical_model_input_spec_v1.0.yaml"
M1_CONFIG = ROOT / "mechanics_ackermann_v2" / "config.json"
J0_CONFIG = ROOT / "configs" / "j0" / "j0_config.json"


@pytest.fixture(scope="session")
def j0_config():
    return load_j0_config(J0_CONFIG)


@pytest.fixture(scope="session")
def m1_model():
    return PhaseM1Model(SPEC, M1_CONFIG)


@pytest.fixture(scope="session")
def adapter(m1_model, j0_config):
    return J0GeometryAdapter(m1_model, j0_config)


@pytest.fixture(scope="session")
def hydraulic():
    return LumpedHydraulicSystem.fast_engineering()


@pytest.fixture(scope="session")
def runner(j0_config, m1_model):
    return J0Runner(j0_config, m1_model)


@pytest.fixture
def scratch_dir(request):
    """Writable per-test directory.

    The pytest ``tmp_path`` fixture cannot be used here: this machine denies
    access to the shared ``%TEMP%/pytest-of-<user>`` directory, the same
    restriction that stops pytest creating ``.pytest_cache``.
    """
    path = ROOT / "outputs" / "_j0_test_tmp" / request.node.name.replace("[", "_").replace("]", "")
    if path.exists():
        import shutil
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)
    return path
