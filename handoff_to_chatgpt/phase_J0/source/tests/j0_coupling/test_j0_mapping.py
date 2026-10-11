"""J0 minimum test set, items 1-6: geometry mapping and closed-chain integrity."""
from __future__ import annotations

import math

import numpy as np
import pytest

from steering_sim.j0_coupling.geometry import (DOF_WHEELS, J0MappingError,
                                               WHEEL_ORDER)

TARGETS = (0.0, 1.0, -1.0, 2.0, -2.0, 3.5, -3.5, 5.0, -5.0)


def test_zero_position_is_the_reference_configuration(adapter):
    """Item 1: q = 0 gives zero strokes, zero wheel angles and a closed chain."""
    linkage = adapter.exact_linkage(adapter.q_zero)
    assert linkage.max_link_residual_m <= 1.0e-9
    for name, stroke in linkage.cylinder_stroke_m.items():
        assert abs(stroke) < 1.0e-12, name
    for wheel, angle in linkage.wheel_angle_deg.items():
        assert abs(angle) < 1.0e-12, wheel
    strokes = adapter.seven_cylinder_strokes(adapter.q_zero)
    assert len(strokes) == 7
    assert all(abs(value) < 1.0e-15 for value in strokes.values())


@pytest.mark.parametrize("target", TARGETS)
def test_stroke_to_q_round_trip(adapter, target):
    """Item 1: the representative-stroke inverse round trips exactly."""
    geometry = adapter.target(target)
    for channel, dof in (("channel_front", "q_front"), ("channel_rear_1", "q4"),
                         ("channel_rear_2", "q5"), ("channel_rear_3", "q6")):
        q_value = float(geometry.q_rad[dof])
        x = adapter.representative_stroke(dof, q_value)
        recovered, status = adapter.q_from_stroke(dof, x)
        assert status.ok, (channel, status.label)
        assert abs(recovered - q_value) < 1.0e-12, channel


@pytest.mark.parametrize("target", TARGETS)
def test_seven_cylinder_strokes_match_m1(adapter, target):
    """Item 2: q -> seven cylinder strokes agrees with the M1 output.

    The M1 number comes from the exact closed-chain solve while the J0 number
    comes from the 1e-3 rad interpolation table used inside every RK4 stage, so
    the agreement is limited by the table interpolation error (measured below
    20 nm on a multi-millimetre stroke).
    """
    geometry = adapter.target(target)
    mine = adapter.seven_cylinder_strokes(geometry.q_rad)
    for name, value in geometry.cylinder_displacement_mm.items():
        assert abs(mine[name] - value * 1.0e-3) < 1.0e-7, name


@pytest.mark.parametrize("target", TARGETS)
def test_companion_cylinder_is_not_an_independent_state(adapter, target):
    """Item 3: the B cylinder always comes from the same q as the representative."""
    geometry = adapter.target(target)
    q_value = float(geometry.q_rad["q4"])
    assert abs(adapter.companion_stroke("q4", q_value)
               - adapter.seven_cylinder_strokes(geometry.q_rad)["axle4_B"]) == 0.0
    # A second call with the same q must return exactly the same value: there is
    # no hidden second coordinate to drift.
    assert adapter.companion_stroke("q4", q_value) == adapter.companion_stroke("q4", q_value)
    # And it agrees with the exact closed chain to the table interpolation error.
    linkage = adapter.exact_linkage(geometry.q_rad)
    assert abs(adapter.companion_stroke("q4", q_value)
               - linkage.cylinder_stroke_m["axle4_B"]) < 1.0e-7


def test_front_group_shares_one_coordinate_and_axle2_follows(adapter):
    """Item 4: axles 1 and 2 share q_front and axle 2 has no independent command."""
    q = dict(adapter.q_zero)
    q["q_front"] = 0.05
    angles = adapter.wheel_angles_deg(q)
    assert abs(angles["axle2_left"]) > 1.0e-3
    assert set(DOF_WHEELS["q_front"]) == {"axle1_left", "axle1_right",
                                          "axle2_left", "axle2_right"}
    # Moving any other coordinate must not change the axle-1/axle-2 angles.
    q2 = dict(q)
    q2["q4"] = 0.05
    angles2 = adapter.wheel_angles_deg(q2)
    for wheel in DOF_WHEELS["q_front"]:
        assert angles2[wheel] == angles[wheel]


def test_third_axle_is_locked_everywhere(adapter):
    """Item 5: axle 3 is exactly 0 degrees for every reachable configuration."""
    for value in np.linspace(-0.5, 0.5, 11):
        q = dict(adapter.q_zero)
        q["q_front"] = float(value)
        q["q4"] = float(value) * 0.5
        q["q5"] = float(value) * 0.2
        q["q6"] = float(value) * 0.15
        angles = adapter.wheel_angles_deg(q)
        assert angles["axle3_left"] == 0.0
        assert angles["axle3_right"] == 0.0
        linkage = adapter.exact_linkage(q)
        assert linkage.third_axle_max_abs_deg == 0.0


def test_closed_chain_residual_and_hardpoints(adapter):
    """Item 6: link residual <= 1e-9 m at every J0 operating configuration."""
    for target in TARGETS:
        geometry = adapter.target(target)
        linkage = adapter.exact_linkage(geometry.q_rad)
        assert linkage.max_link_residual_m <= 1.0e-9
        assert not linkage.singular
        assert linkage.condition_number < 1.0e6


def test_hardpoints_are_frozen(m1_model, adapter):
    """Item 6: the adapter never moves a CUSTOMER hardpoint."""
    before = {name: np.array(point.position) for name, point in m1_model.reference.points.items()}
    adapter.exact_linkage(adapter.target(5.0).q_rad)
    for name, position in before.items():
        assert np.array_equal(position, m1_model.reference.points[name].position), name


def test_representative_stroke_jacobian_matches_the_exact_solver(adapter):
    """The table Jacobian used for the load conversion is validated against the solver."""
    from steering_sim.mechanics import SixAxleSteeringKinematics

    solver = SixAxleSteeringKinematics(adapter.reference)
    order = SixAxleSteeringKinematics.actuator_order
    columns = {"q_front": 0, "q4": 2, "q5": 3, "q6": 4}
    for target in (2.0, 5.0, -5.0):
        q = adapter.target(target).q_rad
        legacy = np.zeros(5)
        for dof, column in columns.items():
            legacy[column] = float(q[dof])
        solution = solver.solve(legacy)
        for dof, axle in (("q4", 4), ("q5", 5), ("q6", 6)):
            exact = float(solution.actuator_jacobian[
                order.index(f"ACTUATOR_{axle}_A"), columns[dof]])
            table = adapter.stroke_jacobian(dof, float(q[dof]))
            assert abs(table - exact) / abs(exact) < 1.0e-5, dof


def test_mapping_rejects_an_out_of_envelope_stroke(adapter):
    """Out-of-envelope requests are flagged, never silently clipped.

    ``dx/dq`` is negative for the q5 and q6 groups, so the requested stroke is
    bounded by ``stroke(q_min)`` and ``stroke(q_max)`` in whichever order they
    fall; the boundary coordinate returned must be the matching envelope end.
    """
    for dof in ("q4", "q6"):
        table = adapter.tables[dof]
        low, high = sorted((table.stroke(table.q_min), table.stroke(table.q_max)))
        high_end = table.q_min if table.stroke(table.q_min) > table.stroke(table.q_max) \
            else table.q_max
        low_end = table.q_max if high_end == table.q_min else table.q_min
        above, status = adapter.q_from_stroke(dof, high + 1.0)
        assert not status.ok and "MAPPING_OUT_OF_ENVELOPE" in status.flags
        assert abs(above - high_end) < 1.0e-12, dof
        below, status = adapter.q_from_stroke(dof, low - 1.0)
        assert not status.ok and "MAPPING_OUT_OF_ENVELOPE" in status.flags
        assert abs(below - low_end) < 1.0e-12, dof


def test_mapping_singularity_is_detected(adapter, j0_config):
    """A flat representative-stroke branch must be reported as MAPPING_SINGULAR."""
    table = adapter.tables["q4"]
    threshold = float(j0_config.mapping["singular_jacobian_threshold_m_per_rad"])
    assert np.min(np.abs(table.stroke_derivative)) > threshold
    # Force a flat branch and confirm the guard fires rather than returning a q.
    table.stroke_derivative[:] = 0.0
    try:
        _, status = adapter.q_from_stroke("q4", 0.0)
        assert not status.ok and "MAPPING_SINGULAR" in status.flags
    finally:
        table.stroke_derivative[:] = np.gradient(table.stroke_repr, table.q)


def test_channel_to_dof_mapping_is_the_declared_one(j0_config):
    """The four-channel to four-dof mapping is the ASSUMED J0 mapping, by name."""
    expected = {"channel_front": "q_front", "channel_rear_1": "q4",
                "channel_rear_2": "q5", "channel_rear_3": "q6"}
    for item in j0_config.channels:
        assert expected[item.channel] == item.dof
        assert item.mapping_status == "ASSUMED"


def test_front_stroke_placeholder_is_declared_assumed(adapter, j0_config):
    assert j0_config.mapping["front_stroke_per_q_m_per_rad"] == 0.25
    assert "ASSUMED" in j0_config.mapping["front_stroke_source"]
    assert math.isclose(adapter.representative_stroke("q_front", 0.04), 0.01, rel_tol=1e-12)


def test_all_twelve_wheels_are_produced(adapter):
    geometry = adapter.target(2.0)
    linkage = adapter.exact_linkage(geometry.q_rad)
    assert set(linkage.wheel_angle_deg) == set(WHEEL_ORDER)
    assert len(WHEEL_ORDER) == 12


def test_mirror_symmetry_between_plus_and_minus_two_degrees(adapter):
    """Item 10: the +-2 deg configurations mirror each other exactly."""
    plus = adapter.target(2.0)
    minus = adapter.target(-2.0)
    for dof in ("q_front", "q4", "q5", "q6"):
        assert math.isclose(float(plus.q_rad[dof]), -float(minus.q_rad[dof]), abs_tol=1.0e-9)
    angles_plus = adapter.wheel_angles_deg(plus.q_rad)
    angles_minus = adapter.wheel_angles_deg(minus.q_rad)
    for wheel in WHEEL_ORDER:
        other = wheel.replace("_left", "_right") if wheel.endswith("_left") \
            else wheel.replace("_right", "_left")
        assert math.isclose(angles_plus[wheel], -angles_minus[other], abs_tol=1.0e-9)


def test_straight_ahead_has_no_spurious_wheel_angle(adapter):
    """Item 10: 0 deg produces exactly zero on all twelve wheels."""
    geometry = adapter.target(0.0)
    angles = adapter.wheel_angles_deg(geometry.q_rad)
    assert all(abs(value) < 1.0e-12 for value in angles.values())


def test_wheel_angles_come_from_x_not_from_the_target(adapter):
    """Item 11: changing the hydraulic stroke changes the wheel angle."""
    q_zero = dict(adapter.q_zero)
    q_zero["q4"] = 0.02
    moved = adapter.wheel_angles_deg(q_zero)["axle4_left"]
    assert abs(moved) > 1.0e-3
    # The target angle is never consulted by the wheel-angle path: an arbitrary
    # q that is not any target's q still produces a well-defined angle.
    assert adapter.wheel_angles_deg(adapter.q_zero)["axle4_left"] == 0.0


def test_mapping_error_type_is_exported():
    assert issubclass(J0MappingError, RuntimeError)
