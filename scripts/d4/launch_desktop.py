"""Standard-library-first desktop launcher with early diagnostics."""
from __future__ import annotations

import faulthandler
import logging
import os
from pathlib import Path
import sys
import tempfile
import time
import traceback

ROOT = Path(__file__).resolve().parents[2]


def _log_directory() -> Path:
    candidates = [ROOT / "outputs" / "desktop" / "logs"]
    local = os.environ.get("LOCALAPPDATA")
    if local:
        candidates.append(Path(local) / "SteeringQualityPredictor" / "logs")
    candidates.append(Path(tempfile.gettempdir()) / "SteeringQualityPredictor" / "logs")
    for candidate in candidates:
        try:
            candidate.mkdir(parents=True, exist_ok=True)
            probe = candidate / ".write_probe"
            probe.write_text("ok", encoding="ascii")
            probe.unlink()
            return candidate
        except OSError:
            continue
    raise RuntimeError("No writable desktop log directory is available")


def main() -> int:
    stamp = time.strftime("%Y%m%d_%H%M%S")
    log_path = _log_directory() / f"desktop_startup_{stamp}_{os.getpid()}.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[logging.FileHandler(log_path, encoding="utf-8"),
                  logging.StreamHandler(sys.stderr)], force=True)
    log = logging.getLogger("steering_sim.desktop.launcher")
    with log_path.open("a", encoding="utf-8") as fault_stream:
        faulthandler.enable(fault_stream)
        log.info("startup begin")
        log.info("python=%s", sys.executable)
        log.info("cwd=%s", Path.cwd())
        log.info("root=%s", ROOT)
        log.info("argv=%r", sys.argv[1:])
        handles = []
        env_root = Path(sys.executable).resolve().parent
        for directory in (env_root, env_root / "Library" / "bin",
                          env_root / "Scripts", env_root / "bin"):
            if directory.is_dir() and hasattr(os, "add_dll_directory"):
                handles.append(os.add_dll_directory(str(directory)))
                log.info("dll_directory=%s", directory)
        for value in (ROOT / "src", ROOT):
            if str(value) not in sys.path:
                sys.path.insert(0, str(value))
        try:
            for name in ("numpy", "pandas", "PySide6", "pyqtgraph", "openpyxl"):
                module = __import__(name)
                log.info("dependency %s=%s", name,
                         getattr(module, "__version__", "installed"))
            log.info("Qt dependencies imported")
            from steering_sim.desktop.app import main as qt_main
            log.info("entering Qt application")
            exit_code = int(qt_main(sys.argv[1:]))
            log.info("normal Qt exit code=%d", exit_code)
            return exit_code
        except BaseException:
            log.critical("desktop startup/runtime exception\n%s", traceback.format_exc())
            print(f"Desktop startup failed. Log: {log_path}", file=sys.stderr)
            return 1
        finally:
            handles.clear()


if __name__ == "__main__":
    raise SystemExit(main())
