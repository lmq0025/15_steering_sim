"""J0 minimum test set, items 7, 8, 12, 13: valve polarity, load conversion,
single application of the road load, and hydraulic sanity."""
from __future__ import annotations

import math

import numpy as np
import pytest

from steering_sim.hydraulics_lumped import HydraulicInput, evaluate_hydraulic
from steering_sim.j0_coupling.authority import (probe_channel_authority,
                                                steady_force, working_point)
from steering_sim.j0_coupling.diagnostics import (characterise_plant,
                                                  passive_closed_loop_estimate)
from steering_sim.j0_coupling.road_load import road_load, virtual_work_residual


def _road(adapter, j0_config, q_values, *, speed_kmh, target_deg):
    curvature = adapter.curvature_1pm(target_deg)
    return road_load(adapter, q_values, speed_kmh=speed_kmh,
                     friction_coefficient=float(j0_config.load["friction_coefficient"]),
                     axle_mass_t=tuple(j0_config.load["axle_mass_t"]),
                     curvature_1pm=curvature,
                     singular_threshold_m_per_rad=float(
                         j0_config.mapping["singular_jacobian_threshold_m_per_rad"]))


# --------------------------------------------------------------- item 7: valve
def test_measured_command_polarity_matches_the_configured_polarity(hydraulic, j0_config):
    """Item 7: each channel's small-perturbation command polarity is measured."""
    neutral = tuple(item.neutral_command for item in j0_config.channels)
    authorities = probe_channel_authority(hydraulic, neutral_commands=neutral)
    assert len(authorities) == 4
    for item, authority in zip(j0_config.channels, authorities):
        assert authority.channel == item.channel
        measured = math.copysign(1.0, authority.d_acceleration_over_d_command)
        assert measured == math.copysign(1.0, item.command_polarity), item.channel


def test_front_channel_polarity_differs_from_the_rear_family(hydraulic, j0_config):
    """The front SC_1 table family must be identified separately, not assumed."""
    neutral = tuple(item.neutral_command for item in j0_config.channels)
    authorities = probe_channel_authority(hydraulic, neutral_commands=neutral)
    assert authorities[0].channel == "channel_front"
    assert authorities[0].neutral_command == 1.0
    for authority in authorities[1:]:
        assert authority.neutral_command == 0.0


@pytest.mark.slow
def test_front_channel_has_no_bidirectional_static_force_authority(hydraulic, j0_config):
    """Measured plant limitation, pinned so a later hydraulic fix flips this test.

    ``LumpedHydraulicSystem`` hard-zeroes the front chamber-A valve flow
    (``model.py``: "SC_1 local A is an upstream circulation node"), so chamber A
    can only follow chamber B through leakage.  The reachable static force window
    is therefore of the order of tens of newtons and cannot hold a steering load.
    """
    neutral = tuple(item.neutral_command for item in j0_config.channels)
    window = [steady_force(hydraulic, 0, float(u), neutral, duration_s=0.2)
              for u in np.linspace(0.0, 1.0, 9)]
    assert max(window) < 200.0
    assert min(window) > -200.0


@pytest.mark.slow
def test_rear_channels_do_have_a_static_force_window(hydraulic, j0_config):
    neutral = tuple(item.neutral_command for item in j0_config.channels)
    window = [steady_force(hydraulic, 1, float(u), neutral, duration_s=0.5)
              for u in np.linspace(-1.0, 1.0, 9)]
    assert max(window) - min(window) > 5.0e3


# ------------------------------------------------- item 8: load conversion
def test_virtual_work_identity_holds(adapter, j0_config):
    """Item 8: F_load*xdot = Q_road*qdot to round-off."""
    geometry = adapter.target(2.0)
    q_values = dict(geometry.q_rad)
    road = _road(adapter, j0_config, q_values, speed_kmh=5.0, target_deg=2.0)
    for dof, jac in road.stroke_jacobian_m_per_rad.items():
        for q_dot in (-0.05, 0.0, 0.037):
            residual = virtual_work_residual(road, {dof: q_dot})[dof]
            scale = max(abs(road.generalized_road_moment_nm[dof] * q_dot),
                        abs(road.hydraulic_load_force_n[dof] * jac * q_dot), 1.0)
            assert abs(residual) / scale < 1.0e-12


def test_load_force_is_the_road_moment_over_the_stroke_jacobian(adapter, j0_config):
    geometry = adapter.target(5.0)
    road = _road(adapter, j0_config, geometry.q_rad, speed_kmh=10.0, target_deg=5.0)
    for dof, force in road.hydraulic_load_force_n.items():
        jac = road.stroke_jacobian_m_per_rad[dof]
        assert math.isclose(force, road.generalized_road_moment_nm[dof] / jac, rel_tol=1e-12)


def test_road_load_is_restoring_on_every_group(adapter, j0_config):
    """The road load must oppose the steering displacement, per group."""
    for target in (2.0, 5.0):
        geometry = adapter.target(target)
        road = _road(adapter, j0_config, geometry.q_rad, speed_kmh=5.0, target_deg=target)
        for item in j0_config.channels:
            dof = item.dof
            x = adapter.representative_stroke(dof, float(geometry.q_rad[dof]))
            force = road.hydraulic_load_force_n[dof]
            # F_load > 0 resists positive x, so a restoring load has the same
            # sign as x for every group of this mechanism.
            assert force * x > 0.0, (item.channel, x, force)


def test_zero_angle_produces_zero_road_load(adapter, j0_config):
    road = _road(adapter, j0_config, adapter.q_zero, speed_kmh=0.0, target_deg=0.0)
    for value in road.generalized_road_moment_nm.values():
        assert value == 0.0
    for value in road.hydraulic_load_force_n.values():
        assert value == 0.0


def test_straight_running_at_speed_still_has_no_road_load(adapter, j0_config):
    """At q = 0 every wheel sits at 0 deg, so the road moment is identically zero."""
    road = _road(adapter, j0_config, adapter.q_zero, speed_kmh=10.0, target_deg=0.0)
    assert road.lateral_acceleration_mps2 == 0.0
    for value in road.road_moment_nm.values():
        assert value == 0.0


def test_load_conversion_flags_a_singular_jacobian(adapter, j0_config):
    """A singular dx/dq must be reported, never turned into a finite-looking force."""
    table = adapter.tables["q4"]
    saved = table.stroke_derivative.copy()
    table.stroke_derivative[:] = 0.0
    try:
        road = _road(adapter, j0_config, adapter.target(2.0).q_rad,
                     speed_kmh=5.0, target_deg=2.0)
        assert "q4:LOAD_CONVERSION_SINGULAR" in road.flags
        assert math.isnan(road.hydraulic_load_force_n["q4"])
    finally:
        table.stroke_derivative[:] = saved


def test_road_load_matches_m1_generalised_moment_on_the_same_q(adapter, j0_config, m1_model):
    """Item 12: the J0 road load reproduces the M1 generalised moment, but the M1
    static compliance correction is deliberately NOT applied."""
    from mechanics_ackermann_v2.model import CaseInput

    target = 2.0
    geometry = adapter.target(target)
    road = _road(adapter, j0_config, geometry.q_rad, speed_kmh=5.0, target_deg=target)
    case = CaseInput(5.0, target, 0.75, tuple(j0_config.load["axle_mass_t"]))
    loaded = m1_model.solve_loaded_case(case, geometry)
    for dof in ("q_front", "q4", "q5", "q6"):
        reference = float(loaded.generalized_road_moment_Nm[dof])
        # Both use a table-gradient wheel-angle Jacobian, but on different grids,
        # so agreement is at the table-derivative level, not to round-off.
        assert abs(road.generalized_road_moment_nm[dof] - reference) / max(
            abs(reference), 1.0) < 1.0e-3, dof
    # And the compliance path really is absent from J0.
    assert not hasattr(road, "loaded_q_rad")


def test_compliance_correction_is_not_applied_in_the_runner(runner):
    """Item 12: the actuator coordinate is the inverse of x, not q - Q/K."""
    q, status = runner.geometry.q_from_strokes(
        {"channel_front": 0.0, "channel_rear_1": 0.0, "channel_rear_2": 0.0,
         "channel_rear_3": 0.0})
    assert all(item.ok for item in status.values())
    for value in q.values():
        assert value == 0.0


# ------------------------------------------------------ item 13: hydraulic sanity
def test_working_point_is_an_exact_equilibrium(hydraulic, j0_config):
    """Item 13: the pre-charged J0 initial state has a zero mechanical residual."""
    state, loads = working_point(hydraulic)
    neutral = tuple(item.neutral_command for item in j0_config.channels)
    speeds = tuple(c.pump.nominal_speed for c in hydraulic.channels)
    inputs = HydraulicInput(neutral, speeds, loads,
                            redundant_valve_commands=dict(
                                j0_config.hydraulic["redundant_valve_commands"]))
    dx, outputs = evaluate_hydraulic(hydraulic, 0.0, state, inputs)
    assert np.all(np.isfinite(dx))
    for index, channel in enumerate(outputs.channels):
        assert abs(dx[4 * index + 3]) < 1.0e-9, channel
    assert abs(dx[2]) < 1.0e-9


def test_pressures_stay_inside_the_regulated_envelope_at_the_working_point(hydraulic, j0_config):
    state, loads = working_point(hydraulic)
    neutral = tuple(item.neutral_command for item in j0_config.channels)
    speeds = tuple(c.pump.nominal_speed for c in hydraulic.channels)
    dx, outputs = evaluate_hydraulic(
        hydraulic, 0.0, state,
        HydraulicInput(neutral, speeds, loads,
                       redundant_valve_commands=dict(
                           j0_config.hydraulic["redundant_valve_commands"])))
    assert np.all(np.isfinite(dx))
    assert all(channel.pressure_a_pa_g > 0.0 for channel in outputs.channels)
    assert all(channel.pressure_b_pa_g > 0.0 for channel in outputs.channels)
    assert not any(outputs.pump_capacity_insufficient)
    assert all(margin >= 0.0 for margin in outputs.pump_capacity_margin_m3_s)


@pytest.mark.slow
def test_chamber_volumes_and_states_stay_finite_in_a_short_free_run(hydraulic, j0_config):
    """Item 13: a 20 ms free run produces finite states and no chamber-volume error."""
    state, loads = working_point(hydraulic)
    speeds = tuple(c.pump.nominal_speed for c in hydraulic.channels)
    from steering_sim.hydraulics_lumped.simulation import simulate_rk4
    commands = [0.0, 0.0, 0.0, 0.0]
    system_inputs = HydraulicInput(tuple(commands), speeds, loads).to_system_inputs()
    times, states = simulate_rk4(hydraulic, 0.02, 5.0e-4,
                                 lambda _t: system_inputs, state)
    assert np.all(np.isfinite(states))
    assert np.max(np.abs(states[:, 2])) < 1.0e-3


@pytest.mark.slow
def test_delivered_plant_has_negative_hydraulic_damping_and_stiffness(hydraulic, j0_config):
    """Pinned plant finding behind the J0 CONDITIONAL/FAIL status.

    A passive actuator must return dF/dv < 0 and dF/dx < 0.  The delivered
    L1-Fast V1 actuator returns both positive, so the open loop injects energy
    and no positive mechanical stiffness can stabilise it.  When the actuator
    sign convention is corrected this test must be updated.
    """
    neutral = tuple(item.neutral_command for item in j0_config.channels)
    plant = characterise_plant(hydraulic, neutral_commands=neutral, force_samples=5)
    for item in plant:
        assert item.d_force_d_velocity_n_s_per_m > 0.0, item.channel
        assert item.d_force_d_displacement_n_per_m > 0.0, item.channel
        estimate = passive_closed_loop_estimate(
            item.d_force_d_velocity_n_s_per_m, item.d_force_d_displacement_n_per_m,
            road_stiffness_n_per_m=0.0)
        assert estimate["max_real_part_1_per_s"] > 0.0


def test_redundant_valves_are_written_explicitly(j0_config):
    """Item 13: the redundant commands are configured, never left implicit."""
    assert set(j0_config.hydraulic["redundant_valve_commands"]) == {
        "dirvalve_2", "dirvalve_9", "dirvalve_12"}
