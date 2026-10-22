"""Actual Qt evidence for the R4 10 degree ramp.

Default: display the explicitly selected THIS-R4 benchmark result; no solver
may run. ``--live`` instead starts the identical scenario through the normal
MainWindow/QThread service. Recorded integration/service timing, preparation,
result presentation and screenshot timing are reported separately.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, is_dataclass
import hashlib
import json
from pathlib import Path
import sys
import time
import traceback


ROOT = Path(__file__).resolve().parents[2]
ENGINEERING_PYTHON = Path(r"E:\ProgramData\condaData\envs_dirs\steering_sim\python.exe")
sys.path[:0] = [str(ROOT), str(ROOT / "src")]


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def json_default(value):
    import numpy as np
    if is_dataclass(value): return asdict(value)
    if hasattr(value, "to_dict"): return value.to_dict(orient="records")
    if isinstance(value, np.ndarray): return value.tolist()
    if isinstance(value, np.generic): return value.item()
    raise TypeError(type(value).__name__)


def restore_record(folder):
    """Restore data types only; do not recalculate response metrics or curves."""
    import numpy as np
    import pandas as pd
    from steering_sim.desktop.response_analysis import ResponseCriteria
    folder = Path(folder).resolve()
    if not folder.is_relative_to(ROOT / "outputs/desktop/r4"):
        raise ValueError("Evidence source must be a clearly identified current R4 result")
    result = json.loads((folder / "result.json").read_text(encoding="utf-8-sig"))
    with np.load(folder / "samples.npz", allow_pickle=False) as archive:
        result["samples"] = {key: archive[key].copy() for key in archive.files}
    if not result["calculation_success"]:
        raise ValueError("Selected integration did not complete; retain its failure evidence instead")
    if result["summary"]["actual_hydraulic_step_s"] != .0005:
        raise ValueError("Selected source is not the 0.5 ms reference-step integration")
    if result["summary"]["reference_space"] != "outer_angle":
        raise ValueError("Selected source is not the strict outer-wheel-angle ramp")
    source_times = result["samples"]["time_s"]
    if source_times[-1] != result["simulation_horizon_s"]:
        raise ValueError("Recorded horizon and source result disagree")
    for key in ("wheel_table", "wheel_response_table", "cylinder_response_table"):
        result[key] = pd.DataFrame(result[key])
    for key in ("wheel_table", "cylinder_table"):
        result["response"][key] = pd.DataFrame(result["response"][key])
    result["response"]["criteria"] = ResponseCriteria(**result["response"]["criteria"])
    result["provenance_kind"] = "HISTORICAL_REPLAY"
    return result


def main():
    if Path(sys.executable) != ENGINEERING_PYTHON:
        raise RuntimeError(f"Use {ENGINEERING_PYTHON}")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=ROOT / "outputs/desktop/r4/optimized/angle_10")
    parser.add_argument("--output", type=Path, default=ROOT / "outputs/desktop/r4/simulation_gui")
    parser.add_argument("--live", action="store_true", help="Run a new real 10 degree QThread simulation")
    args = parser.parse_args()
    output = args.output.resolve(); output.mkdir(parents=True, exist_ok=True)
    if (output / "acceptance.json").exists():
        raise RuntimeError(f"Refuse to overwrite completed evidence: {output}")

    import numpy as np
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication
    from steering_sim.desktop.app import MainWindow, STYLE
    from steering_sim.desktop.services import DesktopCalculationService
    from steering_sim.j0_coupling.runner import J0Runner

    script_started = time.perf_counter()
    app = QApplication([]); app.setStyleSheet(STYLE)
    window = MainWindow(); page = window.pages[0]
    window.service = DesktopCalculationService(output / "live_calculation")
    window.setWindowTitle(window.windowTitle() + ("｜R4实时联合仿真验收" if args.live else "｜R4本轮已算结果回放"))
    window.showMaximized()
    window_preparation_wall = time.perf_counter()-script_started
    solver_calls = [0]
    original_run = J0Runner.run_case
    def count_run(runner, *a, **kw):
        solver_calls[0] += 1
        if not args.live:
            raise AssertionError("Display-only replay attempted to call the numerical solver")
        return original_run(runner, *a, **kw)
    J0Runner.run_case = count_run
    shots, step_measurements = [], []
    gui_presentation = []
    task_started = [None]
    heartbeat = [time.perf_counter()]
    heartbeat_gaps = []
    active_record = [None]
    original_finish = page.task_finished
    def time_presentation(result):
        start = time.perf_counter()
        original_finish(result)
        app.processEvents()
        gui_presentation.append(time.perf_counter() - start)
    page.task_finished = time_presentation

    heartbeat_timer = QTimer()
    def beat():
        now = time.perf_counter()
        if window.controller.busy:
            heartbeat_gaps.append(now - heartbeat[0])
        heartbeat[0] = now
    heartbeat_timer.timeout.connect(beat); heartbeat_timer.start(100)

    def write_failure(detail):
        (output / "failure.txt").write_text(detail, encoding="utf-8")
        (output / "acceptance.json").write_text(json.dumps({"status": "FAIL", "detail": detail,
            "live": args.live, "solver_calls": solver_calls[0]}, ensure_ascii=False, indent=2), encoding="utf-8")
        print(detail, flush=True); app.exit(2)

    def exception_hook(kind, value, tb):
        write_failure("".join(traceback.format_exception(kind, value, tb)))
    sys.excepthook = exception_hook

    def screenshot(name):
        start = time.perf_counter(); app.processEvents()
        screen = window.screen() or app.primaryScreen()
        image = screen.grabWindow(int(window.winId()))
        if image.isNull(): raise RuntimeError("QScreen returned an empty real-window screenshot")
        target = output / f"{name}.png"
        if not image.save(str(target)): raise RuntimeError(f"Cannot save screenshot: {target}")
        shots.append({"path": str(target), "sha256": sha256(target), "width": image.width(),
                      "height": image.height(), "simulated_time_s": page.replay.current_time,
                      "result_tab": page.tabs.currentIndex(), "capture_wall_s": time.perf_counter()-start})

    def apply_scenario(scenario):
        page.command_type.setCurrentIndex(page.command_type.findData("ramp"))
        page.from_straight.setChecked(True); page.initial_angle.setValue(0.)
        page.angle.setValue(float(scenario["target_outer_angle_deg"]))
        page.speed.setValue(float(scenario["speed_kmh"]))
        page.mu.setValue(float(scenario["friction_coefficient"]))
        page.seconds_per_degree.setValue(float(scenario["seconds_per_degree"]))
        page.hold_observation.setValue(float(scenario["hold_observation_s"]))
        for box, mass in zip(page.axles, scenario["axle_mass_t"]): box.setValue(float(mass))

    base_scenario = dict(command_type="ramp", initial_outer_angle_deg=0., target_outer_angle_deg=10.,
                         seconds_per_degree=6., hold_observation_s=10., speed_kmh=5.,
                         friction_coefficient=.8, axle_mass_t=[11.5]*6, duration_s=1.25)
    source_metadata = args.source / "result.json"
    if source_metadata.exists():
        base_scenario = json.loads(source_metadata.read_text(encoding="utf-8-sig"))["scenario"]
    if (float(base_scenario["target_outer_angle_deg"]) != 10. or
        float(base_scenario["initial_outer_angle_deg"]) != 0. or
        float(base_scenario["seconds_per_degree"]) != 6. or
        float(base_scenario["hold_observation_s"]) != 10.):
        raise ValueError("This evidence script is scoped to 0→10°, 6 s/deg, 10 s hold")
    apply_scenario(base_scenario)
    preparation_wall = [None]
    service_to_gui_wall = [None]

    def finish_evidence():
        result = active_record[0]
        window._sync_project()
        project_path = output / ("十度实时验收.d4project.json" if args.live else "十度本轮积分回放.d4project.json")
        window.project.save(project_path)
        source_hashes = ({name: sha256(args.source / name) for name in ("result.json", "samples.npz")}
                         if not args.live else {})
        evidence = {
            "status": "PASS", "method": "QScreen.grabWindow actual visible Qt window",
            "mode": "LIVE_QT_QTHREAD_FULL_22_STATE" if args.live else "EXPLICIT_THIS_R4_RECORDED_INTEGRATION_REPLAY",
            "source_folder": str(args.source.resolve()) if not args.live else None,
            "source_file_sha256": source_hashes, "solver_calls_in_this_script": solver_calls[0],
            "scenario": page._scenario(), "actual_hydraulic_step_s": result["summary"]["actual_hydraulic_step_s"],
            "physical_horizon_s": result["simulation_horizon_s"],
            "command_completion_s": result["response"]["command_completion_s"],
            "system_settled_s": result["response"]["system_settled_s"],
            "additional_convergence_s": result["response"]["additional_convergence_s"],
            "original_runner_wall_s": result["runtime_s"],
            "original_service_wall_s": result["service_runtime_s"],
            "original_performance_timing": result["summary"].get("performance_timing"),
            "record_load_and_type_restore_wall_s": preparation_wall[0],
            "qt_window_preparation_wall_s": window_preparation_wall,
            "gui_task_result_presentation_wall_s": gui_presentation,
            "live_service_to_result_presented_wall_s": service_to_gui_wall[0],
            "maximum_busy_heartbeat_gap_s": max(heartbeat_gaps, default=0.),
            "display_step_timings": step_measurements, "screenshots": shots,
            "project_path": str(project_path), "csv_path": result["csv_path"],
            "csv_sha256": sha256(result["csv_path"]),
            "script_wall_s_including_layout_waits_and_screenshots": time.perf_counter()-script_started,
            "timing_notes": "Original integration and service times are measured by the source calculation. Replay load/presentation and screenshot times are separate; replay does not re-integrate. Live service-to-presented includes actual QThread work and GUI presentation.",
            "raw_response_metrics_recomputed": False,
        }
        if (not args.live and solver_calls[0] != 0) or (args.live and solver_calls[0] != 1):
            raise AssertionError(f"Unexpected solver call count {solver_calls[0]}")
        (output / "acceptance.json").write_text(json.dumps(evidence, ensure_ascii=False, indent=2,
            default=json_default), encoding="utf-8")
        print(json.dumps(evidence, ensure_ascii=False, default=json_default), flush=True)
        heartbeat_timer.stop(); window.close(); app.quit()

    def capture_steps():
        end = float(active_record[0]["simulation_horizon_s"])
        steps = [("01_十度斜坡完成_真实计算耗时", 0, end),
                 ("02_严格六秒每度_目标与实际轮角", 6, end),
                 ("03_四通道同屏_实际行程与腔压", 1, 30.),
                 ("04_十二轮到位稳态时间", 2, end),
                 ("05_两条供油轨全过程", 4, end)]
        def next_step():
            if not steps:
                finish_evidence(); return
            name, tab, physical_time = steps.pop(0)
            start = time.perf_counter()
            page.tabs.setCurrentIndex(tab); page.replay.seek(physical_time)
            app.processEvents()
            step_measurements.append({"name": name, "view_update_wall_s": time.perf_counter()-start})
            QTimer.singleShot(180, lambda: (screenshot(name), next_step()))
        next_step()

    def task_done(task, result):
        if task != "simulation": return
        if not result or not result.get("calculation_success"):
            raise RuntimeError("Live simulation did not complete")
        active_record[0] = result
        service_to_gui_wall[0] = time.perf_counter()-task_started[0]
        window.status_text.setText("R4本窗口实时计算完成；原始积分结果回放不再求解")
        # Keep an exact live service output for a future explicit replay.
        np.savez_compressed(output / "samples.npz", **result["samples"])
        metadata = {key: value for key, value in result.items() if key != "samples"}
        metadata["scenario"] = page._scenario()
        (output / "result.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2,
            default=json_default), encoding="utf-8")
        QTimer.singleShot(150, capture_steps)

    def start():
        window.navigation.setCurrentRow(0)
        if args.live:
            task_started[0] = time.perf_counter(); page._run(); return
        start_restore = time.perf_counter()
        record = restore_record(args.source)
        preparation_wall[0] = time.perf_counter()-start_restore
        active_record[0] = record
        window._task_finished("replay", record)
        if page.last_result is not record and not page.last_result:
            raise RuntimeError("SimulationPage did not accept the source result")
        window.status_text.setText("本轮R4已计算70秒真实积分记录回放；本窗口仅载入和绘图，未重新求解")
        QTimer.singleShot(150, capture_steps)

    window.controller.finished.connect(task_done)
    window.controller.failed.connect(lambda task, message, detail: write_failure(detail))
    QTimer.singleShot(700, start)
    try:
        return app.exec()
    finally:
        J0Runner.run_case = original_run


if __name__ == "__main__":
    raise SystemExit(main())
