"""《电液转向系统联合仿真平台》——中文本地交互界面（Tkinter + Matplotlib）。

本界面只做编排：所有计算都走 :class:`~steering_sim.demo.service.DemoService`，
图像、摘要与 CSV 因此必然来自同一次仿真。界面永不重新实现模型。

界面强制区分两种结果来源：
``重新运行仿真`` 与 ``预设结果回放``。后者会显示缓存时间与代码版本，不会被
说成"刚刚完成的实时仿真"。
"""
from __future__ import annotations

import tkinter as tk
from tkinter import filedialog, font as tkfont, messagebox, ttk
from pathlib import Path
from typing import Any

from . import degradation
from .assessment import PreflightAssessment
from .scenario import (ENGINEERING_DEFAULTS, DemoScenario, preset_scenarios,
                       DEFAULT_PRESET_KEY)
from .service import DemoResult, DemoService, DemoServiceError

WINDOW_TITLE = "电液转向系统联合仿真平台"
CUSTOM_LABEL = "自定义工况"
CHINESE_FONT_CANDIDATES = ("Microsoft YaHei UI", "Microsoft YaHei", "SimHei",
                           "SimSun", "DengXian")

TAB_LAYOUT = (
    ("机械转向结果", ("fig1_plan_view.png", "fig2_wheel_angles.png")),
    ("液压结果", ("fig3_strokes.png", "fig4_hydraulics.png")),
    ("控制结果", ("fig5_control.png",)),
    ("工况与限制", ("fig6_case_and_supply.png",)),
)


def _pick_font(root: tk.Misc) -> str:
    available = set(tkfont.families(root))
    for name in CHINESE_FONT_CANDIDATES:
        if name in available:
            return name
    return "TkDefaultFont"


class ImagePane(ttk.Frame):
    """可滚动的图片面板（按面板宽度缩放）。"""

    def __init__(self, master: tk.Misc, **kwargs: Any) -> None:
        super().__init__(master, **kwargs)
        self.canvas = tk.Canvas(self, highlightthickness=0)
        self.scroll_y = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.scroll_x = ttk.Scrollbar(self, orient="horizontal", command=self.canvas.xview)
        self.canvas.configure(yscrollcommand=self.scroll_y.set,
                              xscrollcommand=self.scroll_x.set)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.scroll_y.grid(row=0, column=1, sticky="ns")
        self.scroll_x.grid(row=1, column=0, sticky="ew")
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)
        self._images: list[Any] = []
        self._paths: tuple[Path, ...] = ()
        self.canvas.bind("<Configure>", lambda _event: self._render())
        # 窗口销毁时必须先释放 PhotoImage：Tk 解释器一旦消失，残留的
        # PhotoImage 在被垃圾回收时会回调已失效的 Tcl，导致进程级崩溃。
        self.bind("<Destroy>", self._on_destroy)

    def _on_destroy(self, event: Any) -> None:
        if event.widget is self:
            self.release()

    def release(self) -> None:
        """释放图像引用（销毁窗口前必须调用，或由 <Destroy> 自动触发）。"""
        self._images.clear()
        self._paths = ()
        try:
            self.canvas.delete("all")
        except tk.TclError:      # 解释器已经没了
            pass

    def show(self, paths: tuple[Path, ...]) -> None:
        self._paths = tuple(path for path in paths if path.exists())
        self._render()

    def _render(self) -> None:
        from PIL import Image, ImageTk
        self._images.clear()
        self.canvas.delete("all")
        if not self._paths:
            self.canvas.create_text(20, 20, anchor="nw",
                                    text="尚无结果。请先运行仿真或回放预设工况。",
                                    fill="#666666")
            self.canvas.configure(scrollregion=(0, 0, 400, 200))
            return
        width = max(self.canvas.winfo_width() - 8, 480)
        y = 0
        for path in self._paths:
            with Image.open(path) as opened:
                image = opened.convert("RGB")
                ratio = width / image.width
                resized = image.resize((int(width), max(1, int(image.height * ratio))),
                                       Image.LANCZOS)
            photo = ImageTk.PhotoImage(resized)
            self._images.append(photo)
            self.canvas.create_image(4, y, anchor="nw", image=photo)
            y += resized.height + 12
        self.canvas.configure(scrollregion=(0, 0, width + 8, y))


class _ProgressDialog:
    """积分期间的模态进度窗（单线程，不涉及后台任务）。"""

    def __init__(self, master: tk.Misc, title: str) -> None:
        self.window = tk.Toplevel(master)
        self.window.title(title)
        self.window.transient(master)
        self.window.resizable(False, False)
        self.window.protocol("WM_DELETE_WINDOW", lambda: None)
        frame = ttk.Frame(self.window, padding=16)
        frame.pack(fill="both", expand=True)
        self.message = tk.StringVar(value="正在运行仿真…")
        ttk.Label(frame, textvariable=self.message, width=46).pack(anchor="w")
        self.bar = ttk.Progressbar(frame, mode="determinate", maximum=100.0,
                                   length=360)
        self.bar.pack(pady=(8, 0))
        self.window.update_idletasks()
        try:
            self.window.grab_set()          # 运行期间禁止操作主窗口，避免重入
        except tk.TclError:
            pass

    def set_message(self, message: str) -> None:
        self.message.set(message)
        self._pump()

    def set_fraction(self, fraction: float) -> None:
        self.bar.configure(value=max(0.0, min(1.0, float(fraction))) * 100.0)
        self._pump()

    def _pump(self) -> None:
        try:
            self.window.update_idletasks()
        except tk.TclError:
            pass

    def close(self) -> None:
        try:
            self.window.grab_release()
            self.window.destroy()
        except tk.TclError:
            pass


class DemoApp:
    """主窗口。"""

    def __init__(self, root: tk.Tk, service: DemoService) -> None:
        self.root = root
        self.service = service
        self.presets = preset_scenarios()
        self.preset_by_label = {f"{p.key}  {p.name}": p for p in self.presets}
        self.preset_by_label[CUSTOM_LABEL] = None
        self.result: DemoResult | None = None
        self.panes: dict[str, ImagePane] = {}
        self._busy = False
        self._build_fonts()
        self._build_layout()
        self._load_preset(DEFAULT_PRESET_KEY)
        self._refresh_assessment()

    # ------------------------------------------------------------ 外观
    def _build_fonts(self) -> None:
        family = _pick_font(self.root)
        self.font_base = (family, 10)
        self.font_small = (family, 9)
        self.font_bold = (family, 10, "bold")
        self.font_title = (family, 13, "bold")
        for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont"):
            try:
                tkfont.nametofont(name).configure(family=family, size=10)
            except tk.TclError:
                pass
        self.root.option_add("*Font", self.font_base)

    def _build_layout(self) -> None:
        self.root.title(WINDOW_TITLE)
        self.root.geometry("1500x950")
        self.root.minsize(1150, 760)

        header = ttk.Frame(self.root, padding=(10, 8))
        header.pack(fill="x")
        ttk.Label(header, text=WINDOW_TITLE, font=self.font_title).pack(side="left")
        ttk.Label(header, text="  控制—液压—机械联合仿真（离线，不依赖 Amesim）",
                  foreground="#555555").pack(side="left")
        self.provenance_label = ttk.Label(header, text="尚未运行", foreground="#8a6d00")
        self.provenance_label.pack(side="right")

        body = ttk.Frame(self.root, padding=(10, 0, 10, 6))
        body.pack(fill="both", expand=True)
        body.columnconfigure(0, weight=0, minsize=350)
        body.columnconfigure(1, weight=1)
        body.rowconfigure(0, weight=1)

        self._build_input_panel(body)
        self._build_result_panel(body)

        self.status = tk.StringVar(value="就绪。请选择预设工况或修改输入后运行仿真。")
        bar = ttk.Frame(self.root, padding=(10, 4))
        bar.pack(fill="x")
        ttk.Label(bar, textvariable=self.status, foreground="#333333").pack(side="left")

    # ------------------------------------------------------------ 输入
    def _build_input_panel(self, parent: ttk.Frame) -> None:
        outer = ttk.Frame(parent)
        outer.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        outer.rowconfigure(0, weight=1)
        outer.columnconfigure(0, weight=1)
        canvas = tk.Canvas(outer, width=340, highlightthickness=0)
        scroll = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scroll.set)
        canvas.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")
        panel = ttk.Frame(canvas, padding=8)
        canvas.create_window((0, 0), window=panel, anchor="nw")
        panel.bind("<Configure>",
                   lambda event: canvas.configure(scrollregion=canvas.bbox("all")))

        ttk.Label(panel, text="工况输入", font=self.font_bold).pack(anchor="w")
        ttk.Label(panel, text="选择预设工况", font=self.font_small).pack(anchor="w", pady=(8, 2))
        self.preset_var = tk.StringVar(value=DEFAULT_PRESET_KEY)
        combo = ttk.Combobox(panel, textvariable=self.preset_var, state="readonly",
                             values=list(self.preset_by_label))
        combo.pack(fill="x")
        combo.bind("<<ComboboxSelected>>", self._on_preset_selected)

        self.entries: dict[str, tk.StringVar] = {}
        self._add_field(panel, "target_outer_angle_deg", "一桥外侧目标转角 [°]", "-30 ~ +30")
        self._add_field(panel, "speed_kmh", "车速 [km/h]", "0 ~ 80")
        self._add_field(panel, "friction_coefficient", "地面摩擦系数 [—]", "0.7 ~ 0.8")
        self._add_field(panel, "duration_s", "仿真时长 [s]", "0.5 ~ 60")

        ttk.Label(panel, text="每桥轴荷 [t]（一桥 → 六桥）",
                  font=self.font_small).pack(anchor="w", pady=(8, 2))
        loads = ttk.Frame(panel)
        loads.pack(fill="x")
        self.load_vars: list[tk.StringVar] = []
        for axle in range(6):
            var = tk.StringVar(value=f"{ENGINEERING_DEFAULTS['axle_mass_t']:.2f}")
            self.load_vars.append(var)
            ttk.Label(loads, text=f"{axle + 1}桥", font=self.font_small).grid(
                row=0, column=axle, padx=1)
            ttk.Entry(loads, textvariable=var, width=6).grid(row=1, column=axle, padx=1)

        note = ("默认摩擦系数 0.75 与每桥轴荷 11.5 t 均为工程假设"
                "（ASSUMED_ENGINEERING_PARAMETER），不是实车测量值。\n"
                "甲方任务书范围为车速 0–80 km/h、转角 ±30°、摩擦系数 0.7–0.8、"
                "轴荷 10–13 t；界面允许录入，但超出已验证动态联调范围"
                "（转角 ±5°、车速 0–10 km/h、μ=0.75、11.5 t）的工况会被标记为外推。")
        ttk.Label(panel, text=note, wraplength=310, font=self.font_small,
                  foreground="#666666", justify="left").pack(anchor="w", pady=(10, 4))

        ttk.Separator(panel).pack(fill="x", pady=6)
        self.run_button = ttk.Button(panel, text="运行仿真", command=self._on_run)
        self.run_button.pack(fill="x", pady=2)
        ttk.Button(panel, text="预设结果回放（快速，不重新计算）",
                   command=self._on_replay).pack(fill="x", pady=2)
        ttk.Button(panel, text="恢复默认工况", command=self._on_reset).pack(fill="x", pady=2)
        ttk.Separator(panel).pack(fill="x", pady=6)
        ttk.Button(panel, text="导出时间序列 CSV…",
                   command=self._on_export_csv).pack(fill="x", pady=2)
        ttk.Button(panel, text="导出结果报告…",
                   command=self._on_export_report).pack(fill="x", pady=2)

        ttk.Separator(panel).pack(fill="x", pady=6)
        ttk.Label(panel, text="性能退化与质量评估（待开发）", font=self.font_bold).pack(anchor="w")
        info = degradation.describe_interfaces()
        ttk.Label(panel, text=info["disclaimer"] + "\n" + info["note"],
                  wraplength=310, font=self.font_small, foreground="#8a6d00",
                  justify="left").pack(anchor="w", pady=(2, 6))
        ttk.Button(panel, text="查看预留参数接口…",
                   command=self._show_degradation).pack(fill="x")

    def _add_field(self, parent: ttk.Frame, key: str, label: str, hint: str) -> None:
        row = ttk.Frame(parent)
        row.pack(fill="x", pady=(6, 0))
        ttk.Label(row, text=label, font=self.font_small).pack(anchor="w")
        var = tk.StringVar()
        self.entries[key] = var
        ttk.Entry(row, textvariable=var).pack(fill="x")
        ttk.Label(row, text=f"任务书范围 {hint}", font=self.font_small,
                  foreground="#888888").pack(anchor="w")

    # ------------------------------------------------------------ 结果
    def _build_result_panel(self, parent: ttk.Frame) -> None:
        right = ttk.Frame(parent)
        right.grid(row=0, column=1, sticky="nsew")
        right.rowconfigure(2, weight=1)
        right.columnconfigure(0, weight=1)

        self.verdict = ttk.Label(right, text="—", font=self.font_bold)
        self.verdict.grid(row=0, column=0, sticky="w")
        self.assessment_text = tk.Text(right, height=8, wrap="word",
                                       font=self.font_small, background="#fbfbfb",
                                       relief="flat", highlightthickness=0)
        self.assessment_text.grid(row=1, column=0, sticky="ew", pady=(4, 6))
        self.assessment_text.tag_configure("warn", foreground="#8a6d00")
        self.assessment_text.tag_configure("block", foreground="#b00020")
        self.assessment_text.tag_configure("ok", foreground="#1b5e20")
        self.assessment_text.configure(state="disabled")

        notebook = ttk.Notebook(right)
        notebook.grid(row=2, column=0, sticky="nsew")
        for title, names in TAB_LAYOUT:
            pane = ImagePane(notebook)
            notebook.add(pane, text=title)
            self.panes[title] = pane

    # ------------------------------------------------------------ 预设
    def _on_preset_selected(self, _event: Any = None) -> None:
        label = self.preset_var.get()
        preset = self.preset_by_label.get(label)
        if preset is None:
            return
        self._fill_inputs(preset.scenario)
        self._refresh_assessment()

    def _load_preset(self, key: str) -> None:
        for preset in self.presets:
            if preset.key == key:
                self.preset_var.set(f"{preset.key}  {preset.name}")
                self._fill_inputs(preset.scenario)
                return

    def _fill_inputs(self, scenario: DemoScenario) -> None:
        self.entries["target_outer_angle_deg"].set(f"{scenario.target_outer_angle_deg:.2f}")
        self.entries["speed_kmh"].set(f"{scenario.speed_kmh:.2f}")
        self.entries["friction_coefficient"].set(f"{scenario.friction_coefficient:.2f}")
        self.entries["duration_s"].set(f"{scenario.duration_s:.2f}")
        for var, value in zip(self.load_vars, scenario.axle_mass_t):
            var.set(f"{value:.2f}")

    def _on_reset(self) -> None:
        self._load_preset(DEFAULT_PRESET_KEY)
        self._refresh_assessment()
        self.status.set("已恢复默认工况（J0-01 直行 0° / 0 km/h）。")

    def _read_scenario(self) -> DemoScenario:
        def number(key: str) -> float:
            raw = self.entries[key].get().strip()
            if not raw:
                raise DemoServiceError(f"「{key}」不能为空。")
            try:
                return float(raw)
            except ValueError as exc:
                raise DemoServiceError(f"「{key}」不是有效数字：{raw!r}") from exc

        loads = []
        for axle, var in enumerate(self.load_vars, start=1):
            raw = var.get().strip()
            try:
                loads.append(float(raw))
            except ValueError as exc:
                raise DemoServiceError(f"{axle}桥轴荷不是有效数字：{raw!r}") from exc
        preset = self.preset_by_label.get(self.preset_var.get())
        case_id = preset.key if preset else "DEMO"
        return DemoScenario(
            target_outer_angle_deg=number("target_outer_angle_deg"),
            speed_kmh=number("speed_kmh"),
            friction_coefficient=number("friction_coefficient"),
            axle_mass_t=tuple(loads),
            duration_s=number("duration_s"),
            case_id=case_id)

    # ------------------------------------------------------------ 评估
    def _refresh_assessment(self) -> None:
        try:
            scenario = self._read_scenario()
            report = self.service.assess(scenario)
        except Exception as exc:  # 输入非法时给出中文提示，不抛栈
            self._write_assessment(f"输入无法解析：{exc}", (("block", str(exc)),))
            self.verdict.configure(text="输入无效", foreground="#b00020")
            return
        self._show_assessment(report)

    def _show_assessment(self, report: PreflightAssessment) -> None:
        entries: list[tuple[str, str]] = []
        for line in report.summary_lines:
            entries.append(("ok" if report.runnable else "block", line))
        for message in report.blockers:
            entries.append(("block", "✖ 阻止运行：" + message))
        for message in report.warnings:
            entries.append(("warn", "⚠ " + message))
        if report.runnable and not report.warnings:
            entries.append(("ok", "✔ 未发现问题。"))
        self._write_assessment("", entries)
        if not report.runnable:
            self.verdict.configure(text="不可运行", foreground="#b00020")
        elif report.warnings:
            self.verdict.configure(text="可运行（带工程警告）", foreground="#8a6d00")
        else:
            self.verdict.configure(text="可运行", foreground="#1b5e20")

    def _write_assessment(self, plain: str, tagged: Any) -> None:
        self.assessment_text.configure(state="normal")
        self.assessment_text.delete("1.0", "end")
        if plain:
            self.assessment_text.insert("end", plain)
        for tag, text in tagged:
            self.assessment_text.insert("end", text + "\n", tag)
        self.assessment_text.configure(state="disabled")

    # ------------------------------------------------------------ 运行
    #
    # 运行全程在**主线程**完成。早期版本把积分放在后台线程、主线程用
    # ``update()`` 泵事件，在 Tk 存在时会在垃圾回收阶段间歇性触发进程级崩溃；
    # 单线程 + 进度回调既消除这一类故障，也让"正在运行"的提示始终可靠。
    # 积分期间界面由模态进度窗接管，不会重入。
    def _on_run(self) -> None:
        self._start_job("run")

    def _on_replay(self) -> None:
        self._start_job("replay")

    def _start_job(self, kind: str) -> None:
        if self._busy:
            return
        try:
            scenario = self._read_scenario()
        except DemoServiceError as exc:
            messagebox.showerror(WINDOW_TITLE, str(exc))
            return
        preset = self.preset_by_label.get(self.preset_var.get())
        preset_key = preset.key if preset else None
        if kind == "replay" and preset is None:
            messagebox.showinfo(WINDOW_TITLE,
                                "预设结果回放只对四个预设工况有效。\n"
                                "自定义工况请使用「运行仿真」。")
            return
        if kind == "replay" and preset is not None and \
                scenario.signature() != preset.scenario.signature():
            messagebox.showinfo(
                WINDOW_TITLE,
                "当前输入已被修改，与预设工况不一致，无法回放。\n"
                "请改回预设参数，或使用「运行仿真」实时计算。")
            return

        self._busy = True
        self.run_button.configure(state="disabled")
        dialog = None if kind == "replay" else _ProgressDialog(self.root, WINDOW_TITLE)
        try:
            if kind == "replay":
                self.status.set(f"正在读取预设缓存 {preset_key} …")
                result = self.service.replay_preset(str(preset_key))
            else:
                assert dialog is not None
                result = self.service.run(
                    scenario,
                    progress=lambda message: dialog.set_message(message),
                    on_fraction=dialog.set_fraction)
                if preset_key is not None and \
                        scenario.signature() == self._preset_signature(preset_key):
                    self.service.store_preset(preset_key, result)
        except Exception as exc:
            if dialog is not None:
                dialog.close()
            self._busy = False
            self.run_button.configure(state="normal")
            self._fail(exc)
            return
        if dialog is not None:
            dialog.close()
        self._busy = False
        self.run_button.configure(state="normal")
        self._finish(result)

    def _preset_signature(self, key: str) -> str:
        for preset in self.presets:
            if preset.key == key:
                return preset.scenario.signature()
        return ""

    def _finish(self, result: DemoResult) -> None:
        self.result = result
        names = {path.name for path in result.figures}
        for title, wanted in TAB_LAYOUT:
            self.panes[title].show(tuple(path for path in result.figures
                                         if path.name in wanted))
        missing = [name for _title, group in TAB_LAYOUT for name in group
                   if name not in names]
        if missing:
            self.status.set("提示：缺少图像 " + "、".join(missing))
        color = {"PASS": "#1b5e20", "CONDITIONAL": "#8a6d00"}.get(result.status, "#b00020")
        self.verdict.configure(text=f"工况判定：{result.status}", foreground=color)
        tag = "warn" if result.provenance == "PRESET_REPLAY" else "ok"
        self.provenance_label.configure(
            text=f"结果来源：{result.provenance_label}", foreground="#8a6d00"
            if tag == "warn" else "#1b5e20")
        entries: list[tuple[str, str]] = [("ok", result.provenance_note)]
        for line in result.preflight.summary_lines:
            entries.append(("ok", line))
        for message in result.preflight.warnings:
            entries.append(("warn", "⚠ " + message))
        for message in result.preflight.blockers:
            entries.append(("block", "✖ " + message))
        if result.headline() != "—":
            entries.append(("warn", "判定说明：" + result.headline()))
        for message in result.consistency.messages:
            entries.append(("warn" if result.consistency.flags else "ok", "· " + message))
        self._write_assessment("", entries)
        seconds = result.duration_wall_s
        self.status.set(f"{result.provenance_label}完成：判定 {result.status}，"
                        f"{'积分' if result.provenance == 'LIVE_RUN' else '缓存'}耗时 "
                        f"{seconds:.1f} s。CSV：{result.csv_path}")

    def _fail(self, exc: Exception) -> None:
        self.status.set("运行失败。")
        messagebox.showerror(WINDOW_TITLE, f"运行失败：\n{exc}")

    # ------------------------------------------------------------ 导出
    def _on_export_csv(self) -> None:
        if self.result is None:
            messagebox.showinfo(WINDOW_TITLE, "还没有结果可以导出，请先运行仿真。")
            return
        scenario = self.result.scenario
        default = f"{scenario.case_id}_timeseries.csv"
        target = filedialog.asksaveasfilename(
            title="导出时间序列 CSV", defaultextension=".csv",
            initialfile=default, filetypes=[("CSV 文件", "*.csv")])
        if not target:
            return
        try:
            path = self.service.export_csv(self.result, target)
        except Exception as exc:
            messagebox.showerror(WINDOW_TITLE, f"CSV 导出失败：{exc}")
            return
        self.status.set(f"已导出 CSV：{path}")

    def _on_export_report(self) -> None:
        if self.result is None:
            messagebox.showinfo(WINDOW_TITLE, "还没有结果可以导出，请先运行仿真。")
            return
        target = filedialog.asksaveasfilename(
            title="导出结果报告", defaultextension=".md",
            initialfile=f"{self.result.scenario.case_id}_demo_report.md",
            filetypes=[("Markdown 文件", "*.md")])
        if not target:
            return
        from .service import build_text_report
        text = build_text_report(self.result, self.service.git_head)
        Path(target).write_text(text, encoding="utf-8")
        self.status.set(f"已导出报告：{target}")

    def close(self) -> None:
        """释放图像资源后销毁窗口（测试与正常退出都应走这里）。"""
        for pane in self.panes.values():
            pane.release()
        self.result = None
        try:
            self.root.destroy()
        except tk.TclError:
            pass

    def _show_degradation(self) -> None:
        info = degradation.describe_interfaces()
        lines = [info["note"], "", info["disclaimer"], "", "预留参数（健康值均为 1.0）："]
        for name, value in info["parameters"].items():
            lines.append(f"  · {name} = {value:.2f}")
        lines.append("")
        lines.append("对应模型落点：")
        for name, where in info["interface_map"].items():
            lines.append(f"  · {name} → {where}")
        lines.append("")
        lines.append("预留模块位置：" + "、".join(info["reserved_modules"]))
        messagebox.showinfo("性能退化与质量评估（待开发）", "\n".join(lines))


def main(argv: list[str] | None = None) -> int:
    import argparse
    parser = argparse.ArgumentParser(description=WINDOW_TITLE)
    parser.add_argument("--output", default=None, help="结果输出目录")
    args = parser.parse_args(argv)

    try:
        service = DemoService(**({"output_dir": args.output} if args.output else {}))
    except Exception as exc:
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(WINDOW_TITLE,
                             f"无法初始化仿真平台：\n{exc}\n\n"
                             f"请确认已使用 E:\\ProgramData\\condaData\\envs_dirs\\"
                             f"steering_sim\\python.exe 启动。")
        return 2
    root = tk.Tk()
    DemoApp(root, service)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
