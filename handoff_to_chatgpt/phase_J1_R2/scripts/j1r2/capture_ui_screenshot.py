"""PHASE J1-R2：抓取中文界面的验收截图。

真的把 Tk 主窗口建起来、跑一个代表工况、等界面刷新完，再用 ``PIL.ImageGrab``
抓窗口区域。抓不到（无显示会话）时显式跳过，**不伪造截图**。
"""
from __future__ import annotations

import argparse
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=str(ROOT / "outputs" / "j1r2"))
    parser.add_argument("--angle", type=float, default=30.0)
    parser.add_argument("--speed", type=float, default=10.0)
    args = parser.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    import tkinter as tk
    from steering_sim.demo.scenario import DemoScenario
    from steering_sim.demo.service import DemoService
    from steering_sim.demo.ui import DemoApp

    service = DemoService(output_dir=ROOT / "outputs" / "_j1r2_ui_shot")
    root = tk.Tk()
    root.geometry("1680x980+40+40")
    app = DemoApp(root, service)
    root.update()
    app.entries["target_outer_angle_deg"].set(f"{args.angle:g}")
    app.entries["speed_kmh"].set(f"{args.speed:g}")
    app.entries["duration_s"].set("3.75")
    root.update()

    app._busy = True                        # 直接调用：截图脚本不需要进度窗
    result = service.run(DemoScenario(args.angle, args.speed, duration_s=3.75),
                         export=False)
    app._busy = False
    app._finish(result)
    for _ in range(40):
        root.update()
        root.update_idletasks()
        time.sleep(0.05)

    shots: list[Path] = []
    try:
        from PIL import ImageGrab
    except Exception as exc:                # pragma: no cover - 无 Pillow
        print("跳过截图（缺少 Pillow）：", exc)
        root.destroy()
        return 0
    boxes = {
        "ui_overall": None,
        "ui_wheel_table": None,
    }
    try:
        x = root.winfo_rootx()
        y = root.winfo_rooty()
        width = root.winfo_width()
        height = root.winfo_height()
        image = ImageGrab.grab(bbox=(x, y, x + width, y + height))
        path = out / "fig_r2_7_ui_overall.png"
        image.save(path)
        shots.append(path)
        # 十二轮表那一页单独抓一张（先切到该标签页）。
        for tab_id in app.notebook.tabs():
            if app.notebook.tab(tab_id, "text") == "十二轮角度数值表":
                app.notebook.select(tab_id)
                break
        for _ in range(20):
            root.update()
            time.sleep(0.05)
        image = ImageGrab.grab(bbox=(x, y, x + width, y + height))
        path = out / "fig_r2_8_ui_wheel_table.png"
        image.save(path)
        shots.append(path)
    except Exception as exc:                # pragma: no cover - 无显示会话
        print("跳过截图（无法抓屏）：", exc)
    finally:
        try:
            app.close()
        except Exception:
            root.destroy()
    for path in shots:
        print("written:", path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
