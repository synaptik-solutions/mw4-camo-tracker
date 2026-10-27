"""Final detector launcher.

Display capture uses Electron's physical bounds instead of trusting monitor ordinals.
Window capture uses a synthetic source-relative monitor supplied by capture_backend so the
saved capture zones remain attached to the selected game window even if it moves displays.
"""
from __future__ import annotations

import json
import os
import sys

from windows_dpi import enable_per_monitor_dpi_awareness

enable_per_monitor_dpi_awareness()


def _set_arg(argv, name, value):
    if name in argv:
        try:
            pos = argv.index(name)
            if pos + 1 < len(argv):
                argv[pos + 1] = str(value)
                return
        except Exception:
            pass
    argv.extend([name, str(value)])


def _remove_arg(argv, name):
    while name in argv:
        try:
            pos = argv.index(name)
            del argv[pos:pos + 2]
        except Exception:
            break


def _resolve_only():
    if "--resolve-window-bounds" not in sys.argv:
        return False
    from capture_backend import _find_window
    title = str(os.environ.get("MW4_CAPTURE_WINDOW") or "").strip()
    found = _find_window(title) if title else None
    if not found:
        print(json.dumps({"ok": False, "bounds": None}), flush=True)
        raise SystemExit(2)
    print(json.dumps({"ok": True, "title": found["title"], "bounds": found["bounds"]}), flush=True)
    raise SystemExit(0)


_resolve_only()


def _normalize_capture_target(argv):
    if str(os.environ.get("MW4_CAPTURE_WINDOW") or "").strip():
        # Window mode: backend exposes the bound window as source-relative monitor #1.
        # Remove Electron display bounds entirely so detector.py derives its reference
        # width/height from that synthetic window monitor rather than from the display.
        _set_arg(argv, "--monitor", 1)
        for flag in ("--left", "--top", "--width", "--height"):
            _remove_arg(argv, flag)
        return

    required = ("--left", "--top", "--width", "--height")
    if all(flag in argv for flag in required):
        # Display mode: physical bounds from Electron are authoritative.
        _set_arg(argv, "--monitor", 0)


_normalize_capture_target(sys.argv)

# Runtime policies are loaded before detector_entry creates capture/reference objects.
import capture_perf  # noqa: E402,F401
import reference_policy  # noqa: E402,F401
import window_capture_policy  # noqa: E402,F401
import detector_entry as app  # noqa: E402
# recognition_policy wraps detector_entry after its OCR/image hooks exist.
import recognition_policy  # noqa: E402,F401

if __name__ == "__main__":
    try:
        app.core.main()
    except KeyboardInterrupt:
        pass
    except Exception as exc:
        app.core.emit({"type": "error", "message": str(exc)})
        raise
