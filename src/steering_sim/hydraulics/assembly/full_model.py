from __future__ import annotations

import csv
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

import numpy as np
from numpy.typing import NDArray

from .element_factory import ElementFactory, RuntimeElement
from .junction_factory import JunctionFactory, RuntimeJunction
from .parameter_loader import ParameterDatabase
from .signal_factory import SignalGraph
from .state_mapper import StateIndex, StateMapper


def _read(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


@dataclass(frozen=True, slots=True)
class AlgebraicGroup:
    group_id: str
    elements: tuple[str, ...]
    junctions: tuple[str, ...]
    unknown_count: int
    solver_method: str


@dataclass(frozen=True, slots=True)
class HydraulicSystem:
    elements: tuple[RuntimeElement, ...]
    junctions: tuple[RuntimeJunction, ...]
    ports: tuple[dict[str, str], ...]
    signal_graph: SignalGraph
    states: tuple[StateIndex, ...]
    parameters: ParameterDatabase
    algebraic_groups: tuple[AlgebraicGroup, ...]
    fidelity_mode: str

    @classmethod
    def from_ir(cls, audit_dir: str | Path, line_fidelity: str = "fast") -> "HydraulicSystem":
        root = Path(audit_dir)
        if line_fidelity not in {"full", "fast"}:
            raise ValueError("line_fidelity must be 'full' or 'fast'")
        element_rows = _read(root / "17A_bondgraph_elements_v3.csv")
        port_rows = _read(root / "17B_bondgraph_ports_v3.csv")
        junction_rows = _read(root / "17C_bondgraph_junctions_v3.csv")
        signal_rows = _read(root / "12D_bondgraph_signal_links_v2.csv")
        parameters = ParameterDatabase.load(root / "04_parameters.csv", root / "03_global_parameters.csv")
        factory = ElementFactory(parameters)
        elements = tuple(factory.create(row) for row in element_rows)
        junctions = tuple(JunctionFactory.create(row) for row in junction_rows)
        signal_graph = SignalGraph.build(signal_rows)
        states = StateMapper.full(root / "11A_state_variable_registry.csv") if line_fidelity == "full" else StateMapper.fast(root / "11A_state_variable_registry.csv", root / "17G_fast_line_reduction_map.csv")
        groups = cls._identify_algebraic_groups(elements, port_rows)
        system = cls(elements, junctions, tuple(port_rows), signal_graph, states, parameters, groups, line_fidelity.upper())
        system.validate()
        return system

    @staticmethod
    def _identify_algebraic_groups(elements: tuple[RuntimeElement, ...], ports: list[dict[str, str]]) -> tuple[AlgebraicGroup, ...]:
        owner = {element.element_id: element for element in elements}
        stateless = {element.element_id for element in elements if element.active_power and not element.original_state_names}
        by_junction: dict[str, set[str]] = defaultdict(set)
        for port in ports:
            if port["element_id"] in stateless:
                by_junction[port["connected_junction"]].add(port["element_id"])
        adjacency: dict[str, set[str]] = defaultdict(set)
        for junction, ids in by_junction.items():
            junction_node = "J:" + junction
            for element_id in ids:
                element_node = "E:" + element_id
                adjacency[junction_node].add(element_node)
                adjacency[element_node].add(junction_node)
        groups: list[AlgebraicGroup] = []
        seen: set[str] = set()
        for start in sorted(adjacency):
            if start in seen:
                continue
            stack, component = [start], set()
            while stack:
                node = stack.pop()
                if node in component:
                    continue
                component.add(node)
                stack.extend(adjacency[node] - component)
            seen |= component
            element_ids = sorted(node[2:] for node in component if node.startswith("E:"))
            junction_ids = sorted(node[2:] for node in component if node.startswith("J:"))
            if not element_ids:
                continue
            aliases = tuple(owner[element_id].instance_alias for element_id in element_ids)
            groups.append(AlgebraicGroup(f"AG_{len(groups) + 1:03d}", aliases, tuple(junction_ids), len(junction_ids), "local damped Newton" if len(junction_ids) > 1 else "explicit/one-dimensional root"))
        return tuple(groups)

    def validate(self) -> None:
        element_ids = {element.element_id for element in self.elements}
        junction_ids = {junction.junction_id for junction in self.junctions}
        if len(element_ids) != len(self.elements):
            raise ValueError("duplicate element id")
        if len({state.index for state in self.states}) != len(self.states):
            raise ValueError("duplicate state index")
        missing_elements = {port["element_id"] for port in self.ports} - element_ids
        if missing_elements:
            raise ValueError(f"ports reference missing elements: {sorted(missing_elements)}")
        missing_junctions = {port["connected_junction"] for port in self.ports} - junction_ids
        if missing_junctions:
            raise ValueError(f"ports reference missing junctions: {sorted(missing_junctions)}")


@dataclass(frozen=True, slots=True)
class FullHydraulicModel:
    system: HydraulicSystem
    _state_owner_index: NDArray[np.int64]

    @classmethod
    def from_ir(cls, audit_dir: str | Path, line_fidelity: str = "fast") -> "FullHydraulicModel":
        system = HydraulicSystem.from_ir(audit_dir, line_fidelity=line_fidelity)
        owner_by_alias = {element.instance_alias: index for index, element in enumerate(system.elements)}
        owner_index = np.asarray([owner_by_alias[state.instance] for state in system.states], dtype=np.int64)
        return cls(system, owner_index)

    def solve_algebraic(self, _t: float, _x: NDArray[np.float64], inputs: Mapping[str, object] | None = None) -> dict[str, float]:
        # Phase 2-A freezes group structure.  Phase 2-B supplies the numeric
        # local Newton kernels.  Explicit caller-provided guesses are retained.
        guesses = {} if inputs is None else dict(inputs.get("junction_pressure_pa", {}))
        return {junction.junction_id: float(guesses.get(junction.junction_id, 0.0)) for junction in self.system.junctions if junction.domain == "hydraulic"}

    def rhs(self, t: float, x: NDArray[np.float64], inputs: Mapping[str, object] | None = None) -> NDArray[np.float64]:
        state = np.asarray(x, dtype=float)
        if state.shape != (len(self.system.states),):
            raise ValueError(f"expected state vector shape {(len(self.system.states),)}, got {state.shape}")
        self.solve_algebraic(t, state, inputs)
        # A precompiled per-state override keeps Phase 2-A executable without
        # pretending that Phase 2-B's network flow solve is already complete.
        supplied = {} if inputs is None else dict(inputs.get("state_rhs", {}))
        derivative = np.zeros_like(state)
        for item in self.system.states:
            derivative[item.index] = float(supplied.get(f"{item.instance}.{item.state_name}", 0.0))
        return derivative
