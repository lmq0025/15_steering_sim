from __future__ import annotations

import math

import pytest

from steering_sim.hydraulics_lumped.actuator import actuator_rates, chamber_volumes
from steering_sim.hydraulics_lumped.parameters import (
    ActuatorParameters, FluidParameters, default_channels, default_sc1_valves)
from steering_sim.hydraulics_lumped.valve import (
    characteristic_orifice_flow, fractional_area_percent, sc1_four_port_flows)


def test_sc1_area_tables_are_independent_and_saturated():
    assert fractional_area_percent(.5, "ramp_minus_to_zero_then_full") == 100
    assert fractional_area_percent(.5, "full_to_zero_on_positive") == 50
    assert fractional_area_percent(.5, "open_on_positive") == 50
    assert fractional_area_percent(.5, "open_on_negative") == 0
    assert fractional_area_percent(-.5, "open_on_negative") == 50
    assert fractional_area_percent(2.0, "positive_linear") == 100


def test_sc1_variants_and_redundant_branch_sets_are_not_merged():
    valves = default_sc1_valves()
    assert [o.branch for o in valves["dirvalve_1"].orifices] == ["P-A", "P-B", "T-A", "T-B"]
    assert [o.branch for o in valves["dirvalve_2"].orifices] == ["P-A", "T-B"]
    curves_1 = {o.branch: o.curve for o in valves["dirvalve_1"].orifices}
    curves_6 = {o.branch: o.curve for o in valves["dirvalve_6"].orifices}
    assert curves_1 != curves_6


def test_hydvorf0_surrogate_allows_source_supported_reverse_flow():
    branch = default_sc1_valves()["dirvalve_1"].orifices[0]
    forward = characteristic_orifice_flow(2e6, 1e6, 1.0, branch)
    reverse = characteristic_orifice_flow(1e6, 2e6, 1.0, branch)
    assert forward > 0
    assert reverse == pytest.approx(-forward)


def test_sc1_four_port_conserves_external_flow():
    valve = default_sc1_valves()["dirvalve_1"]
    flow = sc1_four_port_flows(.9, .85e6, 2.6e6, 1.5e6, 1.1e6, valve)
    # P and T external flows balance the two work-port inflows.
    assert flow.q_a + flow.q_b == pytest.approx(flow.q_supply - flow.q_return)


def test_hj020_source_signs_and_volume_direction():
    actuator = ActuatorParameters(5e-3, 3.7e-3, 50e-6, 50e-6, .13)
    fluid = FluidParameters()
    v = -0.01
    qa, qb = -actuator.area_a * v, actuator.area_b * v
    rates = actuator_rates(1e6, 1e6, 0.0, v, qa, qb, 0.0, actuator, fluid)
    assert rates.dp_a == pytest.approx(0.0, abs=1e-6)
    assert rates.dp_b == pytest.approx(0.0, abs=1e-6)
    va0, vb0 = chamber_volumes(0.0, actuator)
    va, vb = chamber_volumes(-.01, actuator)
    assert va > va0 and vb < vb0


def test_r3_supply_parameters_distinguish_front_and_rear_nodes():
    front, rear = default_channels()[0], default_channels()[1]
    assert front.supply.path_resistance != rear.supply.path_resistance
    assert front.supply.return_path_resistance != rear.supply.return_path_resistance
    assert rear.supply.auxiliary_flow == pytest.approx(4.47 / 60_000.0)
    assert front.supply.auxiliary_flow == 0.0
    assert math.isclose(rear.supply.reducing_valve_margin, 1.10e6)
