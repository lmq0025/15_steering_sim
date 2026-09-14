import pytest

from steering_sim.core.parameters import ParameterMeta, ParameterSet, ParameterSource
from steering_sim.io import parameter_records


def test_parameter_metadata_and_runtime_update() -> None:
    original = ParameterMeta("bulk_modulus", 1.4e9, "Pa", ParameterSource.DATASHEET, 0.8, "25 C")
    parameters = ParameterSet([original])
    degraded = original.with_value(1.2e9, notes="runtime degradation input")
    parameters.update(degraded)
    assert parameters["bulk_modulus"].value == 1.2e9
    assert parameter_records(parameters)[0]["source"] == "DATASHEET"


def test_parameter_confidence_is_bounded() -> None:
    with pytest.raises(ValueError):
        ParameterMeta("bad", 1.0, "-", ParameterSource.ASSUMED, 1.1)

