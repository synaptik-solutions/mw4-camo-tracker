"""Final detector launcher.

Electron already passes the selected display's physical bounds. Force the OCR worker to use
those bounds instead of trusting a monitor ordinal, because Electron, Windows Graphics
Capture, DXGI, and python-mss are not guaranteed to enumerate displays in the same order.
The hybrid capture backend then resolves each region to the physical monitor containing it.
"""
from __future__ import annotations

import sys


def _prefer_physical_bounds(argv):
    required = ("--left", "--top", "--width", "--height")
    if not all(flag in argv for flag in required):
        return
    if "--monitor" in argv:
        try:
            pos = argv.index("--monitor")
            if pos + 1 < len(argv):
                argv[pos + 1] = "0"
                return
        except Exception:
            pass
    argv.extend(["--monitor", "0"])


_prefer_physical_bounds(sys.argv)

import detector_entry as app  # noqa: E402

if __name__ == "__main__":
    try:
        app.core.main()
    except KeyboardInterrupt:
        pass
    except Exception as exc:
        app.core.emit({"type": "error", "message": str(exc)})
        raise
