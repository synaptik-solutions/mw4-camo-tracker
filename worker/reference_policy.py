"""Runtime policy for the cached camo reference database."""
from __future__ import annotations

import time

import camo_reference

_REFRESH_SECONDS = 24 * 60 * 60
_original_start_async = camo_reference.CamoReferenceMatcher.start_async


def _start_async_if_stale(self):
    try:
        # If a usable cache exists and the manifest is less than a day old, keep gameplay
        # startup local-only. A stale/missing cache still refreshes in the background.
        if self.ready and self.manifest_path.exists():
            age = max(0.0, time.time() - self.manifest_path.stat().st_mtime)
            if age < _REFRESH_SECONDS:
                return
    except Exception:
        pass
    return _original_start_async(self)


camo_reference.CamoReferenceMatcher.start_async = _start_async_if_stale
