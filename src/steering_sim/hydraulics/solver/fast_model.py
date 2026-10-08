from __future__ import annotations

import math
from dataclasses import dataclass, field
from time import perf_counter
from typing import Mapping

import numpy as np
from numpy.typing import NDArray
from scipy.integrate import solve_ivp

from ..assembly.full_model import HydraulicSystem
from ..initialization.initial_conditions import InitialCondition, build_initial_conditions, build_state_scaling
from ..initialization.steady_init import relax_pressure_states
from .algebraic import AlgebraicDiagnostics, LocalAlgebraicSolver


PRESSURE_FAMILIES = {"HA001", "HJ0022", "HJ020", "HJ021", "HL0000", "HL0002", "HL011", "HL012"}
LINE_FAMILIES = {"HL0000", "HL0002", "HL011", "HL012"}
CYLINDER_FAMILIES = {"HJ0022", "HJ020", "HJ021"}
SWITCHING_FAMILIES = {"CV010", "CV012", "HYDPRV0", "PV00022", "RV010", "RV011"}
ORIFICE_FAMILIES = {"FP04", "HYDCONSHTL0", "HYDORF0", "HYDORT0", "HYDVORF0", "SC_1"}


def _safe_float(value: object, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        text = str(value).replace("PI", "pi")
        try:
            return float(eval(text, {"__builtins__": {}}, {"sqrt": math.sqrt, "pi": math.pi}))
        except Exception:
            return default


@dataclass(frozen=True, slots=True)
class DynamicHydraulicElement:
    alias: str
    submodel: str
    state_indices: tuple[int, ...]
    junction_indices: tuple[int, ...]
    volume_m3: float
    bulk_modulus_pa: float
    interface_conductance: float


@dataclass(frozen=True, slots=True)
class AlgebraicBranch:
    alias: str
    submodel: str
    junction_indices: tuple[int, ...]
    base_conductance: float


@dataclass(slots=True)
class GroupRuntime:
    group_id: str
    category: str
    junction_indices: NDArray[np.int64]
    solver: LocalAlgebraicSolver | None
    branch_indices: tuple[int, ...]
    dependent_state_indices: tuple[int, ...] = ()
    cache_signature: tuple[bytes, tuple[tuple[str, float], ...]] | None = None
    cache_values: NDArray[np.float64] | None = None
    evaluation_calls: int = 0
    cache_hits: int = 0


@dataclass(frozen=True, slots=True)
class AlgebraicSolution:
    junction_pressure_pa: NDArray[np.float64]
    branch_flow_m3_s: dict[str, float]
    max_hydraulic_residual_m3_s: float
    success: bool


@dataclass(frozen=True, slots=True)
class FastSimulationResult:
    success: bool
    message: str
    time_s: NDArray[np.float64]
    state: NDArray[np.float64]
    wall_time_s: float
    nfev: int
    njev: int
    nlu: int
    solver_steps: int


@dataclass(slots=True)
class FastHydraulicModel:
    system: HydraulicSystem
    hydraulic_junction_ids: dict[str, int]
    ports_by_alias: dict[str, tuple[int, ...]]
    dynamic_hydraulic: tuple[DynamicHydraulicElement, ...]
    branches: tuple[AlgebraicBranch, ...]
    groups: tuple[GroupRuntime, ...]
    state_by_key: dict[tuple[str, str], int]
    initial_conditions: tuple[InitialCondition, ...]
    initial_state: NDArray[np.float64]
    state_scale: NDArray[np.float64]
    atol: NDArray[np.float64]
    parameters: dict[str, dict[str, float | str]]
    element_submodel: dict[str, str]
    mechanical_junction_by_alias: dict[str, str]
    aliases_by_mechanical_junction: dict[str, tuple[str, ...]]
    dynamic_by_junction: tuple[tuple[tuple[int, int], ...], ...]
    tank_nodes: tuple[int, ...]
    pump_definitions: tuple[tuple[str, int, int, float], ...]
    _last_algebraic: AlgebraicSolution | None = None
    _rhs_entries_supplied: NDArray[np.bool_] = field(default_factory=lambda: np.empty(0, dtype=bool))
    _jacobian_sparsity: object | None = None
    _use_jacobian_sparsity: bool = False
    _use_algebraic_cache: bool = True
    # Hydraulic port pressures in the Amesim hydraulic library are gauge
    # pressures.  Keep this configurable so the C2A staged comparison can
    # reproduce the accepted C1 baseline before enabling the correction.
    _pressure_reference_pa: float = 0.0
    # Families listed here use their source-model flow/pressure gradient.
    # An empty set reproduces the Phase 2-C1 fixed-conductance surrogate.
    _source_gradient_families: frozenset[str] = field(default_factory=lambda: frozenset({"CV010", "RV010"}))
    # Calibrated passive restrictions on the pressure-control path.  This is
    # separate from line reduction so C2A can change only the local R laws.
    _source_path_resistance_families: frozenset[str] = field(default_factory=frozenset)
    # Families whose reduced R-C chain uses geometry/fluid-derived total line
    # resistance instead of the Phase-2B fixed interface conductance.
    _calibrated_line_families: frozenset[str] = field(default_factory=frozenset)

    @classmethod
    def from_ir(cls, audit_dir) -> "FastHydraulicModel":
        system = HydraulicSystem.from_ir(audit_dir, line_fidelity="fast")
        if len(system.states) != 109:
            raise ValueError(f"FAST state contract changed: expected 109, got {len(system.states)}")
        hydraulic_junctions = [junction for junction in system.junctions if junction.domain == "hydraulic"]
        hj = {junction.junction_id: index for index, junction in enumerate(hydraulic_junctions)}
        owner = {element.element_id: element for element in system.elements}
        ports_by_alias_raw: dict[str, list[tuple[int, str]]] = {}
        mechanical_junction_by_alias: dict[str, str] = {}
        aliases_by_mechanical: dict[str, list[str]] = {}
        for port in system.ports:
            element = owner[port["element_id"]]
            if port["domain"] == "hydraulic":
                ports_by_alias_raw.setdefault(element.instance_alias, []).append((int(port["port_id"]), port["connected_junction"]))
            elif port["domain"] in {"translation", "rotation"}:
                mechanical_junction_by_alias[element.instance_alias] = port["connected_junction"]
                aliases_by_mechanical.setdefault(port["connected_junction"], []).append(element.instance_alias)
        ports_by_alias = {
            alias: tuple(hj[junction] for _, junction in sorted(values))
            for alias, values in ports_by_alias_raw.items()
        }
        state_by_key = {(state.instance, state.state_name): state.index for state in system.states}
        state_by_alias: dict[str, list[int]] = {}
        for state in system.states:
            state_by_alias.setdefault(state.instance, []).append(state.index)
        params: dict[str, dict[str, float | str]] = {}
        for element in system.elements:
            params[element.instance_alias] = {p.title.strip().lower(): p.si_value for p in element.parameters}

        dynamic: list[DynamicHydraulicElement] = []
        for element in system.elements:
            if element.submodel not in PRESSURE_FAMILIES or element.instance_alias not in state_by_alias:
                continue
            p = params[element.instance_alias]
            if element.submodel in LINE_FAMILIES:
                area = _safe_float(p.get("cross-sectional area"), 500.0e-6)
                # Parameter loader already converts mm^2 to m^2.
                length = _safe_float(p.get("length"), 1.0)
                volume = max(area * length, 1.0e-7)
                conductance = 5.0e-10 if element.submodel == "HL0000" else 2.0e-11
            elif element.submodel == "HA001":
                volume = max(_safe_float(p.get("accumulator volume"), 5.0) * (1.0e-3 if _safe_float(p.get("accumulator volume"), 5.0) > 0.1 else 1.0), 1.0e-6)
                conductance = 1.0e-8
            else:
                dead = _safe_float(p.get("dead volume at port 1 end"), 50.0e-6)
                volume = max(dead, 1.0e-7)
                conductance = 2.0e-9
            beta = _safe_float(p.get("user specified effective bulk modulus"), 8.0e8)
            if beta < 1.0e7:
                beta *= 1.0e5
            dynamic.append(DynamicHydraulicElement(element.instance_alias, element.submodel, tuple(state_by_alias[element.instance_alias]), ports_by_alias[element.instance_alias], volume, beta, conductance))

        branches: list[AlgebraicBranch] = []
        for element in system.elements:
            js = ports_by_alias.get(element.instance_alias, ())
            if not element.active_power or not js or element.submodel in PRESSURE_FAMILIES or element.submodel in {"TK000", "PU001"}:
                continue
            if element.submodel in SWITCHING_FAMILIES:
                g = 8.0e-11
            elif element.submodel in ORIFICE_FAMILIES:
                g = 1.5e-11
            else:
                g = 2.0e-11
            branches.append(AlgebraicBranch(element.instance_alias, element.submodel, js, g))

        element_submodel = {element.instance_alias: element.submodel for element in system.elements}
        group_by_alias: dict[str, str] = {}
        for group in system.algebraic_groups:
            for alias in group.elements:
                group_by_alias[alias] = group.group_id
        groups: list[GroupRuntime] = []
        for group in system.algebraic_groups:
            indices = np.array([hj[j] for j in group.junctions if j in hj], dtype=np.int64)
            submodels = {element_submodel[a] for a in group.elements if a in element_submodel}
            if submodels & SWITCHING_FAMILIES:
                category = "SWITCHING"
            elif submodels & ORIFICE_FAMILIES:
                category = "SMALL_NONLINEAR"
            elif len(indices) <= 1:
                category = "EXPLICIT"
            else:
                category = "LINEAR"
            solver = None if len(indices) == 0 else LocalAlgebraicSolver(group.group_id, len(indices), max_iterations=8)
            node_set = set(map(int, indices))
            branch_indices = tuple(index for index, branch in enumerate(branches) if node_set.intersection(branch.junction_indices))
            groups.append(GroupRuntime(group.group_id, category, indices, solver, branch_indices))

        dynamic_by_junction_raw: dict[int, list[tuple[int, int]]] = {}
        for dynamic_index, dynamic_element in enumerate(dynamic):
            for local_port, junction in enumerate(dynamic_element.junction_indices):
                dynamic_by_junction_raw.setdefault(junction, []).append((dynamic_index, local_port))
        dynamic_by_junction = tuple(tuple(dynamic_by_junction_raw.get(index, ())) for index in range(len(hj)))
        # A group's algebraic solution can depend only on storage states touching
        # its own nodes or the endpoints of branches included in the group.
        # Store this exact dependency signature once so finite-difference
        # perturbations invalidate only the affected local solves.
        dependency_sets: list[set[int]] = []
        group_indices_by_node: dict[int, set[int]] = {}
        for group_index, runtime in enumerate(groups):
            for node in map(int, runtime.junction_indices):
                group_indices_by_node.setdefault(node, set()).add(group_index)
            dependency_nodes = set(map(int, runtime.junction_indices))
            for branch_index in runtime.branch_indices:
                dependency_nodes.update(branches[branch_index].junction_indices)
            dependent_states: set[int] = set()
            for node in dependency_nodes:
                for dynamic_index, port_index in dynamic_by_junction[node]:
                    item = dynamic[dynamic_index]
                    dependent_states.add(item.state_indices[min(port_index, len(item.state_indices) - 1)])
            dependency_sets.append(dependent_states)
        group_neighbors = [set() for _ in groups]
        for branch in branches:
            touched = sorted({group_index for node in branch.junction_indices for group_index in group_indices_by_node.get(node, ())})
            for left in touched:
                group_neighbors[left].update(right for right in touched if right != left)
        # A branch crossing two algebraic groups transmits the neighboring
        # group's pressure.  Close dependencies over that small group graph.
        for start, runtime in enumerate(groups):
            component = {start}
            pending = [start]
            while pending:
                current = pending.pop()
                for neighbor in group_neighbors[current] - component:
                    component.add(neighbor); pending.append(neighbor)
            runtime.dependent_state_indices = tuple(sorted(set().union(*(dependency_sets[index] for index in component))))
        tank_nodes = tuple(sorted({js[0] for alias, js in ports_by_alias.items() if element_submodel.get(alias) == "TK000" and js}))
        pumps = tuple((alias, js[0], js[1], 10.0 * 1.59154943091895e-7) for alias, js in ports_by_alias.items() if element_submodel.get(alias) == "PU001" and len(js) >= 2)

        initial, initial_records = build_initial_conditions(system.states)
        scale, atol, _ = build_state_scaling(system.states)
        return cls(
            system, hj, ports_by_alias, tuple(dynamic), tuple(branches), tuple(groups), state_by_key,
            initial_records, initial, scale, atol, params, element_submodel, mechanical_junction_by_alias,
            {key: tuple(value) for key, value in aliases_by_mechanical.items()}, dynamic_by_junction, tank_nodes, pumps, None,
            np.zeros(len(system.states), dtype=bool),
        )

    def _command(self, alias: str, inputs: Mapping[str, float]) -> float:
        if alias in inputs:
            return float(inputs[alias])
        return float(inputs.get("valve_command", 0.2))

    @staticmethod
    def _resolve_inputs(inputs: Mapping[str, object] | None, t: float) -> dict[str, float]:
        result: dict[str, float] = {}
        for key, value in (inputs or {}).items():
            result[key] = float(value(t)) if callable(value) else float(value)
        return result

    def _branch_pairs(self, branch: AlgebraicBranch) -> tuple[tuple[int, int], ...]:
        js = branch.junction_indices
        if len(js) < 2:
            return ()
        if branch.submodel == "SC_1" and len(js) >= 4:
            return ((js[0], js[2]), (js[1], js[3]))
        if len(js) == 2:
            return ((js[0], js[1]),)
        return tuple((js[0], other) for other in js[1:])

    def _line_interface_conductance(self, dynamic: DynamicHydraulicElement) -> float:
        if dynamic.submodel not in self._calibrated_line_families:
            return dynamic.interface_conductance
        if dynamic.submodel == "HL0000":
            # HL0000 is a pure lumped compliance: source ports share pressure
            # and contain no pipefr1_ resistance. A high finite conductance is
            # the explicit-ODE regularization of that zero-loss constraint.
            return 1.0e-7
        p = self.parameters.get(dynamic.alias, {})
        diameter = _safe_float(p.get("hydraulic diameter", p.get("diameter", 0.025)), 0.025)
        if diameter > 1.0:
            diameter *= 1.0e-3
        length = _safe_float(p.get("length"), 1.0)
        gain = _safe_float(p.get("friction factor gain"), 1.0)
        # qh1_1 elementaryhydraulicprops at the reference temperature.
        density = 883.0
        kinematic_viscosity = 56.47e-6
        dynamic_viscosity = density * kinematic_viscosity
        total_resistance = gain * 128.0 * dynamic_viscosity * length / (math.pi * max(diameter, 1.0e-6) ** 4)
        count = len(dynamic.state_indices)
        # Existing reduced chain has two end resistances 1/g and (count-1)
        # internal resistances count/g. Allocate them so their sum is R_total.
        resistance_units = 2 + max(count - 1, 0) * count
        source_conductance = resistance_units / max(total_resistance, 1.0)
        # A one-cell FAST reduction cannot carry the microsecond full-line
        # pole implied by the raw pipefr1_ resistance without recreating the
        # eliminated stiff states. Retain a conservative 5x improvement over
        # the old 2e-11 interface while preserving the 109-state model.
        return min(source_conductance, 1.0e-10)

    def _flow_and_derivative(self, branch: AlgebraicBranch, dp: float, inputs: Mapping[str, float]) -> tuple[float, float]:
        command = min(max(self._command(branch.alias, inputs), 0.0), 1.0)
        if branch.submodel in SWITCHING_FAMILIES:
            p = self.parameters.get(branch.alias, {})
            crack = next((_safe_float(p[key], 2.0e5) for key in (
                "relief valve cracking pressure", "maximum relief valve cracking pressure",
                "check valve cracking pressure", "minimum set pressure (spring pre-tension)") if key in p), 2.0e5)
            if branch.submodel in self._source_gradient_families:
                gradient_titles = (
                    "check valve flow rate pressure gradient",
                    "relief valve flow rate pressure gradient",
                )
                raw_gradient = next((_safe_float(p[key], 0.0) for key in gradient_titles if key in p), 0.0)
                # CV010.c/RV010.c: L/min/bar -> m^3/s/Pa.
                valve_gradient = raw_gradient * 1.66666666666667e-10
            else:
                # Accepted Phase 2-C1 engineering surrogate.
                valve_gradient = branch.base_conductance
            # Frozen CV/RV equations use p2-p1; branch pairs are stored in
            # port order (p1, p2), hence the directed driving pressure is -dp.
            delta = -dp - crack
            if branch.submodel in self._source_gradient_families:
                # All CV010/RV010 instances in qh1_1 have hyst=0.  Amesim's
                # llimit law is therefore max(delta, 0); polysmooth only
                # guards against negative flow and does not alter this branch.
                positive = max(delta, 0.0)
                d_positive = 1.0 if delta > 0.0 else 0.0
                leakage = 0.0
            else:
                smoothing = max(1.0e4, 0.01 * max(crack, 1.0e5))
                radius = math.hypot(delta, smoothing)
                # Split the sum to avoid overflow in delta + radius during a
                # rejected nonlinear iterate; this is algebraically identical.
                positive = 0.5 * delta + 0.5 * radius
                d_positive = 0.5 * (1.0 + delta / radius)
                leakage = 1.0e-14
            return -valve_gradient * positive + leakage * dp, valve_gradient * d_positive + leakage
        if branch.submodel == "HYDORF0" and branch.submodel in self._source_path_resistance_families:
            p = self.parameters.get(branch.alias, {})
            area = _safe_float(p.get("cross-sectional area"), 20.0e-6)
            if area > 1.0e-3:
                area *= 1.0e-6
            density = _safe_float(p.get("working density for pressure drop measurement"), 850.0)
            coefficient = _safe_float(p.get("maximum flow coefficient cq"), 0.7)
            eps = 10.0
            base = coefficient * area * math.sqrt(2.0 / max(density, 1.0))
            denom = (dp * dp + eps * eps) ** 0.25
            flow = base * dp / denom
            derivative = base * (eps * eps + 0.5 * dp * dp) / (dp * dp + eps * eps) ** 1.25
            return flow, max(derivative, 1.0e-15)
        if branch.submodel == "HYDORT0" and branch.submodel in self._source_path_resistance_families:
            # Exact knots from libhydr/data/q_dP_coolant_sym.data. Piecewise
            # linear evaluation preserves the measured finite zero-dp slope
            # and avoids inventing a singular square-root derivative.
            pressure_knots = (0.0, 1.0e3, 5.0e3, 1.0e4, 1.5e4, 5.0e4, 1.0e5, 5.0e5, 2.0e6)
            flow_knots = tuple(value / 60000.0 for value in (0.0, 1.15, 2.56, 3.62, 4.44, 8.10, 11.46, 25.60, 51.20))
            magnitude = abs(dp)
            if magnitude > pressure_knots[-1]:
                # Continue with the turbulent sqrt asymptote beyond the table
                # domain instead of an unbounded linear extrapolation.
                qmag = flow_knots[-1] * math.sqrt(magnitude / pressure_knots[-1])
                slope = 0.5 * qmag / magnitude
                return math.copysign(qmag, dp), max(slope, 1.0e-15)
            upper = 1
            while upper < len(pressure_knots) - 1 and magnitude > pressure_knots[upper]:
                upper += 1
            lower = upper - 1
            slope = (flow_knots[upper] - flow_knots[lower]) / (pressure_knots[upper] - pressure_knots[lower])
            qmag = flow_knots[lower] + slope * (magnitude - pressure_knots[lower])
            return math.copysign(max(qmag, 0.0), dp), max(slope, 1.0e-15)
        if branch.submodel in ORIFICE_FAMILIES:
            conductance = branch.base_conductance * max(command, 0.02)
            scale = 1.0e6
            denominator = math.sqrt(1.0 + abs(dp) / scale)
            flow = conductance * dp / denominator
            derivative = conductance * (1.0 + 0.5 * abs(dp) / scale) / denominator**3
            return flow, max(derivative, 1.0e-15)
        return branch.base_conductance * dp, branch.base_conductance

    def solve_algebraic(self, _t: float, x: NDArray[np.float64], inputs: Mapping[str, float] | None = None) -> AlgebraicSolution:
        inputs = self._resolve_inputs(inputs, _t)
        input_signature = tuple(sorted(inputs.items()))
        n = len(self.hydraulic_junction_ids)
        pressure = np.full(n, self._pressure_reference_pa, dtype=float)
        branch_flow: dict[str, float] = {}
        pump_sources: list[tuple[int, int, float, str]] = []
        for alias, inlet, outlet, displacement in self.pump_definitions:
            speed = float(inputs.get(f"{alias}.speed_rad_s", inputs.get("pump_speed_rad_s", 1350.0 * 2.0 * math.pi / 60.0)))
            pump_sources.append((inlet, outlet, displacement * speed, alias))

        solved_nodes: set[int] = set()
        max_residual = 0.0
        for runtime in self.groups:
            nodes = runtime.junction_indices
            if not len(nodes) or runtime.solver is None:
                continue
            runtime.evaluation_calls += 1
            state_signature = np.asarray(x[list(runtime.dependent_state_indices)], dtype=np.float64).tobytes()
            signature = (state_signature, input_signature)
            if (
                self._use_algebraic_cache
                and runtime.cache_signature == signature
                and runtime.cache_values is not None
            ):
                pressure[nodes] = runtime.cache_values
                solved_nodes.update(map(int, nodes))
                runtime.cache_hits += 1
                continue
            local = {int(global_index): i for i, global_index in enumerate(nodes)}

            def residual_jacobian(values: NDArray[np.float64]):
                residual = np.zeros(len(nodes), dtype=float)
                jacobian = np.zeros((len(nodes), len(nodes)), dtype=float)
                for global_index, local_index in local.items():
                    # Tiny reference conductance regularizes floating groups.
                    residual[local_index] += 1.0e-15 * (values[local_index] - self._pressure_reference_pa)
                    jacobian[local_index, local_index] += 1.0e-15
                    for dynamic_index, port_index in self.dynamic_by_junction[global_index]:
                        dynamic = self.dynamic_hydraulic[dynamic_index]
                        state_index = dynamic.state_indices[min(port_index, len(dynamic.state_indices) - 1)]
                        g = self._line_interface_conductance(dynamic) if dynamic.submodel in LINE_FAMILIES else dynamic.interface_conductance
                        residual[local_index] += g * (values[local_index] - x[state_index])
                        jacobian[local_index, local_index] += g
                for branch_index in runtime.branch_indices:
                    branch = self.branches[branch_index]
                    for left, right in self._branch_pairs(branch):
                        if left not in local and right not in local:
                            continue
                        pl = values[local[left]] if left in local else pressure[left]
                        pr = values[local[right]] if right in local else pressure[right]
                        flow, derivative = self._flow_and_derivative(branch, pl - pr, inputs)
                        if left in local:
                            i = local[left]; residual[i] += flow; jacobian[i, i] += derivative
                            if right in local: jacobian[i, local[right]] -= derivative
                        if right in local:
                            i = local[right]; residual[i] -= flow; jacobian[i, i] += derivative
                            if left in local: jacobian[i, local[left]] -= derivative
                for inlet, outlet, flow, _alias in pump_sources:
                    if inlet in local: residual[local[inlet]] += flow
                    if outlet in local: residual[local[outlet]] -= flow
                # TK000 is an ideal effort source, not a large finite
                # conductance. Override its balance row with the exact gauge
                # boundary constraint after all connected-flow contributions.
                for global_index, local_index in local.items():
                    if global_index in self.tank_nodes:
                        residual[local_index] = values[local_index] - self._pressure_reference_pa
                        jacobian[local_index, :] = 0.0
                        jacobian[local_index, local_index] = 1.0
                return residual, jacobian

            initial = pressure[nodes]
            values = runtime.solver.solve(residual_jacobian, initial)
            pressure[nodes] = values
            if self._use_algebraic_cache:
                runtime.cache_signature = signature
                runtime.cache_values = values.copy()
            solved_nodes.update(map(int, nodes))
            residual, _ = residual_jacobian(values)
            max_residual = max(max_residual, float(np.max(np.abs(residual))) if residual.size else 0.0)

        # Nodes outside a stateless algebraic group are explicit storage or
        # boundary nodes.
        for node in range(n):
            if node in solved_nodes:
                continue
            attached = self.dynamic_by_junction[node]
            if node in self.tank_nodes:
                pressure[node] = self._pressure_reference_pa
            elif attached:
                pressure[node] = float(np.mean([x[self.dynamic_hydraulic[d].state_indices[min(port, len(self.dynamic_hydraulic[d].state_indices) - 1)]] for d, port in attached]))

        for branch in self.branches:
            total = 0.0
            for left, right in self._branch_pairs(branch):
                flow, _ = self._flow_and_derivative(branch, pressure[left] - pressure[right], inputs)
                total += flow
            branch_flow[branch.alias] = total
        for inlet, outlet, flow, alias in pump_sources:
            branch_flow[alias] = flow
        success = all(runtime.solver is None or runtime.solver.diagnostics.failures == 0 for runtime in self.groups)
        solution = AlgebraicSolution(pressure, branch_flow, max_residual, success)
        self._last_algebraic = solution
        return solution

    def _param(self, alias: str, title: str, default: float) -> float:
        return _safe_float(self.parameters.get(alias, {}).get(title.lower()), default)

    def _cylinder_geometry(self, alias: str, submodel: str) -> tuple[float, float, float, float, float]:
        piston_d = self._param(alias, "piston diameter", 0.08)
        rod1 = self._param(alias, "rod diameter at port 1 end", 0.0 if submodel != "HJ021" else 0.012)
        rod2 = self._param(alias, "rod diameter at port 2 end", self._param(alias, "rod diameter", 0.04))
        # Parameter loader converts mm expressions only when numeric. Expressions
        # remain in mm and are evaluated here.
        if piston_d > 1.0: piston_d *= 1.0e-3
        if rod1 > 1.0: rod1 *= 1.0e-3
        if rod2 > 1.0: rod2 *= 1.0e-3
        a1 = math.pi * max(piston_d**2 - rod1**2, 1.0e-8) / 4.0
        a2 = math.pi * max(piston_d**2 - rod2**2, 1.0e-8) / 4.0
        stroke = self._param(alias, "length of stroke", 0.2)
        dead1 = self._param(alias, "dead volume at port 1 end", 50.0e-6)
        dead2 = self._param(alias, "dead volume at port 2 end", 50.0e-6)
        return a1, a2, stroke, dead1, dead2

    def rhs(self, t: float, x: NDArray[np.float64], inputs: Mapping[str, float] | None = None) -> NDArray[np.float64]:
        x = np.asarray(x, dtype=float)
        if x.shape != (109,):
            raise ValueError(f"FAST RHS requires 109 states, got {x.shape}")
        inputs = self._resolve_inputs(inputs, t)
        algebraic = self.solve_algebraic(t, x, inputs)
        dx = np.zeros_like(x)
        supplied = np.zeros(109, dtype=bool)

        mass_state: dict[str, tuple[int, int]] = {}
        for alias, submodel in self.element_submodel.items():
            if submodel not in {"MAS001", "MAS004"}:
                continue
            velocity_name = "v" if (alias, "v") in self.state_by_key else "v1"
            position_name = "x" if (alias, "x") in self.state_by_key else "x1"
            if (alias, velocity_name) in self.state_by_key and (alias, position_name) in self.state_by_key:
                mass_state[alias] = (self.state_by_key[(alias, position_name)], self.state_by_key[(alias, velocity_name)])

        cylinder_force_by_mech: dict[str, float] = {}
        cylinder_motion: dict[str, tuple[float, float]] = {}
        for dynamic in self.dynamic_hydraulic:
            if dynamic.submodel not in CYLINDER_FAMILIES:
                continue
            mech = self.mechanical_junction_by_alias.get(dynamic.alias, "")
            candidates = [a for a in self.aliases_by_mechanical_junction.get(mech, ()) if a in mass_state]
            if candidates:
                position_index, velocity_index = mass_state[candidates[0]]
                position, velocity = float(x[position_index]), float(x[velocity_index])
            else:
                position = velocity = 0.0
            cylinder_motion[dynamic.alias] = (position, velocity)
            a1, a2, _stroke, _dead1, _dead2 = self._cylinder_geometry(dynamic.alias, dynamic.submodel)
            force = a1 * x[dynamic.state_indices[0]] - a2 * x[dynamic.state_indices[1]]
            cylinder_force_by_mech[mech] = cylinder_force_by_mech.get(mech, 0.0) + force

        for dynamic in self.dynamic_hydraulic:
            state_indices = dynamic.state_indices
            junction_pressures = [algebraic.junction_pressure_pa[j] for j in dynamic.junction_indices]
            if dynamic.submodel in LINE_FAMILIES:
                state_pressures = x[list(state_indices)]
                count = len(state_indices)
                cell_volume = dynamic.volume_m3 / count
                flows = np.empty(count + 1, dtype=float)
                interface_g = self._line_interface_conductance(dynamic)
                flows[0] = interface_g * (junction_pressures[0] - state_pressures[0])
                internal_g = interface_g / max(count, 1)
                for i in range(1, count):
                    flows[i] = internal_g * (state_pressures[i - 1] - state_pressures[i])
                flows[-1] = interface_g * (state_pressures[-1] - junction_pressures[-1])
                for i, state_index in enumerate(state_indices):
                    dx[state_index] = dynamic.bulk_modulus_pa / cell_volume * (flows[i] - flows[i + 1])
                    supplied[state_index] = True
            elif dynamic.submodel in CYLINDER_FAMILIES:
                position, velocity = cylinder_motion[dynamic.alias]
                a1, a2, stroke, dead1, dead2 = self._cylinder_geometry(dynamic.alias, dynamic.submodel)
                v1 = dead1 + a1 * position
                v2 = dead2 + a2 * (stroke - position)
                q1 = dynamic.interface_conductance * (junction_pressures[0] - x[state_indices[0]])
                q2 = dynamic.interface_conductance * (junction_pressures[1] - x[state_indices[1]])
                leak_coeff = self._param(dynamic.alias, "leakage coefficient", 0.0)
                # L/min/bar -> m^3/(s Pa), if not converted by loader.
                if leak_coeff > 1.0e-10: leak_coeff *= 1.0 / 60000.0 / 1.0e5
                leak = leak_coeff * (x[state_indices[0]] - x[state_indices[1]])
                dx[state_indices[0]] = dynamic.bulk_modulus_pa / max(v1, 1.0e-8) * (q1 - a1 * velocity - leak)
                dx[state_indices[1]] = dynamic.bulk_modulus_pa / max(v2, 1.0e-8) * (q2 + a2 * velocity + leak)
                supplied[list(state_indices)] = True
            else:  # HA001
                q = dynamic.interface_conductance * (junction_pressures[0] - x[state_indices[0]])
                gamma = self._param(dynamic.alias, "polytropic index", 1.4)
                dx[state_indices[0]] = gamma * max(x[state_indices[0]] + 1.0e5, 1.0e4) * q / dynamic.volume_m3
                supplied[state_indices[0]] = True

        for alias, (position_index, velocity_index) in mass_state.items():
            mech = self.mechanical_junction_by_alias.get(alias, "")
            force = cylinder_force_by_mech.get(mech, 0.0) + float(inputs.get(f"{alias}.force_n", 0.0))
            mass = self._param(alias, "mass", 1000.0)
            damping = self._param(alias, "coefficient of viscous friction", 0.0)
            position, velocity = float(x[position_index]), float(x[velocity_index])
            strokes = [self._cylinder_geometry(a, self.element_submodel[a])[2] for a in self.aliases_by_mechanical_junction.get(mech, ()) if self.element_submodel.get(a) in CYLINDER_FAMILIES]
            end_force = 0.0
            if strokes:
                stroke = min(strokes)
                if position < 0.0: end_force += -1.0e7 * position - 1.0e5 * min(velocity, 0.0)
                if position > stroke: end_force += -1.0e7 * (position - stroke) - 1.0e5 * max(velocity, 0.0)
            dx[position_index] = velocity
            dx[velocity_index] = (force + end_force - damping * velocity) / max(mass, 1.0e-6)
            supplied[position_index] = supplied[velocity_index] = True

        for alias, submodel in self.element_submodel.items():
            if submodel != "PV00022":
                continue
            xi, vi = self.state_by_key[(alias, "x")], self.state_by_key[(alias, "v")]
            command = min(max(self._command(alias, inputs), 0.0), 1.0)
            wn, zeta = 50.0, 0.8
            dx[xi] = x[vi]
            dx[vi] = wn * wn * (command - x[xi]) - 2.0 * zeta * wn * x[vi]
            supplied[xi] = supplied[vi] = True

        if not np.all(supplied):
            missing = [f"{self.system.states[i].instance}.{self.system.states[i].state_name}" for i in np.flatnonzero(~supplied)]
            raise RuntimeError(f"FAST RHS entries not supplied: {missing}")
        self._rhs_entries_supplied = supplied
        return dx

    def initialize(self, inputs: Mapping[str, float] | None = None) -> tuple[NDArray[np.float64], AlgebraicSolution]:
        value = relax_pressure_states(self, self.initial_state, dict(inputs or {}), passes=4)
        solution = self.solve_algebraic(0.0, value, inputs)
        self.initial_state = value.copy()
        return value, solution

    def reset_diagnostics(self) -> None:
        for group in self.groups:
            if group.solver is not None:
                group.solver.reset()
            group.cache_signature = None
            group.cache_values = None
            group.evaluation_calls = 0
            group.cache_hits = 0

    def aggregate_algebraic_diagnostics(self) -> AlgebraicDiagnostics:
        result = AlgebraicDiagnostics()
        for group in self.groups:
            if group.solver is None:
                continue
            d = group.solver.diagnostics
            result.calls += d.calls; result.failures += d.failures
            result.total_iterations += d.total_iterations
            result.max_iterations = max(result.max_iterations, d.max_iterations)
            result.warm_start_hits += d.warm_start_hits
            result.total_wall_time_s += d.total_wall_time_s
            result.last_residual = max(result.last_residual, d.last_residual)
        return result

    def simulate(self, duration_s: float, inputs: Mapping[str, float] | None = None, *, method: str = "BDF", rtol: float = 1.0e-4, max_step: float | None = None, output_points: int = 101, use_jac_sparsity: bool | None = None) -> FastSimulationResult:
        if duration_s <= 0.0:
            raise ValueError("duration must be positive")
        self.reset_diagnostics()
        x0, _ = self.initialize(inputs)
        t_eval = np.linspace(0.0, duration_s, output_points)
        started = perf_counter()
        options = {}
        enable_sparsity = self._use_jacobian_sparsity if use_jac_sparsity is None else use_jac_sparsity
        if enable_sparsity and method in {"BDF", "Radau"}:
            if self._jacobian_sparsity is None:
                from .jacobian_sparsity import build_jacobian_sparsity
                self._jacobian_sparsity = build_jacobian_sparsity(self).matrix
            options["jac_sparsity"] = self._jacobian_sparsity
        solution = solve_ivp(lambda t, x: self.rhs(t, x, inputs), (0.0, duration_s), x0, method=method, rtol=rtol, atol=self.atol, max_step=max_step or duration_s / 20.0, t_eval=t_eval, **options)
        wall = perf_counter() - started
        return FastSimulationResult(solution.success, solution.message, solution.t, solution.y, wall, solution.nfev, solution.njev, solution.nlu, max(len(solution.t) - 1, 0))

    def outputs(self, t: float, x: NDArray[np.float64], algebraic: AlgebraicSolution | None = None, inputs: Mapping[str, float] | None = None) -> dict[str, float]:
        inputs = self._resolve_inputs(inputs, t)
        z = algebraic or self.solve_algebraic(t, x, inputs)
        result: dict[str, float] = {"time_s": float(t)}
        for alias in ("pump01", "pump01_1", "pump01_2", "pump01_3"):
            js = self.ports_by_alias.get(alias, ())
            if len(js) >= 2:
                speed = float(inputs.get(f"{alias}.speed_rad_s", inputs.get("pump_speed_rad_s", 1350.0 * 2.0 * math.pi / 60.0)))
                flow = z.branch_flow_m3_s.get(alias, 0.0)
                result.update({f"{alias}.speed_rad_s": speed, f"{alias}.flow_m3_s": flow, f"{alias}.pin_pa": z.junction_pressure_pa[js[0]], f"{alias}.pout_pa": z.junction_pressure_pa[js[1]], f"{alias}.torque_nm": (z.junction_pressure_pa[js[1]] - z.junction_pressure_pa[js[0]]) * 10.0 * 1.59154943091895e-7})
        for alias in ("actuator001", "actuator001_1", "actuator001_2", "actuator002", "springreturnactuator", "springreturnactuator_1", "springreturnactuator_2"):
            if (alias, "p1") not in self.state_by_key:
                continue
            p1, p2 = x[self.state_by_key[(alias, "p1")]], x[self.state_by_key[(alias, "p2")]]
            mech = self.mechanical_junction_by_alias.get(alias, "")
            masses = [a for a in self.aliases_by_mechanical_junction.get(mech, ()) if (a, "x") in self.state_by_key or (a, "x1") in self.state_by_key]
            position = velocity = 0.0
            if masses:
                mass = masses[0]
                xn = "x" if (mass, "x") in self.state_by_key else "x1"
                vn = "v" if (mass, "v") in self.state_by_key else "v1"
                position, velocity = x[self.state_by_key[(mass, xn)]], x[self.state_by_key[(mass, vn)]]
            a1, a2, *_ = self._cylinder_geometry(alias, self.element_submodel[alias])
            result.update({f"{alias}.p1_pa": p1, f"{alias}.p2_pa": p2, f"{alias}.force_n": a1 * p1 - a2 * p2, f"{alias}.position_m": position, f"{alias}.velocity_m_s": velocity})
        for alias, submodel in self.element_submodel.items():
            if submodel == "SC_1":
                result[f"{alias}.command"] = self._command(alias, inputs)
                result[f"{alias}.opening"] = min(max(self._command(alias, inputs), 0.0), 1.0)
                result[f"{alias}.flow_m3_s"] = z.branch_flow_m3_s.get(alias, 0.0)
        result["max_hydraulic_residual_m3_s"] = z.max_hydraulic_residual_m3_s
        return result
