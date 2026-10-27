"""Windows-native capture facade that mimics the tiny subset of ``mss`` used by detector.py.

The detector imports ``mss`` from its own worker directory, so this module is loaded before
site-packages. On Windows it uses the Windows Graphics Capture API via ``windows-capture``
and exposes ``mss().monitors`` plus ``mss().grab(region)``. The OCR/detection code can stay
unchanged while screen acquisition moves off the old polling screenshot backend.

If WGC cannot start for a selected monitor, the wrapper falls back to the package's DXGI
Desktop Duplication session. Both paths are Windows-native and GPU-backed.
"""

from __future__ import annotations

import ctypes
import threading
import time
from ctypes import wintypes

import numpy as np

try:
    from windows_capture import DxgiDuplicationSession, WindowsCapture
except Exception as exc:  # surfaced when grab() is first used
    DxgiDuplicationSession = None
    WindowsCapture = None
    _IMPORT_ERROR = exc
else:
    _IMPORT_ERROR = None


_MONITORINFOF_PRIMARY = 0x00000001


class _RECT(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]


class _MONITORINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", _RECT),
        ("rcWork", _RECT),
        ("dwFlags", wintypes.DWORD),
    ]


def _enumerate_monitors():
    """Return MSS-compatible monitor dictionaries.

    Index 0 is the virtual desktop union, followed by physical monitors. The windows-capture
    monitor selector is 1-based, so physical entry N maps directly to native monitor N.
    """
    user32 = ctypes.windll.user32
    monitors = []

    callback_type = ctypes.WINFUNCTYPE(
        ctypes.c_int,
        wintypes.HMONITOR,
        wintypes.HDC,
        ctypes.POINTER(_RECT),
        wintypes.LPARAM,
    )

    def callback(hmonitor, _hdc, _rect, _data):
        info = _MONITORINFO()
        info.cbSize = ctypes.sizeof(_MONITORINFO)
        if user32.GetMonitorInfoW(hmonitor, ctypes.byref(info)):
            rc = info.rcMonitor
            monitors.append(
                {
                    "left": int(rc.left),
                    "top": int(rc.top),
                    "width": int(rc.right - rc.left),
                    "height": int(rc.bottom - rc.top),
                    "primary": bool(info.dwFlags & _MONITORINFOF_PRIMARY),
                }
            )
        return 1

    cb = callback_type(callback)
    if not user32.EnumDisplayMonitors(0, 0, cb, 0):
        raise OSError("EnumDisplayMonitors failed")

    if not monitors:
        raise OSError("No Windows displays found")

    # Put the primary display first. Electron commonly presents it first too, and this keeps
    # the existing monitor picker behavior predictable while still retaining all displays.
    monitors.sort(key=lambda item: (not item["primary"], item["left"], item["top"]))

    left = min(m["left"] for m in monitors)
    top = min(m["top"] for m in monitors)
    right = max(m["left"] + m["width"] for m in monitors)
    bottom = max(m["top"] + m["height"] for m in monitors)
    virtual = {"left": left, "top": top, "width": right - left, "height": bottom - top}

    return [virtual] + [
        {"left": m["left"], "top": m["top"], "width": m["width"], "height": m["height"]}
        for m in monitors
    ]


class mss:
    """Small context-manager facade compatible with the detector's current MSS usage."""

    def __init__(self):
        self.monitors = _enumerate_monitors()
        self._lock = threading.Lock()
        self._frame_event = threading.Event()
        self._latest_bgr = None
        self._capture = None
        self._capture_control = None
        self._dxgi = None
        self._active_monitor = None
        self._backend = None
        self._closed = False

    @property
    def backend(self):
        return self._backend or "windows-uninitialized"

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
        return False

    def close(self):
        self._closed = True
        control = self._capture_control
        self._capture_control = None
        if control is not None:
            try:
                control.stop()
            except Exception:
                pass
        self._capture = None
        self._dxgi = None
        with self._lock:
            self._latest_bgr = None
        self._frame_event.set()

    def _monitor_for_region(self, region):
        cx = int(region["left"]) + max(1, int(region["width"])) // 2
        cy = int(region["top"]) + max(1, int(region["height"])) // 2
        best_index = 1
        best_overlap = -1
        for idx, monitor in enumerate(self.monitors[1:], start=1):
            if (
                monitor["left"] <= cx < monitor["left"] + monitor["width"]
                and monitor["top"] <= cy < monitor["top"] + monitor["height"]
            ):
                return idx

            x0 = max(int(region["left"]), monitor["left"])
            y0 = max(int(region["top"]), monitor["top"])
            x1 = min(int(region["left"]) + int(region["width"]), monitor["left"] + monitor["width"])
            y1 = min(int(region["top"]) + int(region["height"]), monitor["top"] + monitor["height"])
            overlap = max(0, x1 - x0) * max(0, y1 - y0)
            if overlap > best_overlap:
                best_overlap = overlap
                best_index = idx
        return best_index

    def _start_wgc(self, monitor_entry_index):
        if WindowsCapture is None:
            raise RuntimeError(f"windows-capture import failed: {_IMPORT_ERROR}")

        # windows-capture uses 1-based monitor numbering. Our physical monitor entries are
        # also 1-based because index 0 is reserved for the virtual desktop union.
        native_index = max(1, int(monitor_entry_index))
        self._frame_event.clear()
        with self._lock:
            self._latest_bgr = None

        capture = WindowsCapture(
            cursor_capture=False,
            draw_border=False,
            minimum_update_interval=100,
            dirty_region=True,
            monitor_index=native_index,
            window_name=None,
        )

        @capture.event
        def on_frame_arrived(frame, _capture_control):
            if self._closed:
                return
            try:
                image = frame.to_bgr()
                # Frame memory is owned by the callback object, so keep a compact independent
                # copy for the detector thread. OCR only runs at a few Hz.
                image = np.ascontiguousarray(image).copy()
                with self._lock:
                    self._latest_bgr = image
                self._frame_event.set()
            except Exception:
                pass

        @capture.event
        def on_closed():
            self._frame_event.set()

        control = capture.start_free_threaded()
        self._capture = capture
        self._capture_control = control
        self._active_monitor = monitor_entry_index
        self._backend = "windows-graphics-capture"

        # Confirm at least one usable frame before declaring success.
        if not self._frame_event.wait(1.5):
            try:
                control.stop()
            except Exception:
                pass
            self._capture = None
            self._capture_control = None
            raise RuntimeError("Windows Graphics Capture started but no frame arrived")

    def _start_dxgi(self, monitor_entry_index):
        if DxgiDuplicationSession is None:
            raise RuntimeError(f"windows-capture import failed: {_IMPORT_ERROR}")
        native_index = max(1, int(monitor_entry_index))
        self._dxgi = DxgiDuplicationSession(native_index)
        self._active_monitor = monitor_entry_index
        self._backend = "dxgi-desktop-duplication"

    def _ensure_capture(self, monitor_entry_index):
        if self._active_monitor == monitor_entry_index and (self._capture is not None or self._dxgi is not None):
            return

        # Tear down any previous target before switching displays.
        control = self._capture_control
        if control is not None:
            try:
                control.stop()
            except Exception:
                pass
        self._capture = None
        self._capture_control = None
        self._dxgi = None
        self._active_monitor = None

        try:
            self._start_wgc(monitor_entry_index)
        except Exception:
            self._start_dxgi(monitor_entry_index)

    def _latest_full_frame(self):
        if self._capture is not None:
            self._frame_event.wait(0.35)
            with self._lock:
                if self._latest_bgr is None:
                    raise RuntimeError("No Windows Graphics Capture frame available")
                return self._latest_bgr

        if self._dxgi is not None:
            frame = self._dxgi.acquire_frame(timeout_ms=100)
            if frame is None:
                # A duplicated desktop can legitimately have no new frame. Retry briefly so
                # the detector doesn't treat a quiet screen as a capture failure.
                deadline = time.monotonic() + 0.35
                while frame is None and time.monotonic() < deadline:
                    frame = self._dxgi.acquire_frame(timeout_ms=50)
            if frame is None:
                raise RuntimeError("No DXGI frame available")
            image = frame.to_numpy()
            if image.ndim != 3:
                raise RuntimeError("Unexpected DXGI frame shape")
            return np.ascontiguousarray(image[..., :3])

        raise RuntimeError("Windows capture backend is not initialized")

    def grab(self, region):
        if self._closed:
            raise RuntimeError("Capture session is closed")

        monitor_index = self._monitor_for_region(region)
        self._ensure_capture(monitor_index)
        full = self._latest_full_frame()
        monitor = self.monitors[monitor_index]

        rel_left = int(region["left"]) - monitor["left"]
        rel_top = int(region["top"]) - monitor["top"]
        width = max(1, int(region["width"]))
        height = max(1, int(region["height"]))

        x0 = max(0, rel_left)
        y0 = max(0, rel_top)
        x1 = min(full.shape[1], rel_left + width)
        y1 = min(full.shape[0], rel_top + height)
        if x1 <= x0 or y1 <= y0:
            raise RuntimeError("Requested capture region is outside the selected display")

        cropped = full[y0:y1, x0:x1]
        if cropped.shape[0] != height or cropped.shape[1] != width:
            # Match MSS behavior closely enough for downstream code by padding clipped edges.
            output = np.zeros((height, width, 3), dtype=np.uint8)
            dst_x = max(0, -rel_left)
            dst_y = max(0, -rel_top)
            output[dst_y:dst_y + cropped.shape[0], dst_x:dst_x + cropped.shape[1]] = cropped
            return output
        return np.ascontiguousarray(cropped)
