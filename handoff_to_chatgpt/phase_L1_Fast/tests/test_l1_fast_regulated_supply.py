from __future__ import annotations

import math

import numpy as np

from steering_sim.hydraulics_lumped import (
    HydraulicInput, LumpedHydraulicSystem, SUPPLY_MODE, SystemInputs,
    evaluate_hydraulic)
from steering_sim.hydraulics_lumped.simulation import simulate_rk4


def working_point(model: LumpedHydraulicSystem):
    state = np.zeros(16)
    loads = []
    for i, channel in enumerate(model.channels):
        pressure = channel.supply.regulated_return_rail_pressure
        state[4*i:4*i+4] = (pressure, pressure, 0.0, 0.0)
        loads.append(channel.actuator.area_a * pressure -
                     channel.actuator.area_b * pressure)
    return state, tuple(loads)


def inputs(model, loads, command=0.0, prescribed=False):
    primary = (1.0, command, 0.0, 0.0)
    valve_map = dict(zip(
        ("dirvalve_6", "dirvalve_1", "dirvalve_8", "dirvalve_11"), primary))
    valve_map.update({"dirvalve_2": 0.0, "dirvalve_9": 0.0,
                      "dirvalve_12": 0.0})
    motion = ({c.actuator_alias: (0.0, 0.0, 0.0) for c in model.channels}
              if prescribed else None)
    speeds = tuple(c.pump.nominal_speed for c in model.channels)
    return SystemInputs(primary, speeds, loads, valve_commands_by_alias=valve_map,
                        prescribed_motion_by_alias=motion)


def test_fast_factory_selects_regulated_mode_and_keeps_state_count():
    model = LumpedHydraulicSystem.fast_engineering()
    assert SUPPLY_MODE == "regulated_constant_pressure"
    assert model.supply_mode == SUPPLY_MODE
    assert model.state_count == 16


def test_regulated_mode_has_no_inner_iterations_and_distinct_group_pressures():
    model = LumpedHydraulicSystem.fast_engineering()
    state, loads = working_point(model)
    dx, outputs = model.evaluate(0.0, state, inputs(model, loads, prescribed=True))
    assert np.isfinite(dx).all()
    assert outputs[0]["supply_solver_iterations"] == 0.0
    assert outputs[1]["supply_solver_iterations"] == 0.0
    assert outputs[0]["pump_outlet_pressure"] != outputs[1]["pump_outlet_pressure"]
    assert outputs[0]["valve_high_rail_pressure"] != outputs[0]["pump_outlet_pressure"]


def test_nominal_middle_is_exact_equilibrium_without_drift():
    model = LumpedHydraulicSystem.fast_engineering()
    state, loads = working_point(model)
    constant = inputs(model, loads)
    assert np.array_equal(model.rhs(0.0, state, constant), np.zeros(16))
    _, history = simulate_rk4(model, 0.1, 0.002, lambda _t: constant, state)
    assert np.array_equal(history[-1], state)


def test_pump_capacity_shortfall_is_reported_not_hidden():
    model = LumpedHydraulicSystem.fast_engineering()
    state, loads = working_point(model)
    command = inputs(model, loads, command=0.5, prescribed=True)
    command = SystemInputs(command.valve_commands, (0.0,)*4, command.load_forces,
                           pump_speeds_by_alias={a: 0.0 for a in
                               ("pump01", "pump01_1", "pump01_2", "pump01_3")},
                           valve_commands_by_alias=command.valve_commands_by_alias,
                           prescribed_motion_by_alias=command.prescribed_motion_by_alias)
    _, outputs = model.evaluate(0.0, state, command)
    assert outputs[1]["pump_capacity_insufficient"] == 1.0
    assert outputs[1]["pump_capacity_margin"] < 0.0


def test_hydraulic_io_contract_is_si_and_preserves_redundant_commands():
    model = LumpedHydraulicSystem.fast_engineering()
    state, loads = working_point(model)
    speeds = tuple(c.pump.nominal_speed for c in model.channels)
    command = HydraulicInput((1.0, 0.0, 0.0, 0.0), speeds, loads,
                             redundant_valve_commands={"dirvalve_2": 0.1})
    dx, output = evaluate_hydraulic(model, 0.0, state, command)
    assert dx.shape == (16,)
    assert len(output.channels) == 4
    assert len(output.supply_pressures_pa_g) == 2
    assert command.to_system_inputs().valve_commands_by_alias["dirvalve_2"] == 0.1


def test_small_autonomous_step_has_expected_initial_motion_direction():
    model = LumpedHydraulicSystem.fast_engineering()
    state, loads = working_point(model)
    step = inputs(model, loads, command=0.001)
    _, history = simulate_rk4(model, 0.05, 0.0005, lambda _t: step, state)
    assert np.isfinite(history).all()
    assert history[-1, 6] > 0.0
    assert history[-1, 7] > 0.0


def test_one_millisecond_step_meets_one_percent_gate_and_two_does_not():
    model = LumpedHydraulicSystem.fast_engineering()
    state, loads = working_point(model)
    # The accepted L1-Fast hydraulic comparison mode uses a prescribed
    # mechanical boundary until the real steering mechanics is connected.
    step = inputs(model, loads, command=0.001, prescribed=True)
    _, fine = simulate_rk4(LumpedHydraulicSystem.fast_engineering(), 0.05, 0.0005,
                           lambda _t: step, state)
    _, accepted = simulate_rk4(LumpedHydraulicSystem.fast_engineering(), 0.05, 0.001,
                               lambda _t: step, state)
    _, two_ms = simulate_rk4(LumpedHydraulicSystem.fast_engineering(), 0.05, 0.002,
                             lambda _t: step, state)
    scale = np.maximum(np.max(np.abs(fine), axis=0), 1.0)
    assert np.max(np.abs(accepted[-1] - fine[-1]) / scale) < 0.01
    assert np.max(np.abs(two_ms[-1] - fine[-1]) / scale) > 0.01


def test_one_hertz_prescribed_motion_is_finite_at_two_milliseconds():
    model = LumpedHydraulicSystem.fast_engineering()
    state, loads = working_point(model)

    def sine(t):
        command = 0.01 * math.sin(2.0 * math.pi * t)
        base = inputs(model, loads, command=command, prescribed=True)
        motion = dict(base.prescribed_motion_by_alias or {})
        x = 1.0e-4 * math.sin(2.0 * math.pi * t)
        v = 2.0 * math.pi * 1.0e-4 * math.cos(2.0 * math.pi * t)
        a = -(2.0 * math.pi)**2 * x
        motion["actuator001"] = (x, v, a)
        return SystemInputs(base.valve_commands, base.pump_speeds, base.load_forces,
                            valve_commands_by_alias=base.valve_commands_by_alias,
                            prescribed_motion_by_alias=motion)

    _, history = simulate_rk4(model, 1.0, 0.002, sine, state)
    assert np.isfinite(history).all()
    assert np.max(np.abs(history[:, [4, 5]])) < 100e6
