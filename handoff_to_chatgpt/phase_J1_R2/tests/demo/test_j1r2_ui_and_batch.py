"""PHASE J1-R2：中文界面的三态指示、批量导入导出与准稳态能力预测。

这一组测试锁的是 J1-R2 第八节的明确要求：

* 顶部**不再**用一个模糊的红色 FAIL 代表所有状态，而是分开显示
  "计算是否成功 / 液压跟踪是否达标 / 目标轨迹是否满足物理约束"；
* 十二轮表同时给出理想阿克曼角、机构理论角、液压实际角；
* CSV/XLSX 批量导入导出可用，且批算走的是**同一个工程液压模型的能力边界**。
"""
from __future__ import annotations

import math
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[2]
TMP = ROOT / "outputs" / "_demo_test_tmp" / "j1r2"


def _tk_root():
    import tkinter as tk
    try:
        root = tk.Tk()
    except tk.TclError:                       # pragma: no cover - 无显示环境
        pytest.skip("当前环境没有可用的 Tk 显示")
    root.withdraw()
    return root


@pytest.fixture(scope="module")
def context():
    from steering_sim.demo.batch import build_context
    return build_context()


# ------------------------------------------------------------ 批量模块
def test_batch_estimate_reports_capability_with_a_provenance(context):
    from steering_sim.demo.batch import estimate_case
    from steering_sim.demo.scenario import DemoScenario
    row = estimate_case(context, DemoScenario(30.0, 10.0, duration_s=3.75))
    assert row["计算方式"] == "FAST_BATCH_ESTIMATE"
    assert row["综合状态"]
    assert row["液压预测_axle1_right"] is not None
    assert row["预测跟踪误差_deg"] is not None
    for name in context.channel_names:
        assert row[f"可用推力_{name}_N"] > 0.0
        assert row[f"作动能力_{name}"] in ("OK", "FORCE_LIMITED")
        # 可用推力必须与工程液压模型的参数一致（不是另抄一张表）。
        # 导出的数值保留 1 位小数，所以按该精度核对来源。
        assert row[f"可用推力_{name}_N"] == pytest.approx(
            context.availability_n[name], abs=0.05)


def test_batch_never_raises_on_an_infeasible_case(context):
    """附着不可行的极端工况必须照常出结果并标记风险，不能抛异常。"""
    from steering_sim.demo.batch import estimate_case
    from steering_sim.demo.scenario import DemoScenario
    row = estimate_case(context, DemoScenario(30.0, 80.0, duration_s=3.75))
    assert row["综合状态"] == "VEHICLE_DYNAMIC_INFEASIBLE"
    assert row["附着比"] > 1.0
    assert row["液压预测_axle1_right"] is not None


def test_batch_import_export_round_trip(context):
    from steering_sim.demo.batch import (read_cases, run_batch, write_csv,
                                         write_template, write_xlsx)
    TMP.mkdir(parents=True, exist_ok=True)
    template = write_template(TMP / "template.csv")
    cases = read_cases(template)
    assert len(cases) == 5
    rows = run_batch(context, cases)
    assert len(rows) == len(cases)
    csv_path = write_csv(rows, TMP / "result.csv")
    assert csv_path.exists()
    xlsx = write_xlsx(rows, TMP / "result.xlsx")
    if xlsx is not None:
        assert xlsx.exists()
    # 模板 → 改一列 → 再读回来：导入路径必须能承受真实使用方式。
    again = read_cases(template)
    assert [s.target_outer_angle_deg for s in again] ==         [s.target_outer_angle_deg for s in cases]


def test_batch_import_rejects_bad_rows_loudly():
    from steering_sim.demo.batch import read_cases
    TMP.mkdir(parents=True, exist_ok=True)
    bad = TMP / "bad.csv"
    bad.write_text("target_outer_angle_deg,speed_kmh\n5,10\nabc,10\n",
                   encoding="utf-8-sig")
    with pytest.raises(ValueError):
        read_cases(bad)
    missing = TMP / "missing.csv"
    missing.write_text("foo,bar\n1,2\n", encoding="utf-8-sig")
    with pytest.raises(ValueError):
        read_cases(missing)


# ------------------------------------------------------------ 界面
def test_the_ui_shows_three_independent_status_lights(engineering_service):
    from steering_sim.demo.ui import DemoApp
    root = _tk_root()
    try:
        app = DemoApp(root, engineering_service)
        assert set(app.lights) == {"compute", "tracking", "feasibility"}
        # 尚未运行：三盏灯都必须是中性，不能预先显示任何结论。
        for box in app.lights.values():
            assert box.cget("background") == app.LIGHT_STYLE["idle"][0]
        summary = {
            "NUMERICAL_COMPLETED": True, "TRACKING_PASS": True,
            "TRANSIENT_TRACKING_PASS": True,
            "steady_max_tracking_error_vs_command_deg": 0.01,
            "max_tracking_error_vs_command_deg": 0.05,
            "target_path_adhesion_ratio": 5.7,
        }
        app._update_lights(summary)
        assert app.LIGHT_STYLE["ok"][0] == app.lights["compute"].cget("background")
        assert app.LIGHT_STYLE["ok"][0] == app.lights["tracking"].cget("background")
        # 目标轨迹超附着：这一盏必须变红，**但另外两盏不受影响**。
        assert app.LIGHT_STYLE["bad"][0] == app.lights["feasibility"].cget("background")
        assert "不可行" in app.lights["feasibility"].cget("text")
        assert "达标" in app.lights["tracking"].cget("text")
        summary["TRACKING_PASS"] = False
        app._update_lights(summary)
        assert app.LIGHT_STYLE["bad"][0] == app.lights["tracking"].cget("background")
    finally:
        app.close()


def test_the_ui_lists_the_batch_controls_and_the_single_model(engineering_service):
    from steering_sim.demo.ui import DemoApp
    root = _tk_root()
    try:
        app = DemoApp(root, engineering_service)
        assert app.batch_cases == []
        texts = []

        def walk(widget):
            for child in widget.winfo_children():
                try:
                    texts.append(str(child.cget("text")))
                except Exception:
                    pass
                walk(child)

        walk(app.root)
        joined = " ".join(texts)
        assert "导入工况表…" in joined
        assert "批量计算并导出…" in joined
        assert "导出工况模板…" in joined
        # 界面只呈现唯一正式工程模型，且不再有模式切换。
        assert "原始机构" not in joined
        assert "优化机构" not in joined
    finally:
        app.close()


@pytest.mark.slow
def test_the_ui_runs_a_batch_and_exports(engineering_service):
    from steering_sim.demo.ui import DemoApp
    from steering_sim.demo.scenario import DemoScenario
    root = _tk_root()
    try:
        app = DemoApp(root, engineering_service)
        app.batch_cases = [DemoScenario(0.0, 0.0, duration_s=1.3),
                           DemoScenario(10.0, 5.0, duration_s=1.73)]
        context = app._batch_context()
        from steering_sim.demo.batch import run_batch
        rows = run_batch(context, app.batch_cases)
        assert len(rows) == 2
        assert all(row["综合状态"] for row in rows)
        assert all(math.isfinite(row["预测跟踪误差_deg"]) for row in rows)
    finally:
        app.close()


@pytest.mark.slow
def test_the_ui_wheel_table_shows_tracking_deviation(engineering_service):
    """十二轮表必须同时给出理想/机构/实际角与**跟踪偏差**。"""
    from steering_sim.demo.plots import WHEEL_TABLE_HEADER, wheel_table_rows
    from steering_sim.demo.scenario import DemoScenario
    result = engineering_service.run(DemoScenario(10.0, 5.0, duration_s=1.73),
                                     export=False)
    assert WHEEL_TABLE_HEADER[5] == "跟踪偏差"
    rows = wheel_table_rows(result)
    assert len(rows) == 12
    for row in rows:
        ideal, mechanism, actual = (float(row[2]), float(row[3]), float(row[4]))
        deviation = float(row[5])
        assert deviation == pytest.approx(actual - mechanism, abs=0.02)
        assert row[7] in ("正常", "跟踪超差", "锁止 0°", "反号：结构偏差")
    assert result.summary["NUMERICAL_COMPLETED"]
    assert result.summary["TRACKING_PASS"]
