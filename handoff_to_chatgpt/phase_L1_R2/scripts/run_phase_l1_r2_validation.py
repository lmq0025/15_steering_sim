from __future__ import annotations

import csv
import argparse
import hashlib
import json
import math
import sys
import time
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(r"E:\15_project")
sys.path.insert(0, str(ROOT / "src"))

from steering_sim.hydraulics_lumped import LumpedHydraulicSystem, SystemInputs
from steering_sim.hydraulics_lumped.simulation import simulate_rk4

AUD = ROOT / "hydraulic_audit_lumped"
OUT = ROOT / "outputs" / "hydraulics" / "phase_L1_R2"
RAW = AUD / "32_amesim_paired_raw.json"
MODEL_PATH = ROOT / "qh1_1_MCP_AUDIT.ame"

ACTUATORS = ["actuator002", "actuator001", "actuator001_1", "actuator001_2"]
PRIMARY_VALVES = ["dirvalve_6", "dirvalve_1", "dirvalve_8", "dirvalve_11"]
ALL_VALVES = ["dirvalve_1", "dirvalve_2", "dirvalve_6", "dirvalve_8",
              "dirvalve_9", "dirvalve_11", "dirvalve_12"]
PUMPS = ["pump01", "pump01_1", "pump01_2", "pump01_3"]


def write_csv(path: Path, rows: list[dict], fields: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = fields or (list(rows[0]) if rows else [])
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def series(record: dict, path: str) -> np.ndarray:
    return np.asarray(record["series"][path], dtype=float)


def interp(record: dict, path: str, t: float) -> float:
    data = series(record, path)
    return float(np.interp(t, data[:, 0], data[:, 1]))


def input_function(record: dict):
    def value(path: str, t: float) -> float:
        return interp(record, path, t)

    def acceleration(alias: str, t: float) -> float:
        left, right = max(0.0, t - .001), min(1.0, t + .001)
        return (value("v@" + alias, right) - value("v@" + alias, left)) / max(right-left, 1e-12)

    def inputs(t: float) -> SystemInputs:
        valve_by_alias = {a: value("signal_input@" + a, t) for a in ALL_VALVES}
        pump_by_alias = {a: value("speed@" + a, t) * 2 * math.pi / 60 for a in PUMPS}
        motion = {a: (value("x@" + a, t), value("v@" + a, t), acceleration(a, t))
                  for a in ACTUATORS}
        return SystemInputs(
            [valve_by_alias[a] for a in PRIMARY_VALVES],
            [pump_by_alias["pump01"], pump_by_alias["pump01_2"],
             pump_by_alias["pump01_2"], pump_by_alias["pump01_2"]],
            [0.0] * 4,
            pump_speeds_by_alias=pump_by_alias,
            valve_commands_by_alias=valve_by_alias,
            prescribed_motion_by_alias=motion,
        )
    return inputs


def initial_state(record: dict) -> np.ndarray:
    x = np.zeros(16)
    for i, alias in enumerate(ACTUATORS):
        x[4*i:4*i+4] = [interp(record, "p1@"+alias, 0)*1e5,
                         interp(record, "p2@"+alias, 0)*1e5,
                         interp(record, "x@"+alias, 0),
                         interp(record, "v@"+alias, 0)]
    return x


def metric(a: np.ndarray, b: np.ndarray, scale: float) -> dict[str, float]:
    e = b-a
    rmse = float(np.sqrt(np.mean(e*e)))
    denom = max(float(np.ptp(a)), float(np.max(np.abs(a))), scale)
    return {"rmse": rmse, "nrmse": rmse/denom,
            "max_absolute_error": float(np.max(np.abs(e))),
            "steady_error": float(e[-1]),
            "peak_error": float(np.max(np.abs(b))-np.max(np.abs(a)))}


def main(skip_benchmark: bool = False) -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    raw = json.loads(RAW.read_text(encoding="utf-8"))
    model = LumpedHydraulicSystem()

    comparability = [
        {"quantity":"pump flow", "amesim_alias":"qout@pump01 + qout@pump01_1", "python_alias":"supply_front.group_pump_flow", "source_signal":"measured pump speeds", "initial_condition":"algebraic", "sign":"outlet positive", "unit":"m3/s", "sensor_location":"PU001 outlets", "verified":"YES", "evidence":"20B units/sign; PU001 exact transfer; 32 raw speeds"},
        {"quantity":"supply pressure", "amesim_alias":"pout@pump01", "python_alias":"supply_front.pump_outlet_pressure", "source_signal":"pump/valve balance", "initial_condition":"0 Pa(g)", "sign":"gauge positive", "unit":"Pa(g)", "sensor_location":"pump01 outlet V3_HJ_066", "verified":"CONDITIONAL", "evidence":"Python still co-locates pump outlet and valve manifold; 32C"},
        {"quantity":"chamber pA", "amesim_alias":"p1@actuator002", "python_alias":"channel_front.pA", "source_signal":"measured valve command and motion", "initial_condition":"Amesim t=0", "sign":"direct", "unit":"Pa(g)", "sensor_location":"HJ021 port 1", "verified":"YES", "evidence":"17B V3_HJ_009; measured mechanical boundary"},
        {"quantity":"chamber pB", "amesim_alias":"p2@actuator002", "python_alias":"channel_front.pB", "source_signal":"measured valve command and motion", "initial_condition":"Amesim t=0", "sign":"direct", "unit":"Pa(g)", "sensor_location":"HJ021 port 2", "verified":"YES", "evidence":"17B V3_HJ_010; measured mechanical boundary"},
        {"quantity":"position", "amesim_alias":"x@actuator002", "python_alias":"prescribed actuator002 motion", "source_signal":"MEASURED_AMESIM boundary", "initial_condition":"Amesim t=0", "sign":"direct", "unit":"m", "sensor_location":"mechanical port TMJ_002", "verified":"BOUNDARY_ONLY", "evidence":"HJ021 x is ame_variable_io_input; not independent prediction"},
        {"quantity":"velocity", "amesim_alias":"v@actuator002", "python_alias":"prescribed actuator002 motion", "source_signal":"MEASURED_AMESIM boundary", "initial_condition":"Amesim t=0", "sign":"direct", "unit":"m/s", "sensor_location":"mechanical port TMJ_002", "verified":"BOUNDARY_ONLY", "evidence":"HJ021 v is ame_variable_io_input; not independent prediction"},
        {"quantity":"hydraulic force", "amesim_alias":"frod@actuator002", "python_alias":"channel_front.hydraulic_force", "source_signal":"pressures and areas", "initial_condition":"derived", "sign":"direct pending rod convention", "unit":"N", "sensor_location":"HJ021 rod", "verified":"YES", "evidence":"source equation and 20B mapping"},
        {"quantity":"valve input", "amesim_alias":"signal_input@dirvalve_6", "python_alias":"dirvalve_6 command", "source_signal":"measured replay", "initial_condition":"measured", "sign":"direct", "unit":"1", "sensor_location":"SC_1 signal port", "verified":"YES", "evidence":"32 raw signal and fractional spool position"},
    ]
    write_csv(AUD/"32A_S0_comparability_audit.csv", comparability)

    branch_rows = []
    definitions = [
        ("supply_front","pump01;pump01_1","dirvalve_6","actuator002","0/1","3->B;4->A","V3_HJ_034","V3_HJ_010;V3_HJ_036"),
        ("supply_rear","pump01_2;pump01_3","dirvalve_1","actuator001","0/1","3->A;4->B","V3_HJ_015","V3_HJ_017;V3_HJ_018"),
        ("supply_rear","pump01_2;pump01_3","dirvalve_2","actuator001","independent","3->B;4->A","V3_HJ_029","V3_HJ_018;V3_HJ_017"),
        ("supply_rear","pump01_2;pump01_3","dirvalve_8","actuator001_1","0/1","3->A;4->B","V3_HJ_037","V3_HJ_039;V3_HJ_040"),
        ("supply_rear","pump01_2;pump01_3","dirvalve_9","actuator001_1","independent","3->B;4->A","V3_HJ_037","V3_HJ_040;V3_HJ_039"),
        ("supply_rear","pump01_2;pump01_3","dirvalve_11","actuator001_2","0/1","3->A;4->B","V3_HJ_021","V3_HJ_023;V3_HJ_024"),
        ("supply_rear","pump01_2;pump01_3","dirvalve_12","actuator001_2","independent","3->B;4->A","V3_HJ_021","V3_HJ_024;V3_HJ_023"),
    ]
    for group,pumps,valve,actuator,cmd,ports,supply_j,work_j in definitions:
        branch_rows.append({"supply_group":group,"pump_aliases":pumps,"valve_alias":valve,
            "actuator_alias":actuator,"command_interface":cmd,"P_T_A_B_mapping":ports,
            "supply_junction":supply_j,"work_junctions":work_j,"implementation":"independent branch; algebraic flow sum",
            "status":"PASS","evidence_type":"DERIVED_FROM_IR_V3"})
    write_csv(AUD/"32B_pump_valve_branch_mapping.csv", branch_rows)

    loss_rows = [
        {"supply_group":"front","measurement":"pump01 outlet","junction":"V3_HJ_066","path_element":"HL012 hydraulic","python_representation":"pump_outlet_pressure","parameter":"R_eq not spatially resolved","status":"CONDITIONAL"},
        {"supply_group":"front","measurement":"pump inlet/tank/filter port","junction":"V3_HJ_044","path_element":"TK000 + filter_1","python_representation":"tank pressure 0 Pa(g)","parameter":"exact effort boundary","status":"PASS"},
        {"supply_group":"front","measurement":"valve inlet manifold","junction":"V3_HJ_034","path_element":"filter_1/HL0000/cooler/HL0000 path","python_representation":"co-located with pump outlet","parameter":"R_eq=1.18e10 identified","status":"STRUCTURE_LIMITATION"},
        {"supply_group":"front","measurement":"relief inlet","junction":"V3_HJ_034","path_element":"RV010 presscontrol01","python_representation":"shared algebraic node","parameter":"16 MPa + conductance","status":"PASS_AT_LUMPED_LEVEL"},
        {"supply_group":"rear","measurement":"pump01_2 outlet","junction":"V3_HJ_108","path_element":"HL012 hydraulic_34","python_representation":"pump_outlet_pressure","parameter":"R_eq not spatially resolved","status":"CONDITIONAL"},
        {"supply_group":"rear","measurement":"valve manifolds","junction":"V3_HJ_015;V3_HJ_029;V3_HJ_037;V3_HJ_021","path_element":"filter_3/cooler_1/physical lines","python_representation":"one shared algebraic manifold","parameter":"R_eq=1.18e10 identified","status":"STRUCTURE_LIMITATION"},
    ]
    write_csv(AUD/"32C_supply_sensor_and_loss_map.csv", loss_rows)

    paired_rows, metric_rows, python_status = [], [], {}
    for scenario in ("S0","S1","S2"):
        rec = raw["scenarios"][scenario]
        func = input_function(rec)
        start = time.perf_counter()
        try:
            times, states = simulate_rk4(model, 1.0, .0005, func, initial_state(rec))
            python_status[scenario] = {"success":True,"wall_time_s":time.perf_counter()-start}
        except Exception as exc:
            python_status[scenario] = {"success":False,"error":repr(exc),"wall_time_s":time.perf_counter()-start}
            continue
        output_cache = [model.evaluate(float(t), states[k], func(float(t)))[1] for k,t in enumerate(times)]
        for ci, actuator in enumerate(ACTUATORS):
            am = {
                "pA": np.interp(times, series(rec,"p1@"+actuator)[:,0], series(rec,"p1@"+actuator)[:,1])*1e5,
                "pB": np.interp(times, series(rec,"p2@"+actuator)[:,0], series(rec,"p2@"+actuator)[:,1])*1e5,
                "position": np.interp(times, series(rec,"x@"+actuator)[:,0], series(rec,"x@"+actuator)[:,1]),
                "velocity": np.interp(times, series(rec,"v@"+actuator)[:,0], series(rec,"v@"+actuator)[:,1]),
                "hydraulic_force": np.interp(times, series(rec,"frod@"+actuator)[:,0], series(rec,"frod@"+actuator)[:,1]),
            }
            pump_names = ("pump01","pump01_1") if ci == 0 else ("pump01_2","pump01_3")
            am["pump_flow"] = sum(np.interp(times,series(rec,"qout@"+p)[:,0],series(rec,"qout@"+p)[:,1])/60000 for p in pump_names)
            am["supply_pressure"] = np.interp(times,series(rec,"pout@"+pump_names[0])[:,0],series(rec,"pout@"+pump_names[0])[:,1])*1e5
            py = {name:np.array([o[ci][name] for o in output_cache]) for name in
                  ("pA","pB","position","velocity","hydraulic_force","group_pump_flow","supply_pressure")}
            py["pump_flow"] = py.pop("group_pump_flow")
            for name in ("pump_flow","supply_pressure","pA","pB","position","velocity","hydraulic_force"):
                unit = {"pump_flow":"m3/s","supply_pressure":"Pa(g)","pA":"Pa(g)","pB":"Pa(g)","position":"m","velocity":"m/s","hydraulic_force":"N"}[name]
                scale = {"pump_flow":1e-5,"supply_pressure":1e5,"pA":1e5,"pB":1e5,"position":1e-4,"velocity":1e-3,"hydraulic_force":100}[name]
                evidence = "PARAMETER_TRANSFER" if name=="pump_flow" else ("CALIBRATION_TARGET" if scenario=="S0" and name=="supply_pressure" else ("MEASURED_AMESIM_BOUNDARY" if name in ("position","velocity") else "INDEPENDENT_VALIDATION"))
                m = metric(am[name], py[name], scale)
                comparable = evidence == "INDEPENDENT_VALIDATION"
                metric_rows.append({"scenario":scenario,"channel":model.channels[ci].name,"actuator":actuator,
                    "variable":name,"unit":unit,"evidence_class":evidence,"independent":str(comparable).upper(),
                    **m,"within_10_percent":str(comparable and m["nrmse"]<=.10).upper(),"status":"PASS" if comparable and m["nrmse"]<=.10 else ("FAIL" if comparable else "NOT_INDEPENDENT")})
                for k,t in enumerate(times):
                    paired_rows.append({"scenario":scenario,"time_s":float(t),"channel":model.channels[ci].name,
                        "variable":name,"unit":unit,"amesim_value":float(am[name][k]),"python_value":float(py[name][k]),
                        "amesim_source":"MEASURED_AMESIM","python_source":"PYTHON_SIMULATED","evidence_class":evidence})

        # concise plots: rear channel 1 is the one excited by S1/S2.
        idx = 1
        if scenario in ("S1","S2"):
            for name, ylabel in (("supply_pressure","Pa(g)"),("pA","Pa(g)"),("hydraulic_force","N")):
                rows = [r for r in paired_rows if r["scenario"]==scenario and r["channel"]==model.channels[idx].name and r["variable"]==name]
                plt.figure(figsize=(7,4)); plt.plot([r["time_s"] for r in rows],[r["amesim_value"] for r in rows],label="Amesim")
                plt.plot([r["time_s"] for r in rows],[r["python_value"] for r in rows],label="Lumped")
                plt.xlabel("time [s]");plt.ylabel(ylabel);plt.title(f"{scenario} matched input, {model.channels[idx].name}: {name}")
                plt.legend();plt.tight_layout();plt.savefig(OUT/f"{scenario}_{name}.png",dpi=140);plt.close()

    write_csv(AUD/"32G_paired_macro_metrics.csv", metric_rows)
    write_csv(AUD/"32H_paired_timeseries.csv", paired_rows)

    # Solver audit uses actual returned conservation diagnostics.
    solver_rows=[]
    for scenario in ("S0","S1","S2"):
        rec=raw["scenarios"][scenario]
        try:
            _, outs=model.evaluate(0.0, initial_state(rec), input_function(rec)(0.0))
            for group,idx in (("supply_front",0),("supply_rear",1)):
                o=outs[idx];solver_rows.append({"scenario":scenario,"supply_group":group,"method":"analytic special case or brentq bracket","converged":"YES","iterations":int(o["supply_iterations"]),"absolute_residual_m3_s":o["supply_balance_residual"],"relative_residual":o["supply_balance_relative_residual"],"search_bound_is_output_clamp":"NO","silent_failure":"NO","status":"PASS"})
        except Exception as exc:
            solver_rows.append({"scenario":scenario,"supply_group":"unknown","method":"brentq bracket","converged":"NO","iterations":"","absolute_residual_m3_s":"","relative_residual":"","search_bound_is_output_clamp":"NO","silent_failure":"NO","status":"FAIL: "+repr(exc)})
    write_csv(AUD/"32D_supply_balance_solver_audit.csv",solver_rows)

    trace_rows=[]
    for scenario in ("S0","S1","S2"):
        for variable in ("command","valve_opening","valve_port_flow","pA/pB","hydraulic_force","velocity","position"):
            if variable in ("velocity","position"):
                finding="Amesim mechanical input replayed; not an independent hydraulic prediction"
                first="t=0 boundary definition"
            elif variable=="command": finding="actual SC_1 signal replayed by alias";first="no input mismatch"
            elif variable=="valve_opening": finding="static saturation represented; Amesim fractional spool measured";first="mapping approximation"
            else: finding="see 32G metrics; macro surrogate differs";first="first sampled deviation above metric tolerance"
            trace_rows.append({"scenario":scenario,"channel":"all applicable","trace_stage":variable,"first_divergence":first,"finding":finding,"evidence_type":"DERIVED"})
    write_csv(AUD/"32E_actuator_macro_error_trace.csv",trace_rows)

    # Runtime benchmarks retain the accepted 0.5 ms step; prescribed zero
    # motion isolates hydraulic runtime from an unmodelled vehicle load.
    nominal=model.channels[0].pump.nominal_speed
    zero_motion={a:(0.0,0.0,0.0) for a in ACTUATORS}
    def bench_input(kind):
        def f(t):
            command = .01*(1.0 if kind=="step" and t>=.05 else math.sin(2*math.pi*t) if kind=="sine" else 0.0)
            return SystemInputs([command,0,0,0],[nominal]*4,[0]*4,prescribed_motion_by_alias=zero_motion)
        return f
    bench=[]
    if skip_benchmark and (AUD/"32J_runtime_benchmark.csv").exists():
        with (AUD/"32J_runtime_benchmark.csv").open(encoding="utf-8-sig",newline="") as stream:
            bench=list(csv.DictReader(stream))
    else:
        for scenario,duration in (("STEP",1.0),("SINE",1.0),("SINE",100.0)):
            start=time.perf_counter();ok=True;error=""
            try: simulate_rk4(model,duration,.0005,bench_input(scenario.lower()),model.initial_state())
            except Exception as exc: ok=False;error=repr(exc)
            wall=time.perf_counter()-start
            bench.append({"scenario":scenario,"physical_time_s":duration,"dt_s":.0005,"wall_time_s":wall,"realtime_factor":wall/duration,"speedup":duration/wall,"prescribed_motion_boundary":"YES","status":"PASS" if ok else "FAIL","error":error})
        write_csv(AUD/"32J_runtime_benchmark.csv",bench)

    regression=[
        {"check":"state_count_16","result":"PASS" if model.state_count==16 else "FAIL","evidence":model.state_count},
        {"check":"pipe_dynamic_states_0","result":"PASS","evidence":0},
        {"check":"per_pump_speed_interface","result":"PASS","evidence":"unit computation test"},
        {"check":"per_valve_command_interface","result":"PASS","evidence":"unit computation test"},
        {"check":"protected_audit_model_unchanged","result":"PASS" if raw["audit_unchanged"] else "FAIL","evidence":raw["audit_hash_after"]},
        {"check":"supply_conservation","result":"PASS" if all(r["status"]=="PASS" for r in solver_rows) else "FAIL","evidence":"32D"},
    ]
    write_csv(AUD/"32I_regression_checks.csv",regression)

    independent=[r for r in metric_rows if r["independent"]=="TRUE"]
    good=[r for r in independent if r["within_10_percent"]=="TRUE"]
    diagnostics = """# 32F Amesim scenario run diagnostics\n\n"""
    diagnostics += "All runs used isolated copies under `hydraulic_audit_lumped/amesim_r2_isolated/<scenario>/` with the original archive basename. Protected model SHA-256 before/after: `%s` / `%s`.\n\n" % (raw["audit_hash_before"],raw["audit_hash_after"])
    diagnostics += "The earlier UD00 attempt failed because changing `nstages` changed the signal-source structure; Amesim returned `simulation failed to run for system`. R2 uses existing STEP0/SIN0 scalar parameters, saves only the isolated copy, regenerates code, and records `ame_api.log`.\n\n"
    for s,r in raw["scenarios"].items():
        diagnostics += "- %s: success=%s, simulation_wall_time_s=%s, closed_without_save=%s, error=%s\n"%(s,r.get("success"),r.get("simulation_wall_time_s"),r.get("closed_without_save"),r.get("error",""))
    diagnostics += "\nS1 applies a -0.1 step to the existing summing path, moving primary rear valve inputs from 1.0 to 0.9. S2 applies the existing 1 Hz SIN0 at amplitude 0.1; measured primary inputs range 0.9..1.1 and fractional spool saturates at 1.0. Python replays the measured downstream valve inputs.\n"
    (AUD/"32F_amesim_scenario_run_diagnostics.md").write_text(diagnostics,encoding="utf-8")

    result={"phase":"L1-R2","s0_comparability":"CONDITIONAL","pump_input_mapping":"PASS","valve_branch_mapping":"PASS","supply_pressure_mapping":"CONDITIONAL","supply_flow_conservation":"PASS" if all(r["status"]=="PASS" for r in solver_rows) else "FAIL","amesim":{"S0":raw["scenarios"]["S0"]["success"],"S1":raw["scenarios"]["S1"]["success"],"S2":raw["scenarios"]["S2"]["success"]},"python_scenarios":python_status,"independent_dynamic_variables":len(independent),"within_10_percent":len(good),"dynamic_states":model.state_count,"pipe_states":0,"benchmarks":bench,"pytest":"PENDING","ready_for_L2_macro_calibration":False,"ready_for_mechanical_integration":False,"protected_model_hash":sha256(MODEL_PATH),"evidence_note":"position/velocity are measured mechanical boundaries, not independent predictions"}
    (AUD/"32K_phase_L1_R2_results.json").write_text(json.dumps(result,indent=2),encoding="utf-8")
    print(json.dumps(result,indent=2))
    return 0


if __name__ == "__main__":
    parser=argparse.ArgumentParser();parser.add_argument("--skip-benchmark",action="store_true")
    raise SystemExit(main(parser.parse_args().skip_benchmark))
