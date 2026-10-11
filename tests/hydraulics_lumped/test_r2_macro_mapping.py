import pytest

from steering_sim.hydraulics_lumped import LumpedHydraulicSystem, SystemInputs


def _base(model, **kwargs):
    return SystemInputs(
        # Installed SC_1 primary wrappers use x=1 as the healthy neutral
        # coordinate in the captured S0/S1/S2 cases; redundant wrappers are
        # independently set through the alias interface when required.
        [1.0] * 4,
        [c.pump.nominal_speed for c in model.channels],
        [0.0] * 4,
        **kwargs,
    )


def test_per_pump_independent_speed_and_shutdown():
    model = LumpedHydraulicSystem()
    nominal = model.channels[0].pump.nominal_speed
    x = model.initial_state()
    _, both = model.evaluate(0.0, x, _base(model, pump_speeds_by_alias={
        "pump01": nominal, "pump01_1": nominal}))
    _, one = model.evaluate(0.0, x, _base(model, pump_speeds_by_alias={
        "pump01": nominal, "pump01_1": 0.0}))
    _, split = model.evaluate(0.0, x, _base(model, pump_speeds_by_alias={
        "pump01": nominal, "pump01_1": nominal / 2.0}))
    assert one[0]["group_pump_flow"] == pytest.approx(both[0]["group_pump_flow"] / 2)
    assert split[0]["group_pump_flow"] == pytest.approx(both[0]["group_pump_flow"] * .75)


def test_redundant_valves_have_independent_commands():
    model = LumpedHydraulicSystem()
    x = model.initial_state()
    nominal = model.channels[0].pump.nominal_speed
    speeds = {a: nominal for c in model.channels for a in c.pump_aliases}
    commands = {"dirvalve_1": 1.0, "dirvalve_2": 0.0}
    _, first = model.evaluate(0.0, x, _base(model, pump_speeds_by_alias=speeds,
        valve_commands_by_alias=commands))
    commands["dirvalve_2"] = .02
    _, second = model.evaluate(0.0, x, _base(model, pump_speeds_by_alias=speeds,
        valve_commands_by_alias=commands))
    # The redundant P-A/T-B pair is evaluated separately: changing only it
    # changes the aggregate port flows while the primary command is fixed.
    assert (second[1]["QA"], second[1]["QB"]) != pytest.approx(
        (first[1]["QA"], first[1]["QB"]))
    assert first[1]["valve_branch_count"] == 2


def test_shared_supply_conservation_and_solver_status():
    model = LumpedHydraulicSystem()
    _, outputs = model.evaluate(0.0, model.initial_state(), _base(model))
    for output in outputs:
        assert abs(output["supply_balance_residual"]) <= 1e-9
        assert output["supply_balance_relative_residual"] <= 1e-6
        assert output["pump_outlet_pressure"] == output["supply_pressure"]
        assert output["pump_outlet_pressure"] > output["manifold_pressure"]
        assert abs(output["return_absorbed_flow"]) <= 1e-9


def test_legacy_group_input_remains_compatible_when_pumps_same_speed():
    model = LumpedHydraulicSystem()
    speeds = [c.pump.nominal_speed for c in model.channels]
    old = SystemInputs([0.0] * 4, speeds, [0.0] * 4)
    per_pump = SystemInputs([0.0] * 4, speeds, [0.0] * 4,
        pump_speeds_by_alias={a: speeds[i] for i, c in enumerate(model.channels) for a in c.pump_aliases})
    _, a = model.evaluate(0.0, model.initial_state(), old)
    _, b = model.evaluate(0.0, model.initial_state(), per_pump)
    assert [o["group_pump_flow"] for o in a] == pytest.approx(
        [o["group_pump_flow"] for o in b])
