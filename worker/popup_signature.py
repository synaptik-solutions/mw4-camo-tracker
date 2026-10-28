"""Match the UNLOCKED lettering before running expensive camo OCR.

The reference is a 72x16 grayscale crop of the unlock header from supplied gameplay.
High-pass correlation removes most lighting/background variation; several scales support
720p through 4K captures. It is an unlock-header reference, not a camo thumbnail.
"""
import base64
import zlib

import cv2
import numpy as np

_REFERENCE = "eJwt0mtT2ggUgOEf2tndL/tld6azO+22Op16Y9WWWmmFiAgBxAABQgyEWxIgkmBCiITIJQhUvIIQ40C9QbHtzOLMvj/gmXPmHAzyQE5nMJjL4VE7nsnEQ36MpnO79C5BFXiBYfkQgic5KuhIpJxO0LoJmCxWwAiAEZ4KpfmCXKootfrJFY7jSBj+sP5St7bjnl5aNbz7HCIRMpVw+zNYqCL6UUmicMqcZO3WZtnjVH78HD0cueDe8Lxf9EelA7lUVhqnVyg170DzG/oiP7siHn8C9q/BGJGKe7nhqXpmT4JV9ej+HHNtjpkFpYVEoQfvC8NHAMZuwh6vytoOnpxa40yTevObzHd08e6HdapyZVwXBpbEbjLk6RxuWkakwXJVNMa6kW3TQ9p2Fo5nwHEOk5pyAun5bOCNuirJ/zvC8RJI9j2Lte+HfxbbZgevWSg+jcFfU/BWs/c7PtyxIC4LsjbMyoqtQEMD3hlAw1RSQ7Y9TXWlIBVL1VrjXCt23jmIgXv+/O7rc7ljdvGameLSWOye3AFqN8/iapDPRmMZ6+ORFscqKDTuNessQzMDzOtTukvCxFFqjRNNvtS7iAE0d3wxMFcu1128ClB7yRA6JgOWev+3WA8Ry9yeaH8cjjzhMuf8eXoi70x6ck7UBUGSJnvVW6rUfucgB+45RakwigrYORUg2CQW+Eb4rbX+L7G+LyOyu7zt2+2wGGAzW51oPJGgaPrJOb14cuQDpdZSC51lO6m5derxRrupASDbMxEsHQ6Oo35rvf9rRIVCMYJIrn1rFR4CO/GtIR7OpicNMNf2VV2fE8WiXFJaqqguOxKqW3fT/VtrDQAr0zOTezSOjKJuS3XwLNQFvQEYiy+Ps7beHgxbH/y+LDrpyXkQjFw+LxVlpdWVrnU6toPovlz8wY5utz6l206jGfa7+xUbMDqfoQcMhNRh29Z9aqZ0DSdRrYZvV2EgfNZWrw/DQU4UC5KsHKvJUVDfPjMvd9TXyOMoAEp3FZoprJiOtMuLLuSzly9urr94/abR/mp01NOB38e3g7OEBaqVJtcI7wn7+wXpYDLPUlNrnHoNSyfFxQ9HR+YV4vTqvN9YBo1ElQ9AKcoby4ZceErvcEbQ+UWD48XrGf2myx/dsPt2Yrm8KE3WKtWOuwAMRiAgsP7ZsGm0oFa32W1z2ZzedCge9WJpQkBDRJrl8ikUrcglKZeuHkjiU3khnxeL5bpSOzysN04uE8GtIEZSMQhhMjSdZrJZjhdFnsuJeVHIpjlul6/Wy7J8UKxUeCGX4/fYyRsmKTIRjeI4JezSFIFFhDbNMHSKJCiGJmMRPOD3IVg4hgd8Pq/L6bSDlnXT+4V1gwkATO+XF/+dfft25uVf/0y9eTM9PfXq1dTbj0sLs3NvpvW+/wCukEro"
_THRESHOLD = 0.65
_SCALES = (.65, .8, 1., 1.2, 1.5, 1.8, 2., 2.4, 2.8, 3., 3.4)


def _high_pass(gray):
    gray = gray.astype(np.float32)
    return gray - cv2.GaussianBlur(gray, (0, 0), 2)


_template = np.frombuffer(zlib.decompress(base64.b64decode(_REFERENCE)), dtype=np.uint8).reshape(16, 72)
_templates = [_high_pass(cv2.resize(_template, None, fx=s, fy=s)) for s in _SCALES]


def find_popup_header(bgr):
    """Return (score, (x, y, width, height)) only for a matching unlock header."""
    if bgr is None or bgr.size == 0:
        return None
    h, w = bgr.shape[:2]
    # Keep matching work bounded on large/high-DPI capture regions.
    scale = min(1., 1024. / max(w, 1))
    sample = cv2.resize(bgr, None, fx=scale, fy=scale) if scale < 1 else bgr
    gray = _high_pass(cv2.cvtColor(sample, cv2.COLOR_BGR2GRAY))
    hsv = cv2.cvtColor(sample, cv2.COLOR_BGR2HSV)
    green = cv2.inRange(hsv, np.array([25, 25, 70], np.uint8), np.array([100, 255, 255], np.uint8)) / 255.
    color_sum = cv2.integral(green)
    energy_sum = cv2.integral(gray * gray)
    best_score, best_bounds = _THRESHOLD, None
    for template in _templates:
        th, tw = template.shape
        if th > gray.shape[0] or tw > gray.shape[1]:
            continue
        result = cv2.matchTemplate(gray, template, cv2.TM_CCOEFF_NORMED)
        # Normalized correlation is unstable on near-constant black regions. Require
        # actual lettering detail and the yellow/green backing, not just a high score.
        color = color_sum[th:, tw:] - color_sum[:-th, tw:] - color_sum[th:, :-tw] + color_sum[:-th, :-tw]
        energy = energy_sum[th:, tw:] - energy_sum[:-th, tw:] - energy_sum[th:, :-tw] + energy_sum[:-th, :-tw]
        result[(color < .20 * th * tw) | (energy < 9. * th * tw)] = 0
        _, score, _, (x, y) = cv2.minMaxLoc(result)
        if np.isfinite(score) and score >= best_score:
            best_score = float(score)
            best_bounds = tuple(int(round(v / scale)) for v in (x, y, tw, th))
    return (best_score, best_bounds) if best_bounds else None



def popup_card_bounds(shape, header_bounds):
    """Text-only card extent relative to the matched UNLOCKED lettering."""
    height, width = shape[:2]
    x, y, w, h = header_bounds
    return (max(0, int(x - 1.65*w)), max(0, int(y - .5*h)),
            min(width, int(x + 1.25*w)), min(height, int(y + 4.5*h)))
