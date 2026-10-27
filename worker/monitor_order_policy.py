"""Keep display-mode monitor indexes aligned with windows-capture.

windows-capture Monitor::from_index() uses the raw order returned by Win32
EnumDisplayMonitors. capture_backend originally sorted that same list primary-first, which
could turn a geometry-correct monitor selection back into the wrong numeric WGC/DXGI target.
This policy preserves native enumeration order while still exposing the MSS-compatible
virtual-desktop entry at index 0.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes

import capture_backend


def _enumerate_monitors_native_order():
    user32 = ctypes.windll.user32
    found = []
    cb_type = ctypes.WINFUNCTYPE(
        ctypes.c_int,
        wintypes.HMONITOR,
        wintypes.HDC,
        ctypes.POINTER(capture_backend._RECT),
        wintypes.LPARAM,
    )

    def callback(hmonitor, _hdc, _rect, _data):
        info = capture_backend._MONITORINFO()
        info.cbSize = ctypes.sizeof(capture_backend._MONITORINFO)
        if user32.GetMonitorInfoW(hmonitor, ctypes.byref(info)):
            rc = info.rcMonitor
            found.append({
                "left": int(rc.left),
                "top": int(rc.top),
                "width": int(rc.right - rc.left),
                "height": int(rc.bottom - rc.top),
            })
        return 1

    cb = cb_type(callback)
    if not user32.EnumDisplayMonitors(0, 0, cb, 0) or not found:
        with capture_backend.legacy_mss.mss() as sct:
            return [dict(m) for m in sct.monitors]

    left = min(x["left"] for x in found)
    top = min(x["top"] for x in found)
    right = max(x["left"] + x["width"] for x in found)
    bottom = max(x["top"] + x["height"] for x in found)
    virtual = {"left": left, "top": top, "width": right-left, "height": bottom-top}
    return [virtual] + found


capture_backend._enumerate_monitors = _enumerate_monitors_native_order
