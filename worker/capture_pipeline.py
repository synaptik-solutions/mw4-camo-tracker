"""Keep capture independent of OCR, with a small bounded queue of popup snapshots."""
from collections import OrderedDict
from dataclasses import dataclass
import threading
import sys
import time

import numpy as np

from popup_signature import popup_card_bounds

# Native capture runs independently of the legacy scan-rate setting and slow OCR.
MIN_CAPTURE_FPS = 10.
MAX_PENDING_FRAMES = 128
MAX_PENDING_BYTES = 64 * 1024 * 1024


@dataclass(frozen=True)
class PopupFrame:
    zone: str
    frame: object
    header: object
    captured_at: float
    captured_utc: str
    backend: str


class FrameQueue:
    def __init__(self, capacity=MAX_PENDING_FRAMES, max_bytes=MAX_PENDING_BYTES):
        self.capacity = max(1, int(capacity))
        self.max_bytes = max(1, int(max_bytes))
        self.pending_bytes = 0
        self._items = OrderedDict()
        self._condition = threading.Condition()
        self.closed = False
        self.dropped = 0

    def put(self, item):
        # Coalesce only byte-identical cards awaiting OCR. Moving backgrounds and new
        # banners remain separate; time buckets must never merge unrelated unlocks.
        identity = hash(item.frame.tobytes()) if hasattr(item.frame, "tobytes") else item.frame
        key = (item.zone, identity)
        size = getattr(item.frame, "nbytes", 0)
        with self._condition:
            if self.closed:
                return
            old = self._items.get(key)
            if old is not None:
                return
            if size > self.max_bytes:
                self.dropped += 1
                return
            self._items[key] = item
            self.pending_bytes += size
            while len(self._items) > self.capacity or self.pending_bytes > self.max_bytes:
                removed = self._items.popitem(last=False)[1]
                self.pending_bytes -= getattr(removed.frame, "nbytes", 0)
                self.dropped += 1
            self._condition.notify()

    def get(self, timeout=.25):
        with self._condition:
            self._condition.wait_for(lambda: self._items or self.closed, timeout)
            if not self._items:
                return None
            item = self._items.popitem(last=False)[1]
            self.pending_bytes -= getattr(item.frame, "nbytes", 0)
            return item

    def close(self):
        with self._condition:
            self.closed = True
            self._condition.notify_all()

    def __len__(self):
        with self._condition:
            return len(self._items)


class CapturePump:
    def __init__(self, factory, inspect_frame, utc_now, fps=4., capacity=MAX_PENDING_FRAMES):
        self.factory = factory
        self.inspect_frame = inspect_frame
        self.utc_now = utc_now
        self.interval = 1. / max(MIN_CAPTURE_FPS, min(float(fps), 30.))
        self.queue = FrameQueue(capacity)
        self._stop = threading.Event()
        self._ready = threading.Event()
        self._configured = threading.Event()
        self._lock = threading.Lock()
        self.monitors = []
        self.zones = []
        self.latest = {}
        self.error = None
        self.backend = None
        self.capture_count = 0
        self._thread = threading.Thread(target=self._run, name="popup-capture", daemon=True)

    def __enter__(self):
        self._thread.start()
        if not self._ready.wait(25.):
            self.close()
            raise RuntimeError("Capture startup timed out")
        self.check_error()
        return self

    def configure(self, zones):
        self.zones = list(zones)
        self._configured.set()

    def check_error(self):
        if self.error:
            raise RuntimeError(f"Capture failed: {self.error}") from self.error

    def snapshot(self):
        with self._lock:
            return dict(self.latest), self.capture_count, self.backend

    def _run(self):
        try:
            if sys.platform == "win32":
                from windows_dpi import enable_per_monitor_dpi_awareness
                enable_per_monitor_dpi_awareness()
            # MSS/Win32 resources are created, used and closed on their owning thread.
            with self.factory() as capture:
                self.monitors = [dict(m) for m in capture.monitors]
                self._ready.set()
                while not self._configured.wait(.1):
                    if self._stop.is_set():
                        return
                while not self._stop.is_set():
                    started = time.monotonic()
                    for zone in self.zones:
                        if self._stop.is_set():
                            break
                        frame = np.asarray(capture.grab(zone["region"]), dtype=np.uint8)
                        now = time.monotonic()
                        header, health = self.inspect_frame(frame, zone["name"])
                        backend = getattr(capture, "backend", "mss")
                        with self._lock:
                            self.latest[zone["name"]] = health
                            self.capture_count += 1
                            self.backend = backend
                        if header:
                            # Retain the native-resolution card, including weapon and
                            # title, rather than a whole high-resolution capture zone.
                            x0, y0, x1, y1 = popup_card_bounds(frame.shape, header[1])
                            card = frame[y0:y1, x0:x1, :3].copy()
                            score, (x, y, w, h) = header
                            local_header = (score, (x-x0, y-y0, w, h))
                            self.queue.put(PopupFrame(zone["name"], card, local_header,
                                                      now, self.utc_now(), backend))
                    self._stop.wait(max(0., self.interval - (time.monotonic() - started)))
        except Exception as exc:
            self.error = exc
        finally:
            self._ready.set()
            self.queue.close()

    def close(self):
        self._stop.set()
        self._configured.set()
        self.queue.close()
        self._thread.join(timeout=3.)
        if self._thread.is_alive():
            raise RuntimeError("Capture thread did not stop within three seconds")

    def __exit__(self, *_):
        self.close()
        return False
