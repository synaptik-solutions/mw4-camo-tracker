"""Hybrid capture backend for MW4.

Display mode:
1. Windows Graphics Capture
2. DXGI Desktop Duplication
3. python-mss

Window mode (MW4_CAPTURE_WINDOW env var):
1. Windows Graphics Capture bound to the selected window title
2. python-mss of that window's real Win32 rectangle when native window capture fails

The public API intentionally matches the tiny subset used by detector.py: mss().monitors
and mss().grab(region).
"""
from __future__ import annotations

import ctypes
import os
import threading
import time
from ctypes import wintypes

import numpy as np
import mss as legacy_mss

try:
    from windows_capture import DxgiDuplicationSession, WindowsCapture
except Exception as exc:
    DxgiDuplicationSession = None
    WindowsCapture = None
    _IMPORT_ERROR = exc
else:
    _IMPORT_ERROR = None

_MONITORINFOF_PRIMARY = 0x00000001


class _RECT(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long), ("right", ctypes.c_long), ("bottom", ctypes.c_long)]


class _MONITORINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", _RECT), ("rcWork", _RECT), ("dwFlags", wintypes.DWORD)]


def _enumerate_monitors():
    user32 = ctypes.windll.user32
    found = []
    cb_type = ctypes.WINFUNCTYPE(ctypes.c_int, wintypes.HMONITOR, wintypes.HDC, ctypes.POINTER(_RECT), wintypes.LPARAM)

    def callback(hmonitor, _hdc, _rect, _data):
        info = _MONITORINFO()
        info.cbSize = ctypes.sizeof(_MONITORINFO)
        if user32.GetMonitorInfoW(hmonitor, ctypes.byref(info)):
            rc = info.rcMonitor
            found.append({
                "left": int(rc.left), "top": int(rc.top),
                "width": int(rc.right - rc.left), "height": int(rc.bottom - rc.top),
                "primary": bool(info.dwFlags & _MONITORINFOF_PRIMARY),
            })
        return 1

    cb = cb_type(callback)
    if not user32.EnumDisplayMonitors(0, 0, cb, 0) or not found:
        with legacy_mss.mss() as sct:
            return [dict(m) for m in sct.monitors]
    found.sort(key=lambda x: (not x["primary"], x["left"], x["top"]))
    left = min(x["left"] for x in found); top = min(x["top"] for x in found)
    right = max(x["left"] + x["width"] for x in found); bottom = max(x["top"] + x["height"] for x in found)
    return [{"left": left, "top": top, "width": right-left, "height": bottom-top}] + [
        {k: m[k] for k in ("left", "top", "width", "height")} for m in found
    ]


def _find_window(title):
    """Return a visible top-level window matching title, preferring exact match."""
    wanted = str(title or "").strip()
    if not wanted:
        return None
    user32 = ctypes.windll.user32
    matches = []
    enum_type = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)

    def callback(hwnd, _lparam):
        try:
            if not user32.IsWindowVisible(hwnd):
                return True
            length = user32.GetWindowTextLengthW(hwnd)
            if length <= 0:
                return True
            buf = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buf, length + 1)
            text = buf.value.strip()
            if not text:
                return True
            score = 2 if text.casefold() == wanted.casefold() else (1 if wanted.casefold() in text.casefold() or text.casefold() in wanted.casefold() else 0)
            if score:
                rect = _RECT()
                if user32.GetWindowRect(hwnd, ctypes.byref(rect)):
                    width = int(rect.right - rect.left); height = int(rect.bottom - rect.top)
                    if width > 40 and height > 40:
                        matches.append((score, width * height, int(hwnd), text, {
                            "left": int(rect.left), "top": int(rect.top), "width": width, "height": height
                        }))
        except Exception:
            pass
        return True

    cb = enum_type(callback)
    user32.EnumWindows(cb, 0)
    if not matches:
        return None
    matches.sort(key=lambda x: (x[0], x[1]), reverse=True)
    _, _, hwnd, actual_title, bounds = matches[0]
    return {"hwnd": hwnd, "title": actual_title, "bounds": bounds}


def _valid_frame(image):
    return isinstance(image, np.ndarray) and image.ndim == 3 and image.shape[0] > 4 and image.shape[1] > 4 and float(np.std(image)) > 0.20


class mss:
    def __init__(self):
        self._window_name = str(os.environ.get("MW4_CAPTURE_WINDOW") or "").strip()
        self._window = _find_window(self._window_name) if self._window_name else None
        if self._window_name and not self._window:
            raise RuntimeError(f"Bound capture window not found: {self._window_name}")

        if self._window:
            b = self._window["bounds"]
            # detector.py expects index 0 virtual + index 1 target. For window mode use
            # source-relative coordinates so saved percentages stay stable if the window moves.
            target = {"left": 0, "top": 0, "width": b["width"], "height": b["height"]}
            self.monitors = [dict(target), dict(target)]
        else:
            self.monitors = _enumerate_monitors()

        self._lock = threading.Lock(); self._frame_event = threading.Event()
        self._latest_bgr = None; self._capture = None; self._capture_control = None; self._dxgi = None
        self._active_monitor = None; self._backend = "hybrid-uninitialized"; self._closed = False
        self._legacy = None; self._force_legacy = False

    @property
    def backend(self):
        return self._backend

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close(); return False

    def close(self):
        self._closed = True
        if self._capture_control is not None:
            try: self._capture_control.stop()
            except Exception: pass
        self._capture_control = None; self._capture = None; self._dxgi = None
        if self._legacy is not None:
            try: self._legacy.close()
            except Exception: pass
        self._legacy = None; self._frame_event.set()

    def _refresh_window_bounds(self):
        if not self._window_name:
            return None
        current = _find_window(self._window_name)
        if current:
            self._window = current
            b = current["bounds"]
            self.monitors[0] = {"left": 0, "top": 0, "width": b["width"], "height": b["height"]}
            self.monitors[1] = dict(self.monitors[0])
        return current

    def _monitor_for_region(self, region):
        if self._window_name:
            return 1
        cx = int(region["left"]) + max(1, int(region["width"])) // 2
        cy = int(region["top"]) + max(1, int(region["height"])) // 2
        best = 1; best_overlap = -1
        for idx, m in enumerate(self.monitors[1:], start=1):
            if m["left"] <= cx < m["left"] + m["width"] and m["top"] <= cy < m["top"] + m["height"]:
                return idx
            x0 = max(int(region["left"]), m["left"]); y0 = max(int(region["top"]), m["top"])
            x1 = min(int(region["left"]) + int(region["width"]), m["left"] + m["width"])
            y1 = min(int(region["top"]) + int(region["height"]), m["top"] + m["height"])
            overlap = max(0, x1-x0) * max(0, y1-y0)
            if overlap > best_overlap:
                best_overlap = overlap; best = idx
        return best

    def _stop_native(self):
        if self._capture_control is not None:
            try: self._capture_control.stop()
            except Exception: pass
        self._capture_control = None; self._capture = None; self._dxgi = None; self._active_monitor = None

    def _start_wgc(self, index):
        if WindowsCapture is None:
            raise RuntimeError(f"windows-capture unavailable: {_IMPORT_ERROR}")
        self._frame_event.clear(); self._latest_bgr = None
        kwargs = dict(cursor_capture=False, draw_border=False, minimum_update_interval=80, dirty_region=True)
        if self._window_name:
            current = self._refresh_window_bounds()
            if not current:
                raise RuntimeError(f"Bound capture window disappeared: {self._window_name}")
            kwargs.update(monitor_index=None, window_name=current["title"])
        else:
            kwargs.update(monitor_index=max(1, int(index)), window_name=None)
        capture = WindowsCapture(**kwargs)

        @capture.event
        def on_frame_arrived(frame, _control):
            if self._closed:
                return
            try:
                image = np.ascontiguousarray(frame.to_bgr()).copy()
                if _valid_frame(image):
                    with self._lock:
                        self._latest_bgr = image
                    self._frame_event.set()
            except Exception:
                pass

        @capture.event
        def on_closed():
            self._frame_event.set()

        control = capture.start_free_threaded()
        self._capture = capture; self._capture_control = control; self._active_monitor = index
        self._backend = "windows-window-capture" if self._window_name else "windows-graphics-capture"
        if not self._frame_event.wait(1.25) or not _valid_frame(self._latest_bgr):
            self._stop_native()
            raise RuntimeError("Windows Graphics Capture produced no usable frame")

    def _start_dxgi(self, index):
        if self._window_name:
            raise RuntimeError("DXGI is display-only")
        if DxgiDuplicationSession is None:
            raise RuntimeError(f"DXGI unavailable: {_IMPORT_ERROR}")
        self._dxgi = DxgiDuplicationSession(max(1, int(index)))
        self._active_monitor = index; self._backend = "dxgi-desktop-duplication"

    def _start_legacy(self):
        self._stop_native()
        if self._legacy is None:
            self._legacy = legacy_mss.mss()
        self._force_legacy = True
        self._backend = "legacy-window-mss-fallback" if self._window_name else "legacy-mss-fallback"

    def _ensure_capture(self, index):
        if self._force_legacy:
            if self._legacy is None:
                self._start_legacy()
            return
        if self._active_monitor == index and (self._capture is not None or self._dxgi is not None):
            return
        self._stop_native()
        try:
            self._start_wgc(index); return
        except Exception:
            pass
        try:
            self._start_dxgi(index); return
        except Exception:
            self._start_legacy()

    def _native_full_frame(self):
        if self._capture is not None:
            self._frame_event.wait(.30)
            with self._lock:
                image = None if self._latest_bgr is None else self._latest_bgr.copy()
            if not _valid_frame(image):
                raise RuntimeError("WGC frame invalid")
            return image
        if self._dxgi is not None:
            deadline = time.monotonic() + .35; frame = None
            while frame is None and time.monotonic() < deadline:
                frame = self._dxgi.acquire_frame(timeout_ms=60)
            if frame is None:
                raise RuntimeError("DXGI produced no frame")
            image = np.ascontiguousarray(frame.to_numpy()[..., :3])
            if not _valid_frame(image):
                raise RuntimeError("DXGI frame invalid")
            return image
        raise RuntimeError("native capture not initialized")

    def _legacy_grab(self, region):
        if self._legacy is None:
            self._legacy = legacy_mss.mss()
        actual = dict(region)
        if self._window_name:
            current = self._refresh_window_bounds()
            if not current:
                raise RuntimeError(f"Bound capture window not found: {self._window_name}")
            b = current["bounds"]
            actual["left"] = b["left"] + int(region["left"])
            actual["top"] = b["top"] + int(region["top"])
            actual["width"] = min(int(region["width"]), max(1, b["width"] - int(region["left"])))
            actual["height"] = min(int(region["height"]), max(1, b["height"] - int(region["top"])))
        shot = np.asarray(self._legacy.grab(actual), dtype=np.uint8)
        return np.ascontiguousarray(shot[:, :, :3])

    def grab(self, region):
        if self._closed:
            raise RuntimeError("Capture session is closed")
        index = self._monitor_for_region(region)
        self._ensure_capture(index)
        if self._force_legacy:
            return self._legacy_grab(region)
        try:
            full = self._native_full_frame()
        except Exception:
            self._start_legacy()
            return self._legacy_grab(region)

        monitor = self.monitors[index]
        rel_left = int(region["left"]) - monitor["left"]
        rel_top = int(region["top"]) - monitor["top"]
        width = max(1, int(region["width"])); height = max(1, int(region["height"]))
        x0 = max(0, rel_left); y0 = max(0, rel_top)
        x1 = min(full.shape[1], rel_left + width); y1 = min(full.shape[0], rel_top + height)
        if x1 <= x0 or y1 <= y0:
            self._start_legacy()
            return self._legacy_grab(region)
        crop = full[y0:y1, x0:x1]
        if crop.shape[:2] != (height, width):
            out = np.zeros((height, width, 3), dtype=np.uint8)
            dx = max(0, -rel_left); dy = max(0, -rel_top)
            out[dy:dy+crop.shape[0], dx:dx+crop.shape[1]] = crop
            return out
        return np.ascontiguousarray(crop)
