from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.sparse import csr_matrix, lil_matrix
from scipy.sparse.csgraph import connected_components


@dataclass(frozen=True, slots=True)
class SparsityAnalysis:
    matrix: csr_matrix
    colors: tuple[int, ...]
    connected_blocks: int
    state_groups: tuple[tuple[str, ...], ...]


def _greedy_column_coloring(matrix: csr_matrix) -> tuple[int, ...]:
    """Color Jacobian columns that share a structurally nonzero row."""
    csc = matrix.tocsc()
    row_columns: list[list[int]] = [[] for _ in range(matrix.shape[0])]
    for column in range(matrix.shape[1]):
        for row in csc.indices[csc.indptr[column]:csc.indptr[column + 1]]:
            row_columns[int(row)].append(column)
    neighbors = [set() for _ in range(matrix.shape[1])]
    for columns in row_columns:
        for column in columns:
            neighbors[column].update(other for other in columns if other != column)
    order = sorted(range(matrix.shape[1]), key=lambda column: (-len(neighbors[column]), column))
    colors = [-1] * matrix.shape[1]
    for column in order:
        used = {colors[other] for other in neighbors[column] if colors[other] >= 0}
        color = 0
        while color in used:
            color += 1
        colors[column] = color
    return tuple(colors)


def build_jacobian_sparsity(model) -> SparsityAnalysis:
    size = len(model.system.states)
    pattern = lil_matrix((size, size), dtype=np.int8)
    pattern.setdiag(1)

    groups_by_node: dict[int, list[int]] = {}
    group_boundary_states: list[set[int]] = []
    for group_index, group in enumerate(model.groups):
        boundary: set[int] = set()
        for node in map(int, group.junction_indices):
            groups_by_node.setdefault(node, []).append(group_index)
            for dynamic_index, port_index in model.dynamic_by_junction[node]:
                dynamic = model.dynamic_hydraulic[dynamic_index]
                boundary.add(dynamic.state_indices[min(port_index, len(dynamic.state_indices) - 1)])
        group_boundary_states.append(boundary)

    group_neighbors = [set() for _ in model.groups]
    for branch in model.branches:
        touched = sorted({group_index for node in branch.junction_indices for group_index in groups_by_node.get(int(node), ())})
        for left in touched:
            group_neighbors[left].update(right for right in touched if right != left)
    closed_boundaries: list[set[int]] = []
    for start in range(len(model.groups)):
        component = {start}
        pending = [start]
        while pending:
            current = pending.pop()
            for neighbor in group_neighbors[current] - component:
                component.add(neighbor); pending.append(neighbor)
        closed_boundaries.append(set().union(*(group_boundary_states[index] for index in component)))
    group_boundary_states = closed_boundaries

    state_groups: list[set[str]] = [set() for _ in range(size)]
    for group_index, group in enumerate(model.groups):
        for state_index in group_boundary_states[group_index]:
            state_groups[state_index].add(group.group_id)

    # Hydraulic storage equations depend on their own local cells and on the
    # boundary states of only the algebraic groups attached to their ports.
    for dynamic in model.dynamic_hydraulic:
        own = set(dynamic.state_indices)
        endpoint_dependencies: set[int] = set(own)
        affected_groups: set[str] = set()
        for node in dynamic.junction_indices:
            attached_groups = groups_by_node.get(node, ())
            for group_index in attached_groups:
                endpoint_dependencies.update(group_boundary_states[group_index])
                affected_groups.add(model.groups[group_index].group_id)
            if not attached_groups:
                # Explicit storage-only junction: pressure is the mean of all
                # attached storage boundary states.
                for dynamic_index, port_index in model.dynamic_by_junction[node]:
                    neighbor = model.dynamic_hydraulic[dynamic_index]
                    endpoint_dependencies.add(neighbor.state_indices[min(port_index, len(neighbor.state_indices) - 1)])
        for row in dynamic.state_indices:
            pattern[row, sorted(endpoint_dependencies)] = 1
            state_groups[row].update(affected_groups)

    # Mechanical transformer blocks are local to a mechanical 1-junction.
    states_by_alias: dict[str, list[int]] = {}
    for state in model.system.states:
        states_by_alias.setdefault(state.instance, []).append(state.index)
    for aliases in model.aliases_by_mechanical_junction.values():
        local = sorted({index for alias in aliases for index in states_by_alias.get(alias, ())})
        for row in local:
            pattern[row, local] = 1

    # Second-order valve states are isolated 2x2 blocks.
    for alias, submodel in model.element_submodel.items():
        if submodel == "PV00022":
            local = [model.state_by_key[(alias, "x")], model.state_by_key[(alias, "v")]]
            pattern[local, :][:, local] = 1
            for row in local:
                pattern[row, local] = 1

    matrix = pattern.tocsr()
    symmetric = ((matrix + matrix.T) > 0).astype(np.int8)
    blocks, _ = connected_components(symmetric, directed=False)
    colors = _greedy_column_coloring(matrix)
    return SparsityAnalysis(matrix, colors, int(blocks), tuple(tuple(sorted(groups)) for groups in state_groups))


def structural_violations(
    model,
    state: np.ndarray,
    inputs: dict[str, float],
    analysis: SparsityAnalysis,
    relative_threshold: float = 1.0e-7,
) -> list[tuple[int, int, float]]:
    """Return finite-difference nonzeros missing from the structural pattern."""
    base = model.rhs(0.0, state, inputs)
    dense_pattern = analysis.matrix.toarray().astype(bool)
    violations: list[tuple[int, int, float]] = []
    for column in range(len(state)):
        step = 1.0e-7 * max(abs(float(state[column])), float(model.state_scale[column]), 1.0)
        perturbed = state.copy(); perturbed[column] += step
        derivative = (model.rhs(0.0, perturbed, inputs) - base) / step
        threshold = relative_threshold * np.maximum(1.0, np.abs(base)) / max(float(model.state_scale[column]), 1.0)
        for row in np.flatnonzero((np.abs(derivative) > threshold) & ~dense_pattern[:, column]):
            violations.append((int(row), column, float(derivative[row])))
    return violations
