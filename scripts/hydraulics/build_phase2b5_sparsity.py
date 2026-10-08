from __future__ import annotations

import csv
import sys
from pathlib import Path

import numpy as np
from scipy.sparse import save_npz


ROOT = Path(__file__).resolve().parents[2]
AUDIT = ROOT / "hydraulic_audit"
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from steering_sim.hydraulics.solver import FastHydraulicModel
from steering_sim.hydraulics.solver.jacobian_sparsity import build_jacobian_sparsity, structural_violations


def write(name: str, rows: list[dict[str, object]], fields: list[str]) -> None:
    with (AUDIT / name).open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader(); writer.writerows(rows)


def main() -> None:
    model = FastHydraulicModel.from_ir(AUDIT)
    analysis = build_jacobian_sparsity(model)
    state, _ = model.initialize({"pump_speed_rad_s": 0.0, "valve_command": 0.2})
    violations = structural_violations(model, state, {"pump_speed_rad_s": 0.0, "valve_command": 0.2}, analysis)
    if violations:
        sample = ", ".join(f"J[{row},{column}]={value:.3g}" for row, column, value in violations[:10])
        raise SystemExit(f"Jacobian sparsity misses {len(violations)} finite-difference dependencies: {sample}")
    save_npz(AUDIT / "19C_jacobian_sparsity.npz", analysis.matrix)
    color_rows = []
    for color in range(max(analysis.colors) + 1):
        indices = [index for index, assigned in enumerate(analysis.colors) if assigned == color]
        color_rows.append({"color_id": color, "state_indices": ";".join(map(str, indices)), "state_count": len(indices)})
    write("19D_jacobian_coloring.csv", color_rows, ["color_id", "state_indices", "state_count"])
    dependency_rows = []
    for state, groups in zip(model.system.states, analysis.state_groups):
        dependency_rows.append({"state_index": state.index, "instance": state.instance, "state": state.state_name, "affected_algebraic_groups": ";".join(groups), "group_count": len(groups)})
    write("19E_state_algebraic_dependency.csv", dependency_rows, ["state_index", "instance", "state", "affected_algebraic_groups", "group_count"])
    print(f"SHAPE = {analysis.matrix.shape}")
    print(f"NONZEROS = {analysis.matrix.nnz}")
    print(f"DENSITY = {100.0 * analysis.matrix.nnz / (109 * 109):.6f}%")
    print(f"CONNECTED BLOCKS = {analysis.connected_blocks}")
    print(f"COLORS = {max(analysis.colors) + 1}")
    print("FINITE DIFFERENCE STRUCTURAL VIOLATIONS = 0")


if __name__ == "__main__":
    main()
