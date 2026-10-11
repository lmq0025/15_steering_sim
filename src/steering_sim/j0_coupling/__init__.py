"""PHASE J0 joint-commissioning layer: control - L1-Fast hydraulics - M1 mechanics.

This package is an isolated adapter.  It does not modify the L1-Fast hydraulic
constitutive equations, the M1 closed-chain solver, the frozen CUSTOMER
geometry, or the existing PID controller.  It owns exactly four things:

* the ``x <-> q`` geometry mapping and its inverse,
* the road-load generalised moment evaluated on the ACTUAL ``q``,
* the virtual-work conversion of that moment into a hydraulic load force,
* the multi-rate closed-loop runner.
"""
from __future__ import annotations

from .config import ChannelControlConfig, J0Config, J0CaseConfig, load_j0_config
from .geometry import J0GeometryAdapter, J0MappingError, MappingStatus
from .road_load import RoadLoad, road_load
from .authority import ChannelAuthority, probe_channel_authority
from .runner import J0CaseResult, J0Runner, J0StopCondition

__all__ = [
    "ChannelAuthority", "ChannelControlConfig", "J0CaseConfig", "J0CaseResult",
    "J0Config", "J0GeometryAdapter", "J0MappingError", "J0Runner",
    "J0StopCondition", "MappingStatus", "RoadLoad", "load_j0_config",
    "probe_channel_authority", "road_load",
]
