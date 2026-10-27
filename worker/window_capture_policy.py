"""Safety/reliability policy layered over capture_backend window mode.

The core backend intentionally stays small. This module adds rules that matter specifically
when a game window is selected OBS-style:
- saved zones remain percentage-correct if the window/frame resolution changes;
- legacy MSS fallback is allowed only while the bound game window is foreground and visible;
- minimized window capture returns blank pixels instead of re-reading a stale WGC frame;
- alt-tabbed legacy fallback returns blank pixels instead of capturing desktop content behind it;
- native WGC is retried periodically after a fallback instead of remaining on MSS forever.
"""
from __future__ import annotations

import ctypes
import time

import cv2
import numpy as np

import capture_backend

_RETRY_NATIVE_SECONDS = 15.0

_original_init = capture_backend.mss.__init__
_original_refresh = capture_backend.mss._refresh_window_bounds
_original_ensure = capture_backend.mss._ensure_capture
_original_start_legacy = capture_backend.mss._start_legacy
_original_grab = capture_backend.mss.grab


def _blank(region):
    return np.zeros((max(1, int(region.get("height", 1))), max(1, int(region.get("width", 1))), 3), dtype=np.uint8)


def _window_ok_for_native(current):
    if not current:
        return False
    try:
        user32 = ctypes.windll.user32
        hwnd = int(current["hwnd"])
        return bool(user32.IsWindow(hwnd) and user32.IsWindowVisible(hwnd) and not user32.IsIconic(hwnd))
    except Exception:
        return False


def _window_ok_for_screen_fallback(current):
    if not _window_ok_for_native(current):
        return False
    try:
        user32 = ctypes.windll.user32
        hwnd = int(current["hwnd"])
        # MSS is a desktop grab, not true window capture. Only trust the rectangle when the
        # selected game is foreground; otherwise another app may be covering those pixels.
        return int(user32.GetForegroundWindow() or 0) == hwnd
    except Exception:
        return False


def _init(self):
    _original_init(self)
    if self._window_name and self._window:
        b = self._window["bounds"]
        self._window_reference_size = (max(1, int(b["width"])), max(1, int(b["height"])))
    else:
        self._window_reference_size = None
    self._native_retry_at = 0.0


def _refresh_window_bounds(self):
    # capture_backend refreshes the synthetic monitor dimensions. Preserve the original
    # dimensions instead: detector.py calculated its zone pixel rectangles from that initial
    # reference, and this policy scales them dynamically to the current frame/window size.
    if not self._window_name:
        return _original_refresh(self)
    reference = getattr(self, "_window_reference_size", None)
    current = _original_refresh(self)
    if reference:
        w, h = reference
        self.monitors[0] = {"left": 0, "top": 0, "width": w, "height": h}
        self.monitors[1] = dict(self.monitors[0])
    return current


def _start_legacy(self):
    _original_start_legacy(self)
    if self._window_name:
        self._native_retry_at = time.monotonic() + _RETRY_NATIVE_SECONDS


def _ensure_capture(self, index):
    if self._window_name and self._force_legacy:
        if time.monotonic() >= float(getattr(self, "_native_retry_at", 0.0)):
            # Give WGC another chance. The original method will fall back to legacy again
            # and _start_legacy will schedule the next retry if native capture still fails.
            self._force_legacy = False
            _original_ensure(self, index)
            return
    return _original_ensure(self, index)


def _legacy_window_grab(self, region):
    current = self._refresh_window_bounds()
    if not _window_ok_for_screen_fallback(current):
        self._backend = "window-paused-not-foreground"
        return _blank(region)

    if self._legacy is None:
        self._legacy = capture_backend.legacy_mss.mss()

    b = current["bounds"]
    ref_w, ref_h = getattr(self, "_window_reference_size", None) or (b["width"], b["height"])
    sx = float(b["width"]) / max(1.0, float(ref_w))
    sy = float(b["height"]) / max(1.0, float(ref_h))

    left = int(round(int(region["left"]) * sx))
    top = int(round(int(region["top"]) * sy))
    width = max(1, int(round(int(region["width"]) * sx)))
    height = max(1, int(round(int(region["height"]) * sy)))
    width = min(width, max(1, int(b["width"]) - left))
    height = min(height, max(1, int(b["height"]) - top))
    actual = {
        "left": int(b["left"]) + left,
        "top": int(b["top"]) + top,
        "width": width,
        "height": height,
    }
    try:
        shot = np.asarray(self._legacy.grab(actual), dtype=np.uint8)[:, :, :3]
    except Exception:
        return _blank(region)
    target_size = (max(1, int(region["width"])), max(1, int(region["height"])))
    if shot.shape[1] != target_size[0] or shot.shape[0] != target_size[1]:
        shot = cv2.resize(shot, target_size, interpolation=cv2.INTER_AREA)
    self._backend = "legacy-window-mss-fallback"
    return np.ascontiguousarray(shot)


def _window_grab(self, region):
    current = self._refresh_window_bounds()
    if not _window_ok_for_native(current):
        self._backend = "window-paused-minimized-or-closed"
        return _blank(region)

    index = 1
    self._ensure_capture(index)
    if self._force_legacy:
        return _legacy_window_grab(self, region)

    try:
        full = self._native_full_frame()
    except Exception:
        self._start_legacy()
        return _legacy_window_grab(self, region)

    ref_w, ref_h = getattr(self, "_window_reference_size", None) or (self.monitors[1]["width"], self.monitors[1]["height"])
    sx = float(full.shape[1]) / max(1.0, float(ref_w))
    sy = float(full.shape[0]) / max(1.0, float(ref_h))

    x0 = max(0, int(round(int(region["left"]) * sx)))
    y0 = max(0, int(round(int(region["top"]) * sy)))
    width = max(1, int(round(int(region["width"]) * sx)))
    height = max(1, int(round(int(region["height"]) * sy)))
    x1 = min(full.shape[1], x0 + width)
    y1 = min(full.shape[0], y0 + height)
    if x1 <= x0 or y1 <= y0:
        return _blank(region)

    crop = full[y0:y1, x0:x1]
    target_size = (max(1, int(region["width"])), max(1, int(region["height"])))
    if crop.shape[1] != target_size[0] or crop.shape[0] != target_size[1]:
        crop = cv2.resize(crop, target_size, interpolation=cv2.INTER_AREA)
    return np.ascontiguousarray(crop)


def _grab(self, region):
    if self._window_name:
        if self._closed:
            raise RuntimeError("Capture session is closed")
        return _window_grab(self, region)
    return _original_grab(self, region)


capture_backend.mss.__init__ = _init
capture_backend.mss._refresh_window_bounds = _refresh_window_bounds
capture_backend.mss._start_legacy = _start_legacy
capture_backend.mss._ensure_capture = _ensure_capture
capture_backend.mss.grab = _grab
