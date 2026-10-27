"""Make Win32 window/monitor coordinates match physical capture pixels."""
from __future__ import annotations

import ctypes


def enable_per_monitor_dpi_awareness():
    try:
        # PER_MONITOR_AWARE_V2. Negative handle values are predefined DPI contexts.
        ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
        return True
    except Exception:
        pass
    try:
        # Windows 8.1 fallback: PROCESS_PER_MONITOR_DPI_AWARE = 2.
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
        return True
    except Exception:
        pass
    try:
        ctypes.windll.user32.SetProcessDPIAware()
        return True
    except Exception:
        return False
