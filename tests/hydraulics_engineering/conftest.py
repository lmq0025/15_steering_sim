"""PHASE J1-R2 工程液压测试的 marker 注册。"""
from __future__ import annotations


def pytest_configure(config):
    config.addinivalue_line("markers", "slow: 需要真实积分较长时间的检查")
