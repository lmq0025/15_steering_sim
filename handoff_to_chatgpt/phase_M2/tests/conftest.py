"""PHASE M2 测试夹具。M1 模型构建较慢（约 30 s），整个会话只建一次。"""
from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).parents[2]
SPEC = ROOT / "mechanical_model_input_spec_v1.0.yaml"
M1_CONFIG = ROOT / "mechanics_ackermann_v2" / "config.json"


def pytest_configure(config):
    config.addinivalue_line("markers", "slow: 需要构建 M1 查表或跑批的 M2 检查")


@pytest.fixture(scope="session")
def reference():
    from steering_sim.mechanics import reference_geometry_from_file
    return reference_geometry_from_file(SPEC)


@pytest.fixture(scope="session")
def centers(reference):
    return {f"axle{a}_{s}": tuple(map(float, reference.bodies[f"WHEEL_{a}_{l}"].pivot))
            for a in range(1, 7)
            for s, l in (("left", "POS_Y"), ("right", "NEG_Y"))}


@pytest.fixture(scope="session")
def m1():
    from mechanics_ackermann_v2.model import PhaseM1Model
    return PhaseM1Model(SPEC, M1_CONFIG)


@pytest.fixture(scope="session")
def four_bars(reference):
    from steering_sim.ackermann.linkage import build_four_bars
    return build_four_bars(reference)


@pytest.fixture(scope="session")
def equivalent(reference, four_bars):
    from steering_sim.ackermann.equivalent import build_equivalent_map
    return build_equivalent_map(reference, four_bars,
                                need={"channel_rear_2": True, "channel_rear_3": True})


@pytest.fixture
def scratch_dir(request):
    """可写的每测试目录（本机禁止访问共享临时目录，故不用 tmp_path）。"""
    import shutil
    path = ROOT / "outputs" / "_m2_test_tmp" / request.node.name.replace("[", "_").replace("]", "")
    if path.exists():
        shutil.rmtree(path, ignore_errors=True)
    path.mkdir(parents=True, exist_ok=True)
    return path
