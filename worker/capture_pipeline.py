"""Keep capture independent of OCR, with a small bounded queue of popup snapshots."""
from collections import OrderedDict
from dataclasses import dataclass
import threading
import sys
import time

import numpy as np
from capture_health import CaptureHealth


@dataclass(frozen=True)
class PopupFrame:
    zone: str
    frame: object
    header: object
    captured_at: float
    captured_utc: str
    backend: str
    source_time: float = None


class FrameQueue:
    def __init__(self, capacity=4):
        self.capacity = capacity
        self._items = OrderedDict()
        self._condition = threading.Condition()
        self.closed = False
        self.dropped = 0

    def put(self, item):
        # Coalesce identical snapshots within a short slot; all storage stays bounded.
        # Include pixel identity: unrelated banners can arrive in the same slot.
        # Never overwrite one with another merely because they share a screen region.
        identity = hash(item.frame.tobytes()) if hasattr(item.frame, "tobytes") else item.frame
        key = (item.zone, int(item.captured_at / .75), identity)
        with self._condition:
            if self.closed:
                return
            old = self._items.get(key)
            if old is None or item.header[0] > old.header[0]:
                self._items[key] = item
            if len(self._items) > self.capacity:
                self._items.popitem(last=False)
                self.dropped += 1
            self._condition.notify()

    def get(self, timeout=.25):
        with self._condition:
            self._condition.wait_for(lambda: self._items or self.closed, timeout)
            return self._items.popitem(last=False)[1] if self._items else None

    def take_best(self, zone, after, before):
        with self._condition:
            eligible = [(key,item) for key,item in self._items.items()
                        if item.zone==zone and after<=item.captured_at<=before]
            if not eligible:
                return None
            key,item = max(eligible,key=lambda pair:(pair[1].header[0],pair[1].captured_at))
            del self._items[key]
            return item

    def close(self):
        with self._condition:
            self.closed = True
            self._condition.notify_all()

    def __len__(self):
        with self._condition:
            return len(self._items)


class CapturePump:
    def __init__(self, factory, inspect_frame, utc_now, fps=4., capacity=4, heartbeat=None):
        self.heartbeat = heartbeat
        self.health = CaptureHealth(fps)
        self.finished = False
        self.factory = factory
        self.inspect_frame = inspect_frame
        self.utc_now = utc_now
        self.interval = 1. / max(1., fps)
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
                last_heartbeat = 0.
                while not self._stop.is_set():
                    started = time.monotonic()
                    for zone in self.zones:
                        if self._stop.is_set():
                            break
                        frame = np.asarray(capture.grab(zone["region"]), dtype=np.uint8)
                        now = time.monotonic()
                        header, health = self.inspect_frame(frame, zone["name"])
                        health.update(self.health.observe(frame,zone["name"]))
                        backend = getattr(capture, "backend", "mss")
                        with self._lock:
                            self.latest[zone["name"]] = health
                            self.capture_count += 1
                            self.backend = backend
                        if header:
                            self.queue.put(PopupFrame(zone["name"], frame.copy(), header,
                                                      now, self.utc_now(), backend,
                                                      getattr(capture,"source_time",None)))
                    if self.heartbeat and time.monotonic()-last_heartbeat>=2:
                        status = self.health.status(len(self.zones),len(self.queue),self.queue.dropped)
                        self.heartbeat({'type':'capture-heartbeat',**status,'captureBackend':self.backend,
                                        'timestamp':self.utc_now(),'zones':self.snapshot()[0]})
                        last_heartbeat = time.monotonic()
                    self._stop.wait(max(0., self.interval - (time.monotonic() - started)))
        except StopIteration:
            self.finished = True
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
