"""Final detector launcher.

Display capture uses Electron's physical bounds instead of trusting monitor ordinals.
Window capture uses a synthetic source-relative monitor supplied by capture_backend so the
saved capture zones remain attached to the selected game window even if it moves displays.
"""
from __future__ import annotations

import os
import sys


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


def _normalize_capture_target(argv):
    if str(os.environ.get("MW4_CAPTURE_WINDOW") or "").strip():
        # Window mode: backend exposes the bound window as source-relative monitor #1.
        _set_arg(argv, "--monitor", 1)
        return

    required = ("--left", "--top", "--width", "--height")
    if all(flag in argv for flag in required):
        # Display mode: physical bounds from Electron are authoritative.
        _set_arg(argv, "--monitor", 0)


_normalize_capture_target(sys.argv)

import detector_entry as app  # noqa: E402

if __name__ == "__main__":
    try:
        app.core.main()
    except KeyboardInterrupt:
        pass
    except Exception as exc:
        app.core.emit({"type": "error", "message": str(exc)})
        raise
