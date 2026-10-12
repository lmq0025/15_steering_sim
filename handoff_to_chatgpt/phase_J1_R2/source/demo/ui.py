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

WHEEL_TABLE = "十二轮角度数值表"

TAB_LAYOUT = (
    ("机械转向结果", ("fig1_plan_view.png", "fig2_wheel_angles.png")),
    ("液压结果", ("fig3_strokes.png", "fig4_hydraulics.png")),
    ("控制结果", ("fig5_control.png",)),
    ("工况与限制", ("fig6_case_and_supply.png",)),
    (WHEEL_TABLE, ("fig7_wheel_table.png",)),
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
        self.frame = ttk.Frame(self.window, padding=16)
        self.frame.pack(fill="both", expand=True)
        frame = self.frame
        self.message = tk.StringVar(value="正在运行仿真…")
        ttk.Label(frame, textvariable=self.message, width=46).pack(anchor="w")
        self.bar = ttk.Progressbar(frame, mode="determinate", maximum=100.0,
                                   length=360)
        self.bar.pack(pady=(8, 0))
        #: 批量计算用的取消按钮（动态积分不可取消，那时不显示）。
        self.cancel_button: ttk.Button | None = None
        self.window.update_idletasks()
        try:
            self.window.grab_set()          # 运行期间禁止操作主窗口，避免重入
        except tk.TclError:
            pass

    def set_cancel(self, command: Any) -> None:
        """加一个取消按钮（仅批量准稳态计算支持取消）。"""
        if self.cancel_button is not None:
            return
        self.cancel_button = ttk.Button(self.frame, text="取消批量计算",
                                        command=command)
        self.cancel_button.pack(pady=(10, 0))
        self._pump()

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
        #: 上一次成功运行的结果。当前工况被拒绝时，界面必须显著标注它，
        #: 不能让旧图看起来像新工况的输出。
        self.last_success: DemoResult | None = None
        self.panes: dict[str, ImagePane] = {}
        self._busy = False
        #: 批量工况（界面导入 → 准稳态计算 → 导出）。``_batch`` 是懒加载的
        #: 批量上下文，与动态仿真的被控对象共用同一套机构与液压参数。
        self.batch_cases: list[DemoScenario] = []
        self.batch_path: Path | None = None
        self._batch = None
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

        ttk.Label(panel, text="正式机械模型", font=self.font_bold).pack(anchor="w")
        ttk.Label(panel,
                  text="ENGINEERING_STEERING_MODEL —— 唯一正式工程转向模型。"
                       "甲方原始硬点（主销、车轮中心、摆臂枢轴、液压缸安装点）"
                       "保持不变；中间传动机构为 ENGINEERING_DESIGN_ASSUMPTION 工程假设。",
                  wraplength=310, font=self.font_small, foreground="#555555",
                  justify="left").pack(anchor="w", pady=(2, 6))

        ttk.Label(panel, text="工况输入", font=self.font_bold).pack(anchor="w", pady=(6, 0))
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
        ttk.Label(panel, text="批量工况（CSV / XLSX）", font=self.font_bold).pack(anchor="w")
        ttk.Button(panel, text="导出工况模板…",
                   command=self._on_export_template).pack(fill="x", pady=2)
        ttk.Button(panel, text="导入工况表…",
                   command=self._on_import_cases).pack(fill="x", pady=2)
        self.batch_button = ttk.Button(panel, text="批量计算并导出…",
                                       command=self._on_run_batch)
        self.batch_button.pack(fill="x", pady=2)
        ttk.Label(panel,
                  text="批量采用 FAST_BATCH_ESTIMATE（准稳态作动能力预测，不做时间积分，"
                       "逐行标注）；单个工况仍用「运行仿真」做完整动态积分。",
                  wraplength=310, font=self.font_small, foreground="#666666",
                  justify="left").pack(anchor="w", pady=(2, 0))

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
        right.rowconfigure(4, weight=1)
        right.columnconfigure(0, weight=1)

        # PHASE J1-R2 §八：**一个红色 FAIL 不能代表所有状态**。这里把三件事分开
        # 显示，任何一件都不允许冒充另外两件：
        #   1) 计算是否成功（数值积分是否跑完）
        #   2) 液压跟踪是否达标（实际轮角是否跟上机构目标）
        #   3) 目标轨迹是否满足物理约束（a_y 是否超出轮胎附着）
        lights = ttk.Frame(right)
        lights.grid(row=0, column=0, sticky="ew", pady=(0, 4))
        self.lights: dict[str, tk.Label] = {}
        for index, (key, caption) in enumerate((
                ("compute", "① 计算状态"),
                ("tracking", "② 液压跟踪"),
                ("feasibility", "③ 目标轨迹物理可行性"))):
            box = tk.Label(lights, text=f"{caption}：—", font=self.font_bold,
                           anchor="w", padx=10, pady=5,
                           background="#eeeeee", foreground="#333333",
                           relief="flat", borderwidth=0)
            box.grid(row=0, column=index, sticky="ew", padx=(0, 6))
            lights.columnconfigure(index, weight=1)
            self.lights[key] = box

        self.verdict = ttk.Label(right, text="—", font=self.font_bold)
        self.verdict.grid(row=1, column=0, sticky="w")
        # 结果来源横幅：绝不允许把旧工况的图当成新工况的输出。
        self.result_banner = tk.StringVar(value="尚未产生任何结果。")
        self.banner_label = tk.Label(right, textvariable=self.result_banner,
                                     font=self.font_bold, anchor="w",
                                     background="#eeeeee", foreground="#333333",
                                     padx=8, pady=4)
        self.banner_label.grid(row=2, column=0, sticky="ew", pady=(2, 4))
        self.assessment_text = tk.Text(right, height=7, wrap="word",
                                       font=self.font_small, background="#fbfbfb",
                                       relief="flat", highlightthickness=0)
        self.assessment_text.grid(row=3, column=0, sticky="ew", pady=(0, 6))
        self.assessment_text.tag_configure("warn", foreground="#8a6d00")
        self.assessment_text.tag_configure("block", foreground="#b00020")
        self.assessment_text.tag_configure("ok", foreground="#1b5e20")
        self.assessment_text.configure(state="disabled")

        notebook = ttk.Notebook(right)
        notebook.grid(row=4, column=0, sticky="nsew")
        self.notebook = notebook
        for title, names in TAB_LAYOUT:
            if title == WHEEL_TABLE:
                self.panes[title] = self._build_wheel_table(notebook)
                notebook.add(self.panes[title], text=title)
                continue
            pane = ImagePane(notebook)
            notebook.add(pane, text=title)
            self.panes[title] = pane

    def _build_wheel_table(self, parent: ttk.Frame) -> ttk.Frame:
        """十二轮角度的可读数值表（界面内直接看数字）。"""
        frame = ttk.Frame(parent, padding=6)
        frame.rowconfigure(1, weight=1)
        frame.columnconfigure(0, weight=1)
        ttk.Label(frame, text="十二轮转角数值表（单位：°）—— "
                              "理想阿克曼角 / 无载机构理论角 / 液压驱动实际角",
                  font=self.font_bold).grid(row=0, column=0, sticky="w")
        columns = ("axle", "side", "ideal", "mechanism", "actual", "loaded",
                   "ackermann", "state")
        headings = ("车桥", "左/右轮", "理想阿克曼角", "机构理论角",
                    "液压实际角", "跟踪偏差", "阿克曼偏差", "跟踪状态")
        widths = (60, 70, 120, 110, 110, 100, 110, 150)
        tree = ttk.Treeview(frame, columns=columns, show="headings", height=14)
        for column, heading, width in zip(columns, headings, widths):
            tree.heading(column, text=heading)
            tree.column(column, width=width, anchor="center")
        tree.tag_configure("deviation", background="#fde8e6")
        tree.tag_configure("warn", background="#fff6e0")
        tree.tag_configure("locked", background="#f2f2f2")
        scroll = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=scroll.set)
        tree.grid(row=1, column=0, sticky="nsew")
        scroll.grid(row=1, column=1, sticky="ns")
        self.wheel_tree = tree
        self.wheel_note = ttk.Label(
            frame, text="尚无结果。运行仿真或回放预设工况后在此显示十二轮的具体角度。",
            font=self.font_small, foreground="#666666", wraplength=900,
            justify="left")
        self.wheel_note.grid(row=2, column=0, columnspan=2, sticky="w", pady=(6, 0))
        return frame

    #: 三态指示灯的配色（背景，前景）。
    LIGHT_STYLE = {
        "ok": ("#e6f4ea", "#1b5e20"),
        "warn": ("#fff6e0", "#8a6d00"),
        "bad": ("#fde8e6", "#b00020"),
        "idle": ("#eeeeee", "#333333"),
    }

    def _set_light(self, key: str, text: str, style: str) -> None:
        box = getattr(self, "lights", {}).get(key)
        if box is None:
            return
        background, foreground = self.LIGHT_STYLE.get(style, self.LIGHT_STYLE["idle"])
        box.configure(text=text, background=background, foreground=foreground)

    def _clear_lights(self) -> None:
        for key, caption in (("compute", "① 计算状态"),
                             ("tracking", "② 液压跟踪"),
                             ("feasibility", "③ 目标轨迹物理可行性")):
            self._set_light(key, f"{caption}：—", "idle")

    def _update_lights(self, summary: dict | None) -> None:
        """按三个独立结论刷新指示灯，互不冒充。"""
        if not summary:
            self._clear_lights()
            return
        completed = bool(summary.get("NUMERICAL_COMPLETED"))
        if completed:
            self._set_light("compute", "① 计算状态：计算完成", "ok")
        else:
            self._set_light("compute", "① 计算状态：计算未完成/求解失败", "bad")

        steady = summary.get("steady_max_tracking_error_vs_command_deg")
        peak = summary.get("max_tracking_error_vs_command_deg")
        if not completed:
            self._set_light("tracking", "② 液压跟踪：无法判定（未完成计算）", "idle")
        elif summary.get("TRACKING_PASS") and summary.get("TRANSIENT_TRACKING_PASS"):
            self._set_light("tracking",
                            f"② 液压跟踪：达标（稳态 {steady:.3f}°，"
                            f"峰值 {peak:.3f}°）", "ok")
        elif summary.get("TRACKING_PASS"):
            self._set_light("tracking",
                            f"② 液压跟踪：稳态达标但过渡段超差"
                            f"（峰值 {peak:.3f}°）", "warn")
        else:
            steady_text = "—" if steady is None else f"{steady:.3f}°"
            self._set_light("tracking", f"② 液压跟踪：超差（稳态 {steady_text}）", "bad")

        ratio = summary.get("target_path_adhesion_ratio")
        if ratio is None:
            self._set_light("feasibility", "③ 目标轨迹物理可行性：—", "idle")
        elif ratio > 1.0:
            self._set_light("feasibility",
                            f"③ 目标轨迹物理可行性：不可行（附着比 {ratio:.2f} > 1，"
                            f"目标路径超出轮胎附着）", "bad")
        elif ratio > 0.85:
            self._set_light("feasibility",
                            f"③ 目标轨迹物理可行性：接近附着极限（{ratio:.2f}）", "warn")
        else:
            self._set_light("feasibility",
                            f"③ 目标轨迹物理可行性：可行（附着比 {ratio:.2f}）", "ok")

    def _fill_wheel_table(self, result: DemoResult) -> None:
        from .plots import wheel_table_rows
        tree = getattr(self, "wheel_tree", None)
        if tree is None:
            return
        tree.delete(*tree.get_children())
        if result is None:
            self.wheel_note.configure(
                text="尚无结果。运行仿真或回放预设工况后在此显示十二轮的具体角度。")
            return
        for row in wheel_table_rows(result):
            if "反号" in row[-1]:
                tag = "deviation"
            elif row[-1] == "锁止 0°":
                tag = "locked"
            elif row[-1] != "正常":
                tag = "warn"
            else:
                tag = ""
            tree.insert("", "end", values=row, tags=(tag,) if tag else ())
        notes = [
            "各列含义：理想阿克曼角 = 共同瞬时转向中心几何解；"
            "机构理论角 = 真实闭链（无载）在目标机构坐标上的解；"
            "液压实际角 = J0 闭环中由真实缸位移反求的角。",
            "「跟踪偏差」= 液压实际角 − 机构理论角，是控制—液压闭环真正要负责的量；"
            "「阿克曼偏差」= 机构理论角 − 理想阿克曼角，属机械拓扑固有量，"
            "液压闭环不负责消除。",
        ]
        if result.scenario.target_outer_angle_deg != 0:
            notes.append("三桥恒为锁止 0°，不参与转向。")
        self.wheel_note.configure(text="\n".join(notes))

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
        except DemoServiceError as exc:
            # 工况被拒绝（机构不可达 / 超范围）：不用弹窗打断，而是明确标注状态，
            # 并让旧结果带上"上一次成功运行"的醒目标记。
            if dialog is not None:
                dialog.close()
            self._busy = False
            self.run_button.configure(state="normal")
            self._show_refusal(scenario, str(exc))
            return
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
        self.last_success = result
        names = {path.name for path in result.figures}
        for title, wanted in TAB_LAYOUT:
            pane = self.panes[title]
            if isinstance(pane, ImagePane):
                pane.show(tuple(path for path in result.figures
                                if path.name in wanted))
        self._fill_wheel_table(result)
        self._update_lights(result.summary)
        missing = [name for _title, group in TAB_LAYOUT for name in group
                   if name not in names]
        if missing:
            self.status.set("提示：缺少图像 " + "、".join(missing))
        if not result.summary.get("NUMERICAL_COMPLETED", True):
            verdict, color = "计算未完成", "#b00020"
        elif result.summary.get("VEHICLE_DYNAMIC_INFEASIBLE"):
            verdict, color = "计算完成／跟踪达标／目标轨迹物理不可行", "#8a6d00"
        elif result.summary.get("TRACKING_PASS"):
            verdict, color = "计算完成／跟踪达标／目标轨迹物理可行", "#1b5e20"
        else:
            verdict, color = "计算完成／跟踪超差", "#b00020"
        self.verdict.configure(text=f"综合判定：{verdict}"
                                    f"（内部状态 {result.status}）", foreground=color)
        self.result_banner.set(
            f"当前显示：本次运行结果 —— {self._scenario_label(result.scenario)}"
            f"（{result.provenance_label}）")
        self.banner_label.configure(background="#e6f4ea", foreground="#1b5e20")
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

    @staticmethod
    def _scenario_label(scenario: DemoScenario) -> str:
        return (f"目标 {scenario.target_outer_angle_deg:+.1f}° / "
                f"{scenario.speed_kmh:.0f} km/h / μ={scenario.friction_coefficient:.2f} / "
                f"轴荷 {scenario.axle_mass_t[0]:.1f} t")

    def _show_refusal(self, scenario: DemoScenario, reason: str) -> None:
        """新工况无法做动态仿真时，明确说明并标记旧结果。

        绝不能把上一次成功工况的图当成当前工况的输出。
        """
        self.verdict.configure(text="综合判定：动态仿真未执行（不是程序运行失败）",
                               foreground="#8a6d00")
        self._clear_lights()
        self._set_light("compute", "① 计算状态：未执行动态仿真", "warn")
        entries: list[tuple[str, str]] = [
            ("block", f"当前输入工况：{self._scenario_label(scenario)}"),
            ("block", "动态仿真：未执行"),
            ("block", "原因：" + reason.replace("\n", " ")),
        ]
        assessment = self.service.assess(scenario)
        for message in assessment.warnings[:4]:
            entries.append(("warn", "⚠ " + message))
        entries.append(("ok", "允许查看该工况的理想阿克曼几何与适用性评估"
                              "（见「工况与限制」页与左侧检查结论）。"))
        if self.last_success is not None:
            entries.append((
                "warn",
                "下图仍为上一次成功运行结果："
                f"{self._scenario_label(self.last_success.scenario)}"
                f"（{self.last_success.provenance_label}），"
                "**不是**当前工况的输出。"))
            self.result_banner.set(
                "⚠ 上一次成功运行结果："
                f"{self._scenario_label(self.last_success.scenario)}"
                f" —— 当前输入 {self._scenario_label(scenario)} 未执行动态仿真")
            self.banner_label.configure(background="#fff3cd", foreground="#8a6d00")
        else:
            self.result_banner.set(
                f"当前输入 {self._scenario_label(scenario)} 未执行动态仿真，"
                "且此前没有成功结果。")
            self.banner_label.configure(background="#fde8e6", foreground="#b00020")
        self.wheel_note.configure(
            text="当前工况未执行动态仿真，因此没有液压驱动实际角。"
                 "请查看左侧的理想阿克曼角与工况适用性评估。")
        tree = getattr(self, "wheel_tree", None)
        if tree is not None and self.last_success is None:
            tree.delete(*tree.get_children())
        self._write_assessment("", entries)
        self.status.set("当前工况不可运行，已保留上一次成功结果并显著标注。")

    def _fail(self, exc: Exception) -> None:
        self.status.set("运行失败。")
        self._clear_lights()
        self._set_light("compute", "① 计算状态：程序异常，计算失败", "bad")
        messagebox.showerror(WINDOW_TITLE, f"运行失败：\n{exc}")

    # -------------------------------------------------------- 批量工况
    def _batch_context(self):
        """批量用的被控对象上下文（懒加载，只建一次）。"""
        if getattr(self, "_batch", None) is None:
            from .batch import build_context
            self._batch = build_context(adapter=self.service.runner.geometry)
        return self._batch

    def _on_export_template(self) -> None:
        target = filedialog.asksaveasfilename(
            title="导出工况模板", defaultextension=".csv",
            initialfile="工况模板.csv",
            filetypes=[("CSV 文件", "*.csv"), ("Excel 工作簿", "*.xlsx")])
        if not target:
            return
        try:
            from .batch import write_template
            path = write_template(target)
        except Exception as exc:
            messagebox.showerror(WINDOW_TITLE, f"模板导出失败：{exc}")
            return
        self.status.set(f"已导出工况模板：{path}")

    def _on_import_cases(self) -> None:
        target = filedialog.askopenfilename(
            title="导入工况表", filetypes=[("CSV 文件", "*.csv"),
                                          ("Excel 工作簿", "*.xlsx"),
                                          ("全部文件", "*.*")])
        if not target:
            return
        try:
            from .batch import read_cases
            self.batch_cases = read_cases(target)
            self.batch_path = Path(target)
        except Exception as exc:
            messagebox.showerror(WINDOW_TITLE, f"工况表导入失败：\n{exc}")
            return
        lines = [f"已导入工况表：{self.batch_path.name}",
                 f"共 {len(self.batch_cases)} 个工况。"]
        for scenario in self.batch_cases[:5]:
            lines.append(f"  · {self._scenario_label(scenario)}")
        if len(self.batch_cases) > 5:
            lines.append(f"  · …其余 {len(self.batch_cases) - 5} 个")
        lines.append("点「批量计算并导出…」开始计算（可取消）。")
        self._write_assessment("", [("ok", line) for line in lines])
        self.status.set(f"已导入 {len(self.batch_cases)} 个工况：{self.batch_path}")

    def _on_run_batch(self) -> None:
        scenarios = getattr(self, "batch_cases", None)
        if not scenarios:
            messagebox.showinfo(WINDOW_TITLE,
                                "还没有导入工况表。\n请先点「导入工况表…」，"
                                "或先用「导出工况模板…」生成一份模板。")
            return
        target = filedialog.asksaveasfilename(
            title="批量结果导出", defaultextension=".xlsx",
            initialfile="批量工况结果.xlsx",
            filetypes=[("Excel 工作簿", "*.xlsx"), ("CSV 文件", "*.csv")])
        if not target:
            return
        if self._busy:
            return
        self._busy = True
        self.run_button.configure(state="disabled")
        self.batch_button.configure(state="disabled")
        dialog = _ProgressDialog(self.root, WINDOW_TITLE)
        dialog.set_message(f"正在做准稳态能力预测（{len(scenarios)} 个工况）…")
        cancel = {"value": False}

        def request_stop() -> None:
            cancel["value"] = True
            dialog.set_message("正在取消…（本批剩余工况将被跳过）")

        dialog.set_cancel(request_stop)
        try:
            from .batch import run_batch, write_csv, write_xlsx
            context = self._batch_context()
            rows = run_batch(context, scenarios,
                             on_progress=dialog.set_fraction,
                             should_stop=lambda: cancel["value"])
            suffix = Path(target).suffix.lower()
            if suffix in (".xlsx", ".xlsm"):
                written = write_xlsx(rows, target) or write_csv(
                    rows, Path(target).with_suffix(".csv"))
            else:
                written = write_csv(rows, target)
        except Exception as exc:
            dialog.close()
            self._busy = False
            self.run_button.configure(state="normal")
            self.batch_button.configure(state="normal")
            messagebox.showerror(WINDOW_TITLE, f"批量计算失败：{exc}")
            return
        dialog.close()
        self._busy = False
        self.run_button.configure(state="normal")
        self.batch_button.configure(state="normal")

        status_counts: dict[str, int] = {}
        for row in rows:
            key = str(row.get("综合状态"))
            status_counts[key] = status_counts.get(key, 0) + 1
        cancelled = cancel["value"] and len(rows) < len(scenarios)
        lines = [f"批量计算完成：{len(rows)} / {len(scenarios)} 个工况"
                 + ("（已取消）" if cancelled else ""),
                 f"结果已导出：{written}",
                 "计算方式：FAST_BATCH_ESTIMATE（准稳态，不做时间积分）",
                 "综合状态统计："]
        for key, count in sorted(status_counts.items(), key=lambda kv: -kv[1]):
            lines.append(f"  · {key}：{count}")
        lines.append("FAST_BATCH_ESTIMATE 只给出准稳态能力预测；"
                     "需要真实四通道动态时间序列时，对单个工况用「运行仿真」。")
        self._write_assessment("", [("ok", line) for line in lines])
        self.status.set(f"批量完成 {len(rows)} 个工况，已导出 {written}")

    def _clear_result_panes(self) -> None:
        for pane in self.panes.values():
            if isinstance(pane, ImagePane):
                pane.clear()

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
            if isinstance(pane, ImagePane):
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
