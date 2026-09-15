"""Five-DOF six-axle steering closed-chain kinematics."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Mapping
import numpy as np
from scipy.optimize import least_squares
from .geometry2d import ClosedChainConstraint, ReferenceGeometry, RigidLink2D, vector

GENERALIZED_COORDINATES = ("q_front", "q3", "q4", "q5", "q6")
ACTUATOR_ORDER = tuple(f"ACTUATOR_{axle}_{side}" for axle in range(3, 7) for side in ("A", "B"))
RESIDUAL_TOLERANCE_M = 1.0e-10
SINGULAR_CONDITION_LIMIT = 1.0e10

class KinematicsError(RuntimeError):
    pass

class UnreachableGeometryError(KinematicsError):
    pass

class BranchDiscontinuityError(KinematicsError):
    pass

@dataclass(frozen=True, slots=True)
class KinematicStatus:
    reachable: bool
    singular: bool
    condition_number: float
    message: str = ""

@dataclass(frozen=True, slots=True)
class GroupSolution:
    angles: Mapping[str, float]
    angle_sensitivity: Mapping[str, float]
    residuals: Mapping[str, float]
    condition_number: float
    singular: bool

@dataclass(frozen=True, slots=True)
class KinematicSolution:
    q: np.ndarray
    body_angles: Mapping[str, float]
    wheel_angles: Mapping[str, float]
    swing_angles: Mapping[str, float]
    hardpoints: Mapping[str, np.ndarray]
    link_endpoints: Mapping[str, tuple[np.ndarray, np.ndarray]]
    rigid_link_lengths: Mapping[str, float]
    constraint_residuals: Mapping[str, float]
    actuator_lengths: Mapping[str, float]
    actuator_jacobian: np.ndarray
    status: KinematicStatus

class _ClosedChainGroup:
    def __init__(self, reference: ReferenceGeometry, name: str,
                 bodies: tuple[str, ...], coordinate_bodies: tuple[str, str],
                 links: tuple[RigidLink2D, ...]):
        if len(bodies) != len(links) + 1:
            raise ValueError(f"{name}: link constraints plus one coordinate must close the system")
        self.reference, self.name = reference, name
        self.bodies, self.coordinate_bodies, self.links = bodies, coordinate_bodies, links
        self.constraints = tuple(ClosedChainConstraint(link) for link in links)
        self._previous_q = 0.0
        self._previous = np.zeros(len(bodies))

    def reset(self) -> None:
        self._previous_q = 0.0
        self._previous = np.zeros(len(self.bodies))

    def _angles(self, q_value: float, x: np.ndarray) -> dict[str, float]:
        return dict(zip(self.bodies, map(float, x)))

    def _point(self, endpoint: tuple[str, str], angles: Mapping[str, float]) -> np.ndarray:
        body, point_id = endpoint
        return self.reference.bodies[body].world_point(point_id, angles[body])

    def residual_vector(self, q_value: float, x: np.ndarray) -> np.ndarray:
        angles = self._angles(q_value, x)
        link_residuals = [constraint.residual(
            self._point(constraint.link.endpoint_a, angles),
            self._point(constraint.link.endpoint_b, angles),
        ) for constraint in self.constraints]
        coordinate = 0.5 * sum(angles[body] for body in self.coordinate_bodies) - q_value
        return np.array([*link_residuals, coordinate])

    def _body_derivative(self, endpoint, angles, body_name) -> np.ndarray:
        body, point_id = endpoint
        if body != body_name:
            return np.zeros(2)
        return self.reference.bodies[body].point_angle_derivative(point_id, angles[body])

    def _column(self, q_value: float, x: np.ndarray, body_name: str) -> np.ndarray:
        angles = self._angles(q_value, x)
        column = np.zeros(len(self.links) + 1)
        for row, link in enumerate(self.links):
            pa = self._point(link.endpoint_a, angles)
            pb = self._point(link.endpoint_b, angles)
            delta = pb - pa
            length = np.linalg.norm(delta)
            if length <= 1e-14:
                raise UnreachableGeometryError(f"{link.name}: coincident endpoints")
            dpa = self._body_derivative(link.endpoint_a, angles, body_name)
            dpb = self._body_derivative(link.endpoint_b, angles, body_name)
            column[row] = delta @ (dpb - dpa) / length
        if body_name in self.coordinate_bodies:
            column[-1] = 0.5
        return column

    def jacobian_unknown(self, q_value: float, x: np.ndarray) -> np.ndarray:
        return np.column_stack([self._column(q_value, x, body) for body in self.bodies])

    def solve(self, q_value: float) -> GroupSolution:
        if not np.isfinite(q_value):
            raise UnreachableGeometryError(f"{self.name}: generalized coordinate is not finite")
        result = least_squares(
            lambda x: self.residual_vector(q_value, x), self._previous,
            jac=lambda x: self.jacobian_unknown(q_value, x),
            xtol=1e-13, ftol=1e-13, gtol=1e-13, max_nfev=300,
        )
        residual = self.residual_vector(q_value, result.x)
        max_residual = float(np.max(np.abs(residual), initial=0.0))
        if not result.success or not np.all(np.isfinite(result.x)) or max_residual > RESIDUAL_TOLERANCE_M:
            raise UnreachableGeometryError(
                f"{self.name}: closed chain is unreachable; max residual={max_residual:.3e} m"
            )
        if abs(q_value - self._previous_q) <= 0.1 and np.max(np.abs(result.x - self._previous), initial=0.0) > 0.5:
            raise BranchDiscontinuityError(f"{self.name}: assembly branch jump detected")
        jx = self.jacobian_unknown(q_value, result.x)
        condition = float(np.linalg.cond(jx))
        singular = (not np.isfinite(condition)) or condition > SINGULAR_CONDITION_LIMIT
        if singular:
            sensitivity = np.full(len(self.bodies), np.nan)
        else:
            q_column = np.zeros(len(self.bodies)); q_column[-1] = 1.0
            sensitivity = np.linalg.solve(jx, q_column)
        angles = self._angles(q_value, result.x)
        angle_sensitivity = dict(zip(self.bodies, map(float, sensitivity)))
        self._previous_q, self._previous = q_value, result.x.copy()
        return GroupSolution(
            angles, angle_sensitivity,
            dict(zip((link.name for link in self.links), map(float, residual[:-1]))),
            condition, singular,
        )

class SixAxleSteeringKinematics:
    """Project-specific five-coordinate model; actuator lengths are outputs."""
    generalized_coordinates = GENERALIZED_COORDINATES
    actuator_order = ACTUATOR_ORDER
    dof = 5
    group_dofs = {"AXLE_1_2": 1, "AXLE_3": 1, "AXLE_4": 1, "AXLE_5": 1, "AXLE_6": 1}

    def __init__(self, reference: ReferenceGeometry):
        self.reference = reference
        front_bodies = (
            "SWING_1_NEG_Y", "SWING_1_POS_Y", "SWING_2_NEG_Y", "SWING_2_POS_Y",
            "WHEEL_1_NEG_Y", "WHEEL_1_POS_Y", "WHEEL_2_NEG_Y", "WHEEL_2_POS_Y",
        )
        front_links = tuple(reference.links[name] for name in (
            "CROSS_TIE_ROD_12", "LONG_TIE_ROD_12_NEG_Y", "LONG_TIE_ROD_12_POS_Y",
            "SIDE_TIE_ROD_1_NEG_Y", "SIDE_TIE_ROD_1_POS_Y",
            "SIDE_TIE_ROD_2_NEG_Y", "SIDE_TIE_ROD_2_POS_Y",
        ))
        self._groups = [_ClosedChainGroup(
            reference, "AXLE_1_2", front_bodies,
            ("SWING_1_NEG_Y", "SWING_1_POS_Y"), front_links
        )]
        for axle in range(3, 7):
            bodies = (
                f"SWING_{axle}_NEG_Y", f"SWING_{axle}_POS_Y",
                f"WHEEL_{axle}_NEG_Y", f"WHEEL_{axle}_POS_Y"
            )
            links = tuple(reference.links[name] for name in (
                f"CROSS_TIE_ROD_{axle}", f"SIDE_TIE_ROD_{axle}_NEG_Y",
                f"SIDE_TIE_ROD_{axle}_POS_Y",
            ))
            self._groups.append(_ClosedChainGroup(
                reference, f"AXLE_{axle}", bodies,
                (f"SWING_{axle}_NEG_Y", f"SWING_{axle}_POS_Y"), links
            ))

    def reset(self) -> None:
        for group in self._groups:
            group.reset()

    def _hardpoints(self, angles: Mapping[str, float]) -> dict[str, np.ndarray]:
        solved = {}
        for point_id, point in self.reference.points.items():
            owner = self.reference.point_owners[point_id]
            solved[point_id] = (
                vector(point.position) if owner == "FRAME"
                else self.reference.bodies[owner].world_point(point_id, angles[owner])
            )
        return solved

    def solve(self, q) -> KinematicSolution:
        q_array = np.asarray(q, dtype=float)
        if q_array.shape != (5,):
            raise ValueError("q must have shape (5,) ordered as q_front,q3,q4,q5,q6")
        if not np.all(np.isfinite(q_array)):
            raise UnreachableGeometryError("q contains a non-finite value")
        group_solutions = [group.solve(float(value)) for group, value in zip(self._groups, q_array)]
        angles, residuals = {}, {}
        for solution in group_solutions:
            angles.update(solution.angles)
            residuals.update(solution.residuals)
        hardpoints = self._hardpoints(angles)
        link_endpoints, current_lengths = {}, {}
        for name, link in self.reference.links.items():
            pa = hardpoints[link.endpoint_a[1]].copy()
            pb = hardpoints[link.endpoint_b[1]].copy()
            link_endpoints[name] = (pa, pb)
            current_lengths[name] = float(np.linalg.norm(pb - pa))

        actuator_lengths, actuator_jacobian = {}, np.zeros((len(ACTUATOR_ORDER), 5))
        for row, name in enumerate(ACTUATOR_ORDER):
            actuator = self.reference.actuators[name]
            fixed = hardpoints[actuator.frame_point_id]
            moving = hardpoints[actuator.moving_point_id]
            actuator_lengths[name] = actuator.length(fixed, moving)
            body = self.reference.bodies[actuator.moving_body]
            point_derivative = body.point_angle_derivative(
                actuator.moving_point_id, angles[actuator.moving_body]
            )
            dlength_dbody = actuator.derivative_wrt_body_angle(fixed, moving, point_derivative)
            group_index = int(name.split("_")[1]) - 2
            body_sensitivity = group_solutions[group_index].angle_sensitivity[actuator.moving_body]
            actuator_jacobian[row, group_index] = dlength_dbody * body_sensitivity

        condition = max(solution.condition_number for solution in group_solutions)
        singular = any(solution.singular for solution in group_solutions)
        return KinematicSolution(
            q_array.copy(), dict(angles),
            {name: value for name, value in angles.items() if name.startswith("WHEEL_")},
            {name: value for name, value in angles.items() if name.startswith("SWING_")},
            hardpoints, link_endpoints, current_lengths, residuals,
            actuator_lengths, actuator_jacobian,
            KinematicStatus(True, singular, condition, "singular constraint Jacobian" if singular else "ok"),
        )

    def actuator_length(self, q) -> Mapping[str, float]:
        return self.solve(q).actuator_lengths

    def actuator_jacobian(self, q) -> np.ndarray:
        """Return dL/dq as an 8-by-5 matrix in actuator_order."""
        return self.solve(q).actuator_jacobian.copy()

    def actuator_velocity(self, q, q_dot) -> Mapping[str, float]:
        q_dot_array = np.asarray(q_dot, dtype=float)
        if q_dot_array.shape != (5,):
            raise ValueError("q_dot must have shape (5,)")
        velocity = self.actuator_jacobian(q) @ q_dot_array
        return dict(zip(ACTUATOR_ORDER, map(float, velocity)))

    def generalized_actuator_force(self, q, actuator_forces: Mapping[str, float]) -> np.ndarray:
        """Future coupling: Q_hyd = J_A F_A + J_B F_B per rear axle."""
        force = np.array([actuator_forces[name] for name in ACTUATOR_ORDER], dtype=float)
        return self.actuator_jacobian(q).T @ force

def ideal_ackermann_angles(steering_angle: float, wheelbase: float, track: float) -> tuple[float, float]:
    """Independent comparison utility; never used by the mechanism solver."""
    if wheelbase <= 0.0 or track <= 0.0:
        raise ValueError("wheelbase and track must be positive")
    if abs(steering_angle) < 1e-15:
        return 0.0, 0.0
    sign = float(np.sign(steering_angle))
    radius = wheelbase / np.tan(abs(steering_angle))
    if radius <= track / 2:
        raise ValueError("turn radius must exceed half the track")
    inner = np.arctan(wheelbase / (radius - track / 2))
    outer = np.arctan(wheelbase / (radius + track / 2))
    return sign * float(inner), sign * float(outer)
