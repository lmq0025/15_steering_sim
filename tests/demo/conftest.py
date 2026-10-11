"""PHASE J0-DEMO 测试夹具。

``DemoService`` 会重建 M1 的连续延拓查表（约 30 s），因此整个测试会话只建一次。
所有写盘产物都落在仓库内的 ``outputs/_demo_test_tmp``，不使用 ``tmp_path``
（本机禁止访问共享临时目录）。
"""
from __future__ import annotations

from pathlib import Path
import shutil

import pytest

ROOT = Path(__file__).parents[2]


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "slow: 需要真实积分较长时间的演示层检查")


@pytest.fixture(scope="session")
def demo_service():
    """**甲方原始机构**（AS_BUILT_REFERENCE）的服务层。

    PHASE M3 起默认模式改为优化设计机构，但 J0-DEMO/M2 的演示层测试锁的是
    原始机构的真实行为（含五、六桥左右反号这一缺陷），因此这里**显式**使用
    原始机构，绝不因为换了默认值就把这些缺陷测试删掉或改软。
    """
    from steering_sim.demo.service import DemoService
    output = ROOT / "outputs" / "_demo_test_tmp" / "service"
    if output.exists():
        shutil.rmtree(output, ignore_errors=True)
    return DemoService(output_dir=output, mechanical_mode="AS_BUILT_REFERENCE")


@pytest.fixture(scope="session")
def redesigned_service():
    """PHASE M3 优化设计机构的服务层（供新增测试使用）。"""
    from steering_sim.demo.service import DemoService
    output = ROOT / "outputs" / "_demo_test_tmp" / "service_redesigned"
    if output.exists():
        shutil.rmtree(output, ignore_errors=True)
    return DemoService(output_dir=output, mechanical_mode="REDESIGNED_ACKERMANN")


@pytest.fixture(scope="session")
def runner(demo_service):
    """复用服务层已经建好的被控对象，避免重复构建 M1 查表（约 30 s）。"""
    return demo_service.runner


@pytest.fixture(scope="session")
def m1_model(demo_service):
    return demo_service.runner.geometry.model


@pytest.fixture
def scratch_dir(request):
    path = (ROOT / "outputs" / "_demo_test_tmp"
            / request.node.name.replace("[", "_").replace("]", ""))
    if path.exists():
        shutil.rmtree(path, ignore_errors=True)
    path.mkdir(parents=True, exist_ok=True)
    return path
