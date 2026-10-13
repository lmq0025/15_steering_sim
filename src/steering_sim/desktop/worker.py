"""One-task-at-a-time QThread execution with cooperative cancellation."""
from __future__ import annotations

import traceback
from typing import Any, Callable

from PySide6.QtCore import QObject, QThread, Signal, Slot


class TaskWorker(QObject):
    progress = Signal(int, str)
    finished = Signal(object)
    failed = Signal(str, str)
    cancelled = Signal(str)

    def __init__(self, task: Callable[..., Any], kwargs: dict[str, Any]) -> None:
        super().__init__()
        self.task = task
        self.kwargs = kwargs
        self._cancel_requested = False

    def is_cancelled(self) -> bool:
        return self._cancel_requested

    def report(self, fraction: float, message: str) -> None:
        self.progress.emit(max(0, min(100, int(round(100 * fraction)))), message)

    @Slot()
    def cancel(self) -> None:
        self._cancel_requested = True

    @Slot()
    def run(self) -> None:
        try:
            result = self.task(progress=self.report,
                               is_cancelled=self.is_cancelled, **self.kwargs)
            if self._cancel_requested:
                self.cancelled.emit("任务已在安全检查点取消")
            else:
                self.finished.emit(result)
        except Exception as exc:
            self.failed.emit(f"{type(exc).__name__}: {exc}", traceback.format_exc())


class TaskController(QObject):
    started = Signal(str)
    progress = Signal(int, str)
    finished = Signal(str, object)
    failed = Signal(str, str, str)
    cancelled = Signal(str, str)
    busy_changed = Signal(bool)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.thread: QThread | None = None
        self.worker: TaskWorker | None = None
        self.task_id = ""

    @property
    def busy(self) -> bool:
        return self.thread is not None and self.thread.isRunning()

    def start(self, task_id: str, task: Callable[..., Any], **kwargs) -> bool:
        if self.busy:
            return False
        self.task_id = task_id
        self.thread = QThread(self)
        self.worker = TaskWorker(task, kwargs)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.progress.connect(self.progress)
        self.worker.finished.connect(lambda result: self._finish(result))
        self.worker.failed.connect(lambda message, detail: self._fail(message, detail))
        self.worker.cancelled.connect(lambda message: self._cancelled(message))
        self.thread.finished.connect(self.thread.deleteLater)
        self.started.emit(task_id)
        self.busy_changed.emit(True)
        self.thread.start()
        return True

    def request_cancel(self) -> None:
        if self.worker is not None:
            self.worker.cancel()

    def _stop(self) -> None:
        if self.thread is not None:
            self.thread.quit()
            self.thread.wait(3000)
        self.thread = None
        self.worker = None
        self.busy_changed.emit(False)

    def _finish(self, result: Any) -> None:
        task_id = self.task_id
        self._stop()
        self.finished.emit(task_id, result)

    def _fail(self, message: str, detail: str) -> None:
        task_id = self.task_id
        self._stop()
        self.failed.emit(task_id, message, detail)

    def _cancelled(self, message: str) -> None:
        task_id = self.task_id
        self._stop()
        self.cancelled.emit(task_id, message)

    def shutdown(self) -> None:
        if self.worker is not None:
            self.worker.cancel()
        if self.thread is not None:
            self.thread.quit()
            self.thread.wait(5000)
