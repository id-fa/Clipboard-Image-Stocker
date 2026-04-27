"""High-throughput clipboard paste queue.

Decouples Ctrl+V (sync, must be fast) from disk I/O (slow). The UI thread
deep-copies the QImage and enqueues a PendingPaste; a single worker thread
saves them sequentially in timestamp order.
"""

from __future__ import annotations

import itertools
import logging
import queue
import threading
import time
from pathlib import Path

from PySide6.QtCore import QObject, QThread, Signal
from PySide6.QtGui import QImage

from stocker.core.image_io import save_image_atomic
from stocker.core.models import FileItem, PendingPaste, PendingStatus
from stocker.utils.paths import avoid_collision, normalize_rel

log = logging.getLogger(__name__)

BACKPRESSURE_QUEUE_LEN = 200
RETRY_BACKOFF_S = (0.05, 0.2, 0.6)


class PasteQueue(QObject):
    pending_added = Signal(object)  # PendingPaste
    paste_completed = Signal(int, object)  # pid, FileItem
    paste_failed = Signal(int, str)  # pid, error message
    backpressure_changed = Signal(int)  # current queue length

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._ids = itertools.count(1)
        self._queue: queue.Queue[PendingPaste] = queue.Queue()
        self._target_root: Path | None = None
        self._format: str = "png"
        self._jpeg_quality: int = 92
        self._worker = _Worker(self)
        self._lock = threading.Lock()

    def start(self) -> None:
        if not self._worker.isRunning():
            self._worker.start()

    def stop(self, timeout_ms: int = 3000) -> None:
        self._worker.request_stop()
        self._queue.put(_SHUTDOWN_SENTINEL)
        if not self._worker.wait(timeout_ms):
            log.warning("PasteQueue worker did not stop in %d ms", timeout_ms)

    def set_target_root(self, root: Path | None) -> None:
        with self._lock:
            self._target_root = root.resolve() if root else None

    def target_root(self) -> Path | None:
        with self._lock:
            return self._target_root

    def set_format(self, fmt: str, jpeg_quality: int = 92) -> None:
        fmt = (fmt or "png").lower()
        if fmt not in ("png", "jpeg"):
            fmt = "png"
        with self._lock:
            self._format = fmt
            self._jpeg_quality = max(50, min(100, jpeg_quality))

    def get_format(self) -> tuple[str, int]:
        with self._lock:
            return self._format, self._jpeg_quality

    def enqueue(self, qimage: QImage) -> PendingPaste | None:
        if qimage.isNull():
            return None
        if self._target_root is None:
            log.warning("paste enqueue dropped: no active root")
            return None
        # Deep-copy so the QImage survives clipboard mutation
        copy = qimage.copy()
        ts = time.time()
        fmt, _ = self.get_format()
        ext = ".jpg" if fmt == "jpeg" else ".png"
        pending = PendingPaste(
            pid=next(self._ids),
            qimage=copy,
            timestamp_ns=time.time_ns(),
            suggested_name=PendingPaste.make_name(ts, ext=ext),
        )
        self._queue.put(pending)
        self.pending_added.emit(pending)
        self.backpressure_changed.emit(self._queue.qsize())
        return pending

    # internal -----------------

    def _next(self) -> PendingPaste | None:
        item = self._queue.get()
        if item is _SHUTDOWN_SENTINEL:
            return None
        return item


_SHUTDOWN_SENTINEL = PendingPaste(
    pid=-1, qimage=None, timestamp_ns=0, suggested_name="<shutdown>",
    status=PendingStatus.DONE,
)


class _Worker(QThread):
    def __init__(self, owner: PasteQueue):
        super().__init__(owner)
        self._owner = owner
        self._stop = False

    def request_stop(self) -> None:
        self._stop = True

    def run(self) -> None:  # type: ignore[override]
        log.info("PasteQueue worker started")
        while not self._stop:
            pending = self._owner._next()
            if pending is None:
                break
            self._handle(pending)
            self._owner.backpressure_changed.emit(self._owner._queue.qsize())
        log.info("PasteQueue worker stopped")

    def _handle(self, p: PendingPaste) -> None:
        root = self._owner.target_root()
        if root is None:
            self._owner.paste_failed.emit(p.pid, "保存先フォルダが未指定")
            return
        fmt, quality = self._owner.get_format()
        target = avoid_collision(root / p.suggested_name)
        last_err: str | None = None
        for attempt, delay in enumerate([0.0, *RETRY_BACKOFF_S]):
            if delay:
                time.sleep(delay)
            try:
                p.status = PendingStatus.WRITING
                save_image_atomic(p.qimage, target, fmt, quality)  # type: ignore[arg-type]
                p.rel_path_after_save = normalize_rel(target.relative_to(root))
                p.status = PendingStatus.DONE
                item = FileItem.from_path(root, target)
                self._owner.paste_completed.emit(p.pid, item)
                return
            except Exception as e:  # noqa: BLE001
                last_err = f"attempt {attempt+1}: {e}"
                log.warning("paste save retry: %s", last_err)
        p.status = PendingStatus.FAILED
        p.error = last_err
        self._owner.paste_failed.emit(p.pid, last_err or "unknown error")
