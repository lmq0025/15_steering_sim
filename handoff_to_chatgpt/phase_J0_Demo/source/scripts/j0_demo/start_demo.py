"""一键启动《电液转向系统联合仿真平台》中文界面。

由 ``start_steering_demo.bat`` 调用。本脚本只负责环境自检与中文错误提示，
不做任何仿真计算。

自检内容：
1. 必须使用指定的 conda 环境解释器（``steering_sim``）；
2. 项目源码目录必须可导入；
3. Tkinter 与 Matplotlib TkAgg 后端必须可用（离线，不联网）。
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys

EXPECTED_PYTHON = Path(r"E:\ProgramData\condaData\envs_dirs\steering_sim\python.exe")
PROJECT_ROOT = Path(__file__).resolve().parents[2]

BANNER = """
================================================================
  电液转向系统联合仿真平台
  控制 — 液压 — 机械 联合仿真（离线，不依赖 Amesim）
================================================================
"""


def _set_console_title(title: str) -> None:
    """用宽字符 API 设置控制台标题，避免代码页引起的乱码。"""
    if os.name != "nt":
        return
    try:
        import ctypes
        ctypes.windll.kernel32.SetConsoleTitleW(ctypes.c_wchar_p(title))
    except Exception:
        pass


def _prepare_console() -> None:
    """控制台输出走 UTF-8；失败也不影响界面启动。"""
    _set_console_title("电液转向系统联合仿真平台")
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def _fail(title: str, detail: str, hint: str = "") -> int:
    lines = [f"[启动失败] {title}", "", detail]
    if hint:
        lines.extend(["", hint])
    message = "\n".join(lines)
    print(message, file=sys.stderr)
    print(message)
    try:
        import tkinter
        from tkinter import messagebox
        root = tkinter.Tk()
        root.withdraw()
        messagebox.showerror("电液转向系统联合仿真平台", message)
        root.destroy()
    except Exception:
        pass
    return 2


def _check_interpreter() -> str | None:
    current = Path(sys.executable).resolve()
    if current == EXPECTED_PYTHON.resolve():
        return None
    return (f"当前解释器：{current}\n"
            f"指定解释器：{EXPECTED_PYTHON}\n\n"
            f"请使用 start_steering_demo.bat 启动，或直接执行：\n"
            f'  "{EXPECTED_PYTHON}" "{Path(__file__).resolve()}"')


def _check_dependencies() -> str | None:
    missing = []
    for name in ("numpy", "scipy", "matplotlib", "PIL", "tkinter"):
        try:
            __import__(name)
        except Exception:
            missing.append(name)
    if missing:
        return ("缺少运行依赖：" + "、".join(missing) + "\n\n"
                "本项目不自动安装依赖，请在 steering_sim 环境中补齐后重试。")
    # 界面把图像渲染成 PNG 再用 PIL 显示，不嵌入任何 matplotlib 画布，
    # 因此不需要 TkAgg 后端（切换全局后端会与后台线程建图冲突）。
    try:
        from matplotlib.backends.backend_agg import FigureCanvasAgg  # noqa: F401
        from PIL import ImageTk  # noqa: F401
    except Exception as exc:
        return f"图像渲染依赖不可用：{exc}"
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="启动电液转向系统联合仿真平台")
    parser.add_argument("--check-only", action="store_true",
                        help="只做环境自检，不打开界面")
    parser.add_argument("--cli", nargs=argparse.REMAINDER, default=None,
                        help="转发给命令行入口（不打开界面）")
    args = parser.parse_args(argv)

    _prepare_console()
    print(BANNER)

    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))

    problem = _check_interpreter()
    if problem:
        return _fail("Python 解释器不正确", problem)
    problem = _check_dependencies()
    if problem:
        return _fail("运行依赖不完整", problem)

    os.chdir(PROJECT_ROOT)

    if args.cli:
        from steering_sim.demo.cli import main as cli_main
        return cli_main(args.cli)
    if args.check_only:
        print("[自检通过] 解释器、依赖与图像渲染环境均可用。")
        print(f"项目根目录：{PROJECT_ROOT}")
        return 0

    try:
        from steering_sim.demo.ui import main as ui_main
    except Exception as exc:
        return _fail("界面模块导入失败",
                     f"{type(exc).__name__}: {exc}",
                     "请确认 src/steering_sim/demo 目录完整。")
    try:
        return ui_main([])
    except Exception as exc:  # 界面主循环内的意外错误
        import traceback
        return _fail("界面运行时出错", f"{type(exc).__name__}: {exc}",
                     traceback.format_exc())


if __name__ == "__main__":
    raise SystemExit(main())
