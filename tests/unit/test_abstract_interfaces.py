from collections.abc import Mapping

import numpy as np

from steering_sim.control import Command, Controller, Measurement, Reference
from steering_sim.core.parameters import ParameterMeta
from steering_sim.core.ports import HydraulicPowerPort, TranslationalPowerPort
from steering_sim.hydraulics import HydraulicInputs, HydraulicModel, HydraulicOutputs, HydraulicState
from steering_sim.mechanics import MechanicalDerivative, MechanicalInputs, MechanicalModel, MechanicalState


class DummyController(Controller):
    def reset(self) -> None:
        self.calls = 0

    def step(self, measurement: Measurement, reference: Reference, dt: float) -> Command:
        self.calls += 1
        return Command(reference.values - measurement.values)


class DummyMechanicalModel(MechanicalModel):
    def reset(self, state=None) -> Mapping:
        return self.observe()

    def observe(self) -> Mapping:
        return {"q": np.zeros(1), "q_dot": np.zeros(1), "q_ddot": np.zeros(1)}

    def measure(self) -> Mapping:
        return {"q": np.zeros(1)}

    def derivative(self, t, state, inputs) -> MechanicalDerivative:
        return MechanicalDerivative(state.q_dot, inputs.external_load + inputs.actuator_effort)

    def forward_kinematics(self, q) -> Mapping:
        return {"rack_position": q.copy()}

    def constraint_residual(self, state):
        return np.zeros(0)

    def actuator_kinematics(self, state):
        return state.q.copy(), state.q_dot.copy()

    def actuator_ports(self, state, inputs):
        return (TranslationalPowerPort(float(inputs.actuator_effort[0]), float(state.q_dot[0])),)


class DummyHydraulicModel(HydraulicModel):
    def reset(self, state=None) -> Mapping:
        return self.observe()

    def observe(self) -> Mapping:
        return {"pressure": np.ones(1), "flow": np.zeros(1)}

    def measure(self) -> Mapping:
        return {"pressure": np.ones(1)}

    def rhs(self, t, state, inputs) -> HydraulicState:
        return HydraulicState(np.zeros_like(state.pressure), np.zeros_like(state.flow))

    def outputs(self, state, inputs) -> HydraulicOutputs:
        effort = np.ones_like(inputs.actuator_velocity)
        return HydraulicOutputs(
            effort,
            (HydraulicPowerPort(float(state.pressure[0]), float(state.flow[0])),),
            (TranslationalPowerPort(float(effort[0]), float(inputs.actuator_velocity[0])),),
        )

    def update_parameters(self, updates: Mapping[str, ParameterMeta]) -> None:
        self.updates = dict(updates)


def test_controller_substitute_is_instantiable() -> None:
    controller = DummyController()
    controller.reset()
    command = controller.step(Measurement(np.array([1.0])), Reference(np.array([2.0])), 0.01)
    assert command.values.tolist() == [1.0]


def test_mechanical_substitute_is_instantiable() -> None:
    model = DummyMechanicalModel()
    state = MechanicalState(np.array([0.0]), np.array([0.5]), np.array([0.0]))
    inputs = MechanicalInputs(np.array([-1.0]), np.array([2.0]))
    derivative = model.derivative(0.0, state, inputs)
    assert derivative.q_ddot.tolist() == [1.0]
    assert model.actuator_kinematics(state)[1].tolist() == [0.5]


def test_hydraulic_substitute_is_instantiable() -> None:
    model = DummyHydraulicModel()
    state = HydraulicState(np.array([2.0e6]), np.array([1.0e-4]))
    inputs = HydraulicInputs(np.array([0.1]), np.array([0.0]), np.array([0.2]))
    assert model.outputs(state, inputs).actuator_effort.tolist() == [1.0]

