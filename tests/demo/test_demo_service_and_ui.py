"""PHASE J0-DEMO 服务层与中文界面的回归测试。

覆盖验收清单中的：四个预设可加载、直行可运行、图表数据单位一致、
CSV 可导出、超范围能提示、供油不足不被隐藏、无 NaN/Inf、
退化接口不产生虚假结果。
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

import numpy as np
import pytest

from steering_sim.demo import degradation
from steering_sim.demo.scenario import DemoScenario, preset_scenarios
from steering_sim.demo.service import DemoServiceError, build_text_report


SHORT = DemoScenario(0.0, 0.0, duration_s=0.6, case_id="DEMO-SHORT")


@pytest.fixture(scope="module")
def short_run(demo_service):
    return demo_service.run(SHORT)


# ------------------------------------------------------------- 运行
@pytest.mark.slow
def test_a_short_straight_run_completes_and_exports_everything(short_run, scratch_dir):
    assert short_run.completed and short_run.status == "PASS"
    assert short_run.provenance == "LIVE_RUN"
    assert short_run.provenance_label == "重新运行仿真"
    assert len(short_run.figures) == 7
    assert all(path.exists() and path.stat().st_size > 5_000 for path in short_run.figures)
    assert short_run.csv_path.exists()
    assert short_run.report_path is not None and short_run.report_path.exists()
    assert short_run.consistency.ok, short_run.consistency.flags


@pytest.mark.slow
def test_figures_and_csv_come_from_the_same_run(short_run):
    header = short_run.csv_path.read_text(encoding="utf-8").splitlines()[0].split(",")
    time = np.array([float(line.split(",")[0])
                     for line in short_run.csv_path.read_text(
                         encoding="utf-8").splitlines()[1:]])
    assert abs(time[-1] - SHORT.duration_s) < 1e-9
    assert abs(float(short_run.samples["time_s"][-1]) - time[-1]) < 1e-12
    assert abs(short_run.consistency.metrics["time_last_s"] - SHORT.duration_s) < 1e-9
    # 图直接从同一份 samples 生成，因此列集合必须与 samples 一致。
    assert "channel_front_x_m" in header
    assert "wheel_axle5_left_actual_deg" in header


@pytest.mark.slow
def test_twelve_wheels_and_locked_third_axle(short_run):
    samples = short_run.samples
    for axle in range(1, 7):
        for side in ("left", "right"):
            key = f"wheel_axle{axle}_{side}_actual_deg"
            assert key in samples and np.all(np.isfinite(samples[key]))
    assert np.max(np.abs(samples["third_axle_max_abs_deg"])) <= 1e-9
    assert np.all(np.isfinite(samples["max_link_residual_m"]))


@pytest.mark.slow
def test_no_nan_inf_and_pressure_stays_physical(short_run):
    for name, values in short_run.samples.items():
        assert np.all(np.isfinite(np.asarray(values, dtype=float))), name
    assert short_run.consistency.metrics["max_chamber_pressure_mpa_g"] < 100.0


@pytest.mark.slow
def test_the_demo_path_has_no_amesim_dependency(short_run):
    """演示平台所依赖的每一个模块都不允许出现 Amesim/COM 桥接。"""
    import sys
    from steering_sim.demo import (assessment, cli, degradation, plots,
                                   scenario, service, ui)

    roots = [Path(module.__file__).resolve().parent
             for module in (assessment, cli, degradation, plots, scenario,
                            service, ui)]
    roots.append(Path(sys.modules["steering_sim.j0_coupling"].__file__).resolve().parent)
    roots.append(Path(sys.modules["steering_sim.hydraulics_lumped"].__file__).resolve().parent)
    roots.append(Path(sys.modules["mechanics_ackermann_v2"].__file__).resolve().parent)

    offenders: list[str] = []
    files = sorted({path for root in roots for path in root.rglob("*.py")})
    assert len(files) > 20, "模块扫描范围异常"
    for path in files:
        text = path.read_text(encoding="utf-8", errors="ignore").lower()
        for token in ("import amesim", "from amesim", "win32com", "amesim_api",
                      "subprocess.*amesim"):
            if token in text:
                offenders.append(f"{path.name}: {token}")
    assert not offenders, "演示路径出现 Amesim 依赖：" + "、".join(offenders)
    assert "win32com" not in sys.modules


# ------------------------------------------------------------- 阻塞
@pytest.mark.slow
def test_unrunnable_input_is_refused_with_a_chinese_reason(demo_service):
    with pytest.raises(DemoServiceError) as info:
        demo_service.run(DemoScenario(30.0, 80.0, duration_s=0.5))
    # PHASE M2：拒绝原因改为"超出连续延拓验证过的真实可解范围"。
    assert "可解范围" in str(info.value)


@pytest.mark.slow
def test_out_of_task_range_input_is_refused(demo_service):
    with pytest.raises(DemoServiceError):
        demo_service.run(DemoScenario(45.0, 5.0, duration_s=0.5))
    assessment = demo_service.assess(DemoScenario(45.0, 5.0, duration_s=0.5))
    assert any(flag.startswith("INPUT_OUT_OF_TASK_RANGE") for flag in assessment.flags)


# ------------------------------------------------------------- 导出
@pytest.mark.slow
def test_csv_export_writes_a_readable_file(demo_service, short_run, scratch_dir):
    target = scratch_dir / "export.csv"
    demo_service.export_csv(short_run, target)
    with target.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.reader(handle))
    assert rows[0][0] == "time_s"
    assert len(rows) == len(short_run.samples["time_s"]) + 1
    assert all(len(row) == len(rows[0]) for row in rows[:5])


@pytest.mark.slow
def test_report_states_provenance_and_assumptions(short_run):
    text = build_text_report(short_run, "deadbeef")
    assert "重新运行仿真" in text
    assert "ASSUMED" in text or "工程假设" in text
    assert "未复制任何目标角" in text
    assert "理想阿克曼角" in text and "机构可达角" in text


# ------------------------------------------------------------- 缓存
@pytest.mark.slow
def test_preset_cache_round_trip_is_labelled_as_replay(demo_service, scratch_dir):
    key = "UNIT-TEST-PRESET"
    result = demo_service.run(DemoScenario(0.0, 0.0, duration_s=0.6,
                                           case_id="J0-01"))
    demo_service.store_preset(key, result)
    try:
        replay = demo_service.replay_preset(key)
    finally:
        for path in demo_service.cache_paths(key):
            path.unlink(missing_ok=True)
    assert replay.provenance == "PRESET_REPLAY"
    assert replay.provenance_label == "预设结果回放"
    assert "不是刚刚完成的实时仿真" in replay.provenance_note
    assert replay.scenario.signature() == result.scenario.signature()
    assert np.allclose(replay.samples["time_s"], result.samples["time_s"])


@pytest.mark.slow
def test_missing_cache_gives_a_chinese_error(demo_service):
    with pytest.raises(DemoServiceError) as info:
        demo_service.replay_preset("NOT-BUILT")
    assert "尚无缓存" in str(info.value)


def test_cache_replay_cannot_be_forged_from_a_replay(demo_service):
    """回放结果不得再次写回缓存，避免把回放伪装成实时仿真。"""
    fake_result = type("R", (), {"provenance": "PRESET_REPLAY"})()
    with pytest.raises(DemoServiceError):
        demo_service.store_preset("X", fake_result)


# ------------------------------------------------------- 退化接口
def test_degradation_defaults_are_healthy_and_change_nothing():
    parameters = degradation.DegradationParameters()
    assert parameters.is_healthy
    assert set(parameters.__dataclass_fields__) >= {
        "pump_volumetric_efficiency", "valve_discharge_coefficient",
        "cylinder_internal_leakage", "cylinder_friction", "cylinder_damping",
        "controller_proportional_gain"}
    info = degradation.describe_interfaces()
    assert info["status"] == "RESERVED" and info["implemented"] is False
    assert "不输出寿命、剩余寿命或质量评分" in info["disclaimer"]


def test_unimplemented_predictions_fail_loudly_instead_of_guessing():
    with pytest.raises(degradation.DegradationNotImplementedError):
        degradation.predict_life()
    with pytest.raises(degradation.DegradationNotImplementedError):
        degradation.assess_quality()
    with pytest.raises(ValueError):
        degradation.DegradationParameters(pump_volumetric_efficiency=0.0)


# ------------------------------------------------------------- 界面
def _tk_root():
    import tkinter
    try:
        root = tkinter.Tk()
    except Exception as exc:  # 无桌面会话时跳过
        pytest.skip(f"当前环境无法创建 Tk 窗口：{exc}")
    root.withdraw()
    return root


@pytest.fixture
def silent_dialogs(monkeypatch):
    """测试中不允许弹出模态对话框（会永久阻塞事件循环）。"""
    from steering_sim.demo import ui
    calls: list[tuple[str, str]] = []
    for name in ("showerror", "showinfo", "showwarning"):
        monkeypatch.setattr(
            ui.messagebox, name,
            lambda title, message, _n=name, _c=calls: _c.append((_n, str(message))),
            raising=False)
    return calls


def _run_job(root, app, kind: str, timeout_s: float = 300.0) -> None:
    """运行一次界面任务。任务在主线程同步完成，这里只做超时保护。"""
    import time
    start = time.time()
    app._start_job(kind)
    root.update()
    assert not app._busy, "界面任务没有正常结束"
    assert time.time() - start < timeout_s


@pytest.mark.slow
def test_chinese_ui_builds_and_lists_four_presets(demo_service):
    from steering_sim.demo.ui import CUSTOM_LABEL, DemoApp
    root = _tk_root()
    try:
        app = DemoApp(root, demo_service)
        root.update()
        labels = [label for label in app.preset_by_label if label != CUSTOM_LABEL]
        assert len(labels) == 7
        assert app.preset_var.get().startswith("R2-")
        # 默认预设是 R2-05（+30°/10 km/h）—— 最大目标角的完整动态工况。
        default = app.preset_by_label[app.preset_var.get()]
        assert app.entries["target_outer_angle_deg"].get() ==             f"{default.scenario.target_outer_angle_deg:.2f}"
        assert app.entries["friction_coefficient"].get() == "0.75"
        assert len(app.load_vars) == 6
        assert set(app.panes) == {"机械转向结果", "液压结果", "控制结果",
                                  "工况与限制", "十二轮角度数值表"}
    finally:
        app.close()


@pytest.mark.slow
def test_chinese_ui_loads_each_preset_into_the_fields(demo_service):
    from steering_sim.demo.ui import DemoApp
    root = _tk_root()
    try:
        app = DemoApp(root, demo_service)
        for label, preset in app.preset_by_label.items():
            if preset is None:
                continue
            app.preset_var.set(label)
            app._on_preset_selected()
            root.update()
            assert (float(app.entries["target_outer_angle_deg"].get())
                    == pytest.approx(preset.scenario.target_outer_angle_deg))
            assert (float(app.entries["speed_kmh"].get())
                    == pytest.approx(preset.scenario.speed_kmh))
    finally:
        app.close()


@pytest.mark.slow
def test_chinese_ui_shows_warnings_for_out_of_range_input(demo_service):
    from steering_sim.demo.ui import DemoApp
    root = _tk_root()
    try:
        app = DemoApp(root, demo_service)
        app.entries["target_outer_angle_deg"].set("20")
        app.entries["speed_kmh"].set("60")
        app._refresh_assessment()
        root.update()
        text = app.assessment_text.get("1.0", "end")
        assert "不可运行" in app.verdict.cget("text")
        assert "可解范围" in text
        assert "外推" in text
    finally:
        app.close()


@pytest.mark.slow
def test_chinese_ui_preset_replay_does_not_claim_a_live_run(
        demo_service, silent_dialogs):
    """预设回放必须明确标注，且不能在没有缓存时静默退回实时计算。"""
    from steering_sim.demo.ui import DemoApp
    key = "J0-04"
    cached = demo_service.cache_exists(key)
    root = _tk_root()
    try:
        app = DemoApp(root, demo_service)
        app._load_preset(key)
        _run_job(root, app, "replay")
        if cached:
            assert app.result is not None
            assert app.result.provenance == "PRESET_REPLAY"
            assert app.provenance_label.cget("text").endswith("预设结果回放")
        else:
            # 没有缓存时走"拒绝运行"路径：不用弹窗打断，而是在检查结论里说明原因。
            assert app.result is None
            assert "尚无缓存" in app.assessment_text.get("1.0", "end")
        # 回放绝不写入缓存，也就不会把回放变成一次"实时仿真"。
        assert demo_service.cache_exists(key) == cached
    finally:
        app.close()


@pytest.mark.slow
def test_chinese_ui_records_a_live_run_and_shows_all_figures(demo_service, silent_dialogs):
    from steering_sim.demo.ui import DemoApp
    root = _tk_root()
    try:
        app = DemoApp(root, demo_service)
        app.preset_var.set("自定义工况")
        # 这个夹具跑的是**历史机构 AS_BUILT_REFERENCE + L1-Fast**，它只能做到
        # ±5° 量级；R2 的默认预设是 ±30°，对它来说会被正确拒绝。
        # 本测试要验的是"实时运行会记录结果并画出全部图"，因此显式给一个
        # 该机构真正能跑的工况。
        app.entries["target_outer_angle_deg"].set("2")
        app.entries["speed_kmh"].set("5")
        app.entries["duration_s"].set("2.0")
        _run_job(root, app, "run")
        assert app.result is not None
        assert app.result.provenance == "LIVE_RUN"
        assert "重新运行仿真" in app.provenance_label.cget("text")
        from steering_sim.demo.ui import ImagePane
        shown = [path for pane in app.panes.values()
                 if isinstance(pane, ImagePane) for path in pane._paths]
        # 六张图在图像页里，第七张（十二轮数值表）在表格页。
        assert len(shown) == 6
        assert len(app.result.figures) == 7
        assert len(app.wheel_tree.get_children()) == 12
        assert all(path.exists() for path in shown)
        assert all(path.exists() for path in app.result.figures)
    finally:
        app.close()


# ---------------------------------------------- PHASE M2：数值表与旧结果处理
@pytest.mark.slow
def test_wheel_table_carries_concrete_numbers_for_all_twelve_wheels(short_run):
    """M2 第十条：每个轮子都必须能直接看到具体角度数值。"""
    from steering_sim.demo.plots import wheel_table_rows
    rows = wheel_table_rows(short_run)
    assert len(rows) == 12
    assert [row[0] for row in rows].count("1桥") == 2
    for row in rows:
        axle, side, ideal, mechanism, actual, loaded, ackermann, state = row
        assert side in ("左", "右")
        for text in (ideal, mechanism, actual, ackermann):
            float(text)                     # 必须是数字，不能是"—"
        assert state
    locked = [row for row in rows if row[0] == "3桥"]
    assert all(row[7] == "锁止 0°" for row in locked)
    assert all(float(row[4]) == 0.0 for row in locked)


@pytest.mark.slow
def test_chinese_ui_shows_the_twelve_wheel_table(short_run, demo_service):
    from steering_sim.demo.ui import DemoApp, WHEEL_TABLE
    root = _tk_root()
    try:
        app = DemoApp(root, demo_service)
        app._finish(short_run)
        root.update()
        assert WHEEL_TABLE in app.panes
        items = app.wheel_tree.get_children()
        assert len(items) == 12
        values = app.wheel_tree.item(items[0], "values")
        assert len(values) == 8
        float(values[2]) and float(values[3]) and float(values[4])
    finally:
        app.close()


@pytest.mark.slow
def test_chinese_ui_marks_stale_results_after_a_refused_case(demo_service, silent_dialogs):
    """M2 第十一条：新工况跑不了时，绝不能把旧工况的图当成新工况输出。"""
    from steering_sim.demo.ui import DemoApp
    root = _tk_root()
    try:
        app = DemoApp(root, demo_service)
        app.preset_var.set("自定义工况")
        app.entries["duration_s"].set("0.6")
        app.entries["target_outer_angle_deg"].set("2")
        app.entries["speed_kmh"].set("5")
        _run_job(root, app, "run")
        assert app.result is not None
        previous = app.result.scenario.target_outer_angle_deg
        assert "本次运行结果" in app.result_banner.get()

        # PHASE J1-R2：+30°/80 km/h 现在**可以**完成计算（只是目标轨迹物理不可行），
        # 所以这里改用真正超出任务书范围的输入来检验"拒绝运行"路径。
        app.entries["target_outer_angle_deg"].set("45")
        app.entries["speed_kmh"].set("5")
        _run_job(root, app, "run")
        text = app.assessment_text.get("1.0", "end")
        assert "动态仿真：未执行" in text
        assert "当前输入工况" in text
        banner = app.result_banner.get()
        assert "上一次成功运行结果" in banner
        assert "未执行动态仿真" in banner
        # 旧结果被保留下来供对照，但必须带标记，且 result 未被替换成新工况。
        assert app.last_success is not None
        assert app.last_success.scenario.target_outer_angle_deg == previous
        assert app.result is not None
        assert app.result.scenario.target_outer_angle_deg == previous
        assert "未执行" in app.verdict.cget("text")
        assert "未执行" in app.lights["compute"].cget("text")
    finally:
        app.close()


@pytest.mark.slow
def test_chinese_ui_clears_the_banner_on_a_later_success(demo_service, silent_dialogs):
    from steering_sim.demo.ui import DemoApp
    root = _tk_root()
    try:
        app = DemoApp(root, demo_service)
        app.preset_var.set("自定义工况")
        app.entries["duration_s"].set("0.6")
        app.entries["target_outer_angle_deg"].set("45")
        app.entries["speed_kmh"].set("5")
        _run_job(root, app, "run")
        assert "未执行动态仿真" in app.result_banner.get()
        app.entries["target_outer_angle_deg"].set("0")
        app.entries["speed_kmh"].set("0")
        _run_job(root, app, "run")
        assert "未执行动态仿真" not in app.result_banner.get()
        assert "本次运行结果" in app.result_banner.get()
    finally:
        app.close()
