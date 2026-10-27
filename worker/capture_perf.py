"""Low-cost validation helpers for the capture backend."""
from __future__ import annotations

import numpy as np

import capture_backend


def sampled_valid_frame(image):
    if not isinstance(image, np.ndarray) or image.ndim != 3 or image.shape[0] <= 4 or image.shape[1] <= 4:
        return False
    # Sample roughly <=96x96 pixels rather than calculating statistics over an entire
    # 1440p/4K frame on every capture-zone read.
    sy = max(1, image.shape[0] // 96)
    sx = max(1, image.shape[1] // 96)
    sample = image[::sy, ::sx]
    return sample.size > 0 and float(np.std(sample)) > 0.20


capture_backend._valid_frame = sampled_valid_frame
