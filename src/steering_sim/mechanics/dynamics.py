"""Five-coordinate reduced dynamics assembled from frozen R02-B kinematics."""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections import OrderedDict
from dataclasses import dataclass
from typing import Callable, Mapping, Sequence

import numpy as np

from .kinematics import ACTUATOR_ORDER, SixAxleSteeringKinematics
from .mass_properties import MassPropertySet, SYNTHETIC_TEST_NOTE


DOF = 5
STATE_SIZE = 2 * DOF


class IllConditionedMassMatrixError(RuntimeError):
    """Raised instead of integrating with a singular/ill-conditioned M(q)."""


class SyntheticParameterUseError(ValueError):
    """Raised when test-only parameters reach the formal engineering entry."""


@dataclass(frozen=True, slots=True)
class FiniteDifferenceSettings:
    body_jacobian_step_rad: float = 2.0e-5
    mass_derivative_step_rad: float = 2.0e-4

    def __post_init__(self) -> None:
        if self.body_jacobian_step_rad <= 0.0 or self.mass_derivative_step_rad <= 0.0:
            raise ValueError("finite-difference steps must be positive")


@dataclass(frozen=True, slots=True)
class DynamicBodyPose:
    origin_m: np.ndarray
    angle_rad: float


@dataclass(frozen=True, slots=True)
class ExternalPointForce:
    body_id: str
    point_local_m: tuple[float, float]
    force_xy_n: tuple[float, float]


@dataclass(frozen=True, slots=True)
class ExternalTorque:
    body_id: str
    torque_z_nm: float


class MechanicalLossModel(ABC):
    """Extension point for viscous, Coulomb and efficiency/resistance losses."""

    @abstractmethod
    def generalized_loss(self, q: np.ndarray, q_dot: np.ndarray) -> np.ndarray:
        """Return resisting generalized effort to subtract from applied effort."""


class ZeroMechanicalLoss(MechanicalLossModel):
    def generalized_loss(self, q: np.ndarray, q_dot: np.ndarray) -> np.ndarray:
        return np.zeros(DOF)


GeneralizedForce = np.ndarray | Sequence[float]
GeneralizedForceFunction = Callable[[float, np.ndarray, np.ndarray], GeneralizedForce]


def _rotation(angle: float) -> np.ndarray:
    c, s = np.cos(angle), np.sin(angle)
    return np.array([[c, -s], [s, c]])


def _angle_delta(plus: float, minus: float) -> float:
    delta = plus - minus
    return float(np.arctan2(np.sin(delta), np.cos(delta)))


class ReducedMechanicalDynamics:
    """Reduced dynamics on q=[q_front,q3,q4,q5,q6], never independent joint states.

    Gravity is identically zero in this revision: all motion is in a horizontal
    XOY plane, +Z is vertical, gravity acts along -Z, and there is no vertical
    component motion or body pitch/roll.
    """

    def __init__(
        self,
        kinematics: SixAxleSteeringKinematics,
        mass_properties: MassPropertySet,
        *,
        finite_difference: FiniteDifferenceSettings | None = None,
        loss_model: MechanicalLossModel | None = None,
        mass_matrix_condition_limit: float = 1.0e12,
        allow_synthetic_test_only: bool = False,
    ) -> None:
        self.kinematics = kinematics
        self.reference = kinematics.reference
        self.body_ids = tuple(self.reference.bodies) + tuple(self.reference.links)
        mass_properties.validate_complete(self.body_ids)
        if mass_properties.contains_synthetic_test_only and not allow_synthetic_test_only:
            raise SyntheticParameterUseError(
                f"{SYNTHETIC_TEST_NOTE}; pass allow_synthetic_test_only=True only in tests/examples"
            )
        self.mass_properties = mass_properties
        self.finite_difference = finite_difference or FiniteDifferenceSettings()
        self.loss_model = loss_model or ZeroMechanicalLoss()
        self.mass_matrix_condition_limit = float(mass_matrix_condition_limit)
        if self.mass_matrix_condition_limit <= 1.0:
            raise ValueError("mass_matrix_condition_limit must exceed one")
        self._jacobian_cache: OrderedDict[tuple[bytes, float], tuple[dict, dict]] = OrderedDict()

    def _fresh_solution(self, q: np.ndarray):
        return SixAxleSteeringKinematics(self.reference).solve(np.asarray(q, dtype=float))

    def body_poses(self, q: np.ndarray) -> Mapping[str, DynamicBodyPose]:
        solution = self._fresh_solution(q)
        poses = {}
        for body_id, body in self.reference.bodies.items():
            poses[body_id] = DynamicBodyPose(
                np.asarray(body.pivot, dtype=float),
                float(solution.body_angles[body_id]),
            )
        for body_id in self.reference.links:
            point_a, point_b = solution.link_endpoints[body_id]
            delta = point_b - point_a
            poses[body_id] = DynamicBodyPose(
                0.5 * (point_a + point_b),
                float(np.arctan2(delta[1], delta[0])),
            )
        return poses

    def _positions(self, poses: Mapping[str, DynamicBodyPose], local_points: Mapping[str, np.ndarray]):
        return {
            body_id: pose.origin_m + _rotation(pose.angle_rad) @ local_points[body_id]
            for body_id, pose in poses.items()
        }

    def _jacobians_for_local_points(
        self,
        q: np.ndarray,
        local_points: Mapping[str, np.ndarray],
        step: float,
    ) -> tuple[dict[str, np.ndarray], dict[str, np.ndarray]]:
        q = np.asarray(q, dtype=float)
        linear = {body_id: np.zeros((2, DOF)) for body_id in self.body_ids}
        angular = {body_id: np.zeros(DOF) for body_id in self.body_ids}
        for column in range(DOF):
            offset = np.zeros(DOF)
            offset[column] = step
            plus_pose = self.body_poses(q + offset)
            minus_pose = self.body_poses(q - offset)
            plus_position = self._positions(plus_pose, local_points)
            minus_position = self._positions(minus_pose, local_points)
            for body_id in self.body_ids:
                linear[body_id][:, column] = (
                    plus_position[body_id] - minus_position[body_id]
                ) / (2.0 * step)
                angular[body_id][column] = _angle_delta(
                    plus_pose[body_id].angle_rad, minus_pose[body_id].angle_rad
                ) / (2.0 * step)
        return linear, angular

    def _com_local_points(self) -> dict[str, np.ndarray]:
        return {
            body_id: np.array([
                self.mass_properties[body_id].com_local_x_m,
                self.mass_properties[body_id].com_local_y_m,
            ])
            for body_id in self.body_ids
        }

    def body_jacobians(
        self, q: np.ndarray, *, step_rad: float | None = None
    ) -> tuple[Mapping[str, np.ndarray], Mapping[str, np.ndarray]]:
        step = float(step_rad or self.finite_difference.body_jacobian_step_rad)
        q_array = np.asarray(q, dtype=float)
        if q_array.shape != (DOF,):
            raise ValueError("q must have shape (5,)")
        key = (q_array.tobytes(), step)
        cached = self._jacobian_cache.get(key)
        if cached is not None:
            self._jacobian_cache.move_to_end(key)
            return cached
        result = self._jacobians_for_local_points(q_array, self._com_local_points(), step)
        self._jacobian_cache[key] = result
        if len(self._jacobian_cache) > 32:
            self._jacobian_cache.popitem(last=False)
        return result

    def body_com_jacobian(
        self, q: np.ndarray, body_id: str, *, step_rad: float | None = None
    ) -> np.ndarray:
        return np.array(self.body_jacobians(q, step_rad=step_rad)[0][body_id], copy=True)

    def body_angular_jacobian(
        self, q: np.ndarray, body_id: str, *, step_rad: float | None = None
    ) -> np.ndarray:
        return np.array(self.body_jacobians(q, step_rad=step_rad)[1][body_id], copy=True)

    def body_point_jacobian(
        self,
        q: np.ndarray,
        body_id: str,
        point_local_m: Sequence[float],
        *,
        step_rad: float | None = None,
    ) -> np.ndarray:
        if body_id not in self.body_ids:
            raise KeyError(f"unknown dynamic body: {body_id}")
        point = np.asarray(point_local_m, dtype=float)
        if point.shape != (2,):
            raise ValueError("point_local_m must have shape (2,)")
        local_points = {name: np.zeros(2) for name in self.body_ids}
        local_points[body_id] = point
        step = float(step_rad or self.finite_difference.body_jacobian_step_rad)
        return self._jacobians_for_local_points(np.asarray(q, dtype=float), local_points, step)[0][body_id]

    def mass_matrix(self, q: np.ndarray, *, jacobian_step_rad: float | None = None) -> np.ndarray:
        linear, angular = self.body_jacobians(q, step_rad=jacobian_step_rad)
        matrix = np.zeros((DOF, DOF))
        for body_id in self.body_ids:
            prop = self.mass_properties[body_id]
            if not prop.include_in_inertia:
                continue
            jv = linear[body_id]
            jw = angular[body_id]
            matrix += prop.mass_kg * (jv.T @ jv) + prop.izz_kg_m2 * np.outer(jw, jw)
        return 0.5 * (matrix + matrix.T)

    def mass_matrix_derivatives(
        self,
        q: np.ndarray,
        *,
        step_rad: float | None = None,
        jacobian_step_rad: float | None = None,
    ) -> np.ndarray:
        step = float(step_rad or self.finite_difference.mass_derivative_step_rad)
        q = np.asarray(q, dtype=float)
        derivatives = np.zeros((DOF, DOF, DOF))
        for coordinate in range(DOF):
            offset = np.zeros(DOF)
            offset[coordinate] = step
            derivatives[coordinate] = (
                self.mass_matrix(q + offset, jacobian_step_rad=jacobian_step_rad)
                - self.mass_matrix(q - offset, jacobian_step_rad=jacobian_step_rad)
            ) / (2.0 * step)
        return derivatives

    def coriolis_centrifugal_bias(
        self,
        q: np.ndarray,
        q_dot: np.ndarray,
        *,
        mass_derivative_step_rad: float | None = None,
        jacobian_step_rad: float | None = None,
    ) -> np.ndarray:
        velocity = np.asarray(q_dot, dtype=float)
        if velocity.shape != (DOF,):
            raise ValueError("q_dot must have shape (5,)")
        if np.count_nonzero(velocity) == 0:
            return np.zeros(DOF)
        derivative = self.mass_matrix_derivatives(
            q,
            step_rad=mass_derivative_step_rad,
            jacobian_step_rad=jacobian_step_rad,
        )
        bias = np.zeros(DOF)
        for i in range(DOF):
            for j in range(DOF):
                for k in range(DOF):
                    christoffel = 0.5 * (
                        derivative[k, i, j]
                        + derivative[j, i, k]
                        - derivative[i, j, k]
                    )
                    bias[i] += christoffel * velocity[j] * velocity[k]
        return bias

    @staticmethod
    def gravity_generalized_force(q: np.ndarray) -> np.ndarray:
        """G(q)=0 because horizontal XOY motion has no gravitational work."""
        q_array = np.asarray(q, dtype=float)
        if q_array.shape != (DOF,):
            raise ValueError("q must have shape (5,)")
        return np.zeros(DOF)

    def kinetic_energy(self, q: np.ndarray, q_dot: np.ndarray) -> float:
        velocity = np.asarray(q_dot, dtype=float)
        return float(0.5 * velocity @ self.mass_matrix(q) @ velocity)

    def kinetic_energy_by_bodies(self, q: np.ndarray, q_dot: np.ndarray) -> float:
        velocity = np.asarray(q_dot, dtype=float)
        linear, angular = self.body_jacobians(q)
        energy = 0.0
        for body_id in self.body_ids:
            prop = self.mass_properties[body_id]
            if not prop.include_in_inertia:
                continue
            v_com = linear[body_id] @ velocity
            omega = float(angular[body_id] @ velocity)
            energy += 0.5 * prop.mass_kg * float(v_com @ v_com)
            energy += 0.5 * prop.izz_kg_m2 * omega**2
        return float(energy)

    def actuator_generalized_force(
        self, q: np.ndarray, actuator_forces_n: Mapping[str, float] | Sequence[float]
    ) -> np.ndarray:
        if isinstance(actuator_forces_n, Mapping):
            forces = np.array([actuator_forces_n[name] for name in ACTUATOR_ORDER], dtype=float)
        else:
            forces = np.asarray(actuator_forces_n, dtype=float)
        if forces.shape != (len(ACTUATOR_ORDER),):
            raise ValueError("actuator forces must have shape (8,)")
        jacobian = SixAxleSteeringKinematics(self.reference).actuator_jacobian(q)
        return jacobian.T @ forces

    def actuator_length_velocity(self, q: np.ndarray, q_dot: np.ndarray) -> np.ndarray:
        jacobian = SixAxleSteeringKinematics(self.reference).actuator_jacobian(q)
        return jacobian @ np.asarray(q_dot, dtype=float)

    def point_force_generalized_force(
        self,
        q: np.ndarray,
        body_id: str,
        point_local_m: Sequence[float],
        force_xy_n: Sequence[float],
    ) -> np.ndarray:
        force = np.asarray(force_xy_n, dtype=float)
        if force.shape != (2,):
            raise ValueError("force_xy_n must have shape (2,)")
        return self.body_point_jacobian(q, body_id, point_local_m).T @ force

    def torque_generalized_force(
        self, q: np.ndarray, body_id: str, torque_z_nm: float
    ) -> np.ndarray:
        return self.body_angular_jacobian(q, body_id) * float(torque_z_nm)

    def external_generalized_force(
        self,
        q: np.ndarray,
        point_forces: Sequence[ExternalPointForce] = (),
        torques: Sequence[ExternalTorque] = (),
    ) -> np.ndarray:
        generalized = np.zeros(DOF)
        for load in point_forces:
            generalized += self.point_force_generalized_force(
                q, load.body_id, load.point_local_m, load.force_xy_n
            )
        for load in torques:
            generalized += self.torque_generalized_force(q, load.body_id, load.torque_z_nm)
        return generalized

    def mechanical_rhs(
        self,
        t: float,
        y: np.ndarray,
        generalized_force: GeneralizedForce | GeneralizedForceFunction,
    ) -> np.ndarray:
        state = np.asarray(y, dtype=float)
        if state.shape != (STATE_SIZE,):
            raise ValueError("mechanical state must have shape (10,) as [q,q_dot]")
        q, q_dot = state[:DOF], state[DOF:]
        applied = generalized_force(t, q.copy(), q_dot.copy()) if callable(generalized_force) else generalized_force
        applied = np.asarray(applied, dtype=float)
        if applied.shape != (DOF,):
            raise ValueError("generalized force must have shape (5,)")
        matrix = self.mass_matrix(q)
        eigenvalues = np.linalg.eigvalsh(matrix)
        condition = float(np.linalg.cond(matrix))
        if (
            not np.all(np.isfinite(matrix))
            or eigenvalues[0] <= 0.0
            or not np.isfinite(condition)
            or condition > self.mass_matrix_condition_limit
        ):
            raise IllConditionedMassMatrixError(
                f"M(q) is not numerically positive definite: "
                f"lambda_min={eigenvalues[0]:.3e}, condition={condition:.3e}"
            )
        bias = self.coriolis_centrifugal_bias(q, q_dot)
        loss = np.asarray(self.loss_model.generalized_loss(q, q_dot), dtype=float)
        if loss.shape != (DOF,):
            raise ValueError("mechanical loss must have shape (5,)")
        total = applied + self.gravity_generalized_force(q) - bias - loss
        q_ddot = np.linalg.solve(matrix, total)
        return np.concatenate((q_dot, q_ddot))


def mechanical_rhs(
    dynamics: ReducedMechanicalDynamics,
    t: float,
    y: np.ndarray,
    generalized_force: GeneralizedForce | GeneralizedForceFunction,
) -> np.ndarray:
    """Functional adapter for solver/orchestrator use."""
    return dynamics.mechanical_rhs(t, y, generalized_force)
