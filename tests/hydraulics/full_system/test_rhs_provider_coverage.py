from pathlib import Path

import numpy as np

from steering_sim.hydraulics.assembly import FullHydraulicModel


ROOT = Path(__file__).resolve().parents[3]


def test_every_fast_state_owner_has_rhs_provider():
    model = FullHydraulicModel.from_ir(ROOT / "hydraulic_audit")
    owners = {element.instance_alias: element for element in model.system.elements}
    assert all(owners[state.instance].rhs_provider for state in model.system.states)


def test_rhs_interface_has_stable_shape_and_accepts_compiled_overrides():
    model = FullHydraulicModel.from_ir(ROOT / "hydraulic_audit")
    x = np.zeros(len(model.system.states))
    first = model.system.states[0]
    key = f"{first.instance}.{first.state_name}"
    result = model.rhs(0.0, x, {"state_rhs": {key: 3.0}})
    assert result.shape == x.shape
    assert result[first.index] == 3.0
