import argparse
import json
import re
import sys
import time
from datetime import datetime, timezone

import cv2
import mss
import numpy as np
from rapidocr_onnxruntime import RapidOCR

UNLOCK_RE = re.compile(r"\b(MILITARY|SPECIAL|COMPLETIONIST|PRESTIGE)\s+CAMO\s+(\d+)\b", re.I)
CAMO_RE = re.compile(r"\b([A-Z][A-Z0-9' .\-]{2,30})\s+CAMO\b", re.I)


def emit(payload):
    print(json.dumps(payload, ensure_ascii=True), flush=True)


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def normalize_ocr_line(text):
    text = re.sub(r"\s+", " ", str(text or "").strip())
    text = re.sub(r"\bCAM0\b", "CAMO", text, flags=re.I)
    text = re.sub(r"\bUNL0CKED\b", "UNLOCKED", text, flags=re.I)
    text = re.sub(r"\bUNLOCKE[D0]\b", "UNLOCKED", text, flags=re.I)
    return text


def parse_text(lines):
    clean = [normalize_ocr_line(x) for x in lines if x and str(x).strip()]
    clean = [x for x in clean if x]
    if not clean:
        return None

    joined = " | ".join(clean)
    upper = [x.upper() for x in clean]
    unlock_idx = next((i for i, x in enumerate(upper) if "UNLOCK" in x or "NLOCK" in x), None)
    if unlock_idx is None:
        return None

    weapon = None
    for candidate in upper[unlock_idx + 1:unlock_idx + 6]:
        if "CAMO" not in candidate and len(candidate) >= 2:
            weapon = candidate
            break

    for line in upper:
        m = UNLOCK_RE.search(line)
        if m:
            return {
                "type": "unlock",
                "weapon": weapon or "UNKNOWN",
                "family": f"{m.group(1).upper()} CAMO",
                "number": int(m.group(2)),
                "camo": None,
                "rawText": joined,
                "timestamp": utc_now(),
            }

    for line in upper:
        m = CAMO_RE.search(line)
        if m and not any(x in line for x in ("MILITARY", "SPECIAL", "COMPLETIONIST", "PRESTIGE")):
            return {
                "type": "unlock",
                "weapon": weapon or "UNKNOWN",
                "family": None,
                "number": None,
                "camo": m.group(1).strip(),
                "rawText": joined,
                "timestamp": utc_now(),
            }

    return None


def fingerprint(gray):
    small = cv2.resize(gray, (48, 27), interpolation=cv2.INTER_AREA)
    return small.astype(np.int16)


def text_activity(gray):
    small = cv2.resize(gray, (140, 79), interpolation=cv2.INTER_AREA)
    _, bright = cv2.threshold(small, 190, 255, cv2.THRESH_BINARY)
    return float(np.count_nonzero(bright)) / float(bright.size)


def ocr_lines(ocr, image):
    result, _ = ocr(image)
    if not result:
        return [], 0.0
    good = [item for item in result if len(item) >= 3 and float(item[2]) >= 0.26]
    lines = [item[1] for item in good]
    confidence = float(np.mean([item[2] for item in good])) if good else 0.0
    return lines, confidence


def scaled_region(monitor, reference_width, reference_height, scale_x, scale_y, spec):
    ref_left = int(reference_width * spec["x"])
    ref_top = int(reference_height * spec["y"])
    ref_width = int(reference_width * spec["width"])
    ref_height = int(reference_height * spec["height"])
    region = {
        "left": monitor["left"] + int(ref_left * scale_x),
        "top": monitor["top"] + int(ref_top * scale_y),
        "width": max(1, int(ref_width * scale_x)),
        "height": max(1, int(ref_height * scale_y)),
    }
    region["width"] = min(region["width"], monitor["left"] + monitor["width"] - region["left"])
    region["height"] = min(region["height"], monitor["top"] + monitor["height"] - region["top"])
    return region


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--monitor", type=int, default=0, help="1-based MSS monitor index")
    p.add_argument("--left", type=int)
    p.add_argument("--top", type=int)
    p.add_argument("--width", type=int)
    p.add_argument("--height", type=int)
    p.add_argument("--fps", type=float, default=4.0)
    args = p.parse_args()

    fps = min(max(args.fps, 1.0), 4.0)
    interval = 1.0 / fps

    try:
        cv2.setNumThreads(1)
    except Exception:
        pass

    ocr = RapidOCR(det_use_dilation=True)
    last_event_key = None
    last_event_time = 0.0
    last_health = 0.0

    with mss.mss() as sct:
        if 1 <= args.monitor < len(sct.monitors):
            monitor = dict(sct.monitors[args.monitor])
            monitor_source = f"mss-{args.monitor}"
        elif None not in (args.left, args.top, args.width, args.height):
            monitor = {"left": args.left, "top": args.top, "width": args.width, "height": args.height}
            monitor_source = "electron-fallback"
        else:
            monitor = dict(sct.monitors[1])
            monitor_source = "mss-1-fallback"

        reference_width = int(args.width or monitor["width"])
        reference_height = int(args.height or monitor["height"])
        scale_x = float(monitor["width"]) / float(max(reference_width, 1))
        scale_y = float(monitor["height"]) / float(max(reference_height, 1))

        # Two small, resolution-independent zones. The selected display in Settings is
        # always the reference coordinate system so these stay in the same relative spots.
        zone_specs = [
            {"name": "upper-right", "x": 0.58, "y": 0.05, "width": 0.40, "height": 0.40},
            {"name": "center", "x": 0.27, "y": 0.25, "width": 0.46, "height": 0.50},
        ]
        zones = []
        for spec in zone_specs:
            zones.append({
                "name": spec["name"],
                "percent": {k: spec[k] for k in ("x", "y", "width", "height")},
                "region": scaled_region(monitor, reference_width, reference_height, scale_x, scale_y, spec),
                "last_fp": None,
                "baseline_activity": None,
                "last_ocr": 0.0,
            })

        emit({
            "type": "status",
            "message": "detector-ready",
            "monitor": args.monitor,
            "monitorSource": monitor_source,
            "monitorBounds": monitor,
            "settingsResolution": {"width": reference_width, "height": reference_height},
            "captureScale": {"x": round(scale_x, 4), "y": round(scale_y, 4)},
            "zones": [{"name": z["name"], "percent": z["percent"], "region": z["region"]} for z in zones],
            "fps": fps,
        })

        while True:
            started = time.perf_counter()
            now = time.monotonic()

            for zone in zones:
                frame = np.asarray(sct.grab(zone["region"]), dtype=np.uint8)
                bgr = frame[:, :, :3]
                gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
                fp = fingerprint(gray)
                activity = text_activity(gray)

                if zone["baseline_activity"] is None:
                    zone["baseline_activity"] = activity
                else:
                    zone["baseline_activity"] = zone["baseline_activity"] * 0.99 + activity * 0.01

                mean_delta = 999.0
                if zone["last_fp"] is not None:
                    mean_delta = float(np.mean(np.abs(fp - zone["last_fp"])))
                zone["last_fp"] = fp

                activity_spike = activity > (zone["baseline_activity"] + 0.0015)
                visual_change = mean_delta >= 1.5
                strong_change = mean_delta >= 2.9

                # Each small zone gets its own trigger. Heartbeat is intentionally slow so
                # two-zone coverage stays lightweight while still catching missed animations.
                heartbeat_due = (now - zone["last_ocr"]) >= 6.0
                burst_due = (now - zone["last_ocr"]) >= 0.60 and (visual_change or activity_spike)
                if not (heartbeat_due or burst_due):
                    continue

                zone["last_ocr"] = now
                lines, confidence = ocr_lines(ocr, bgr)
                event = parse_text(lines)

                if not event and (strong_change or activity_spike):
                    h, w = bgr.shape[:2]
                    focus = bgr[int(h * 0.08):int(h * 0.92), int(w * 0.08):int(w * 0.92)]
                    focus_gray = cv2.cvtColor(focus, cv2.COLOR_BGR2GRAY)
                    focus_gray = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(focus_gray)
                    focus_up = cv2.resize(focus_gray, None, fx=1.20, fy=1.20, interpolation=cv2.INTER_CUBIC)
                    focus_lines, focus_conf = ocr_lines(ocr, focus_up)
                    if focus_lines:
                        merged = list(lines)
                        for value in focus_lines:
                            if value not in merged:
                                merged.append(value)
                        lines = merged
                        confidence = max(confidence, focus_conf)
                        event = parse_text(lines)

                if event:
                    event["confidence"] = round(confidence, 3)
                    event["zone"] = zone["name"]
                    event_key = (event.get("weapon"), event.get("family"), event.get("number"), event.get("camo"))
                    if event_key != last_event_key or (now - last_event_time) > 8.0:
                        emit(event)
                        last_event_key = event_key
                        last_event_time = now

            if (now - last_health) >= 10.0:
                emit({
                    "type": "capture-health",
                    "monitor": args.monitor,
                    "settingsResolution": {"width": reference_width, "height": reference_height},
                    "zoneCount": len(zones),
                    "timestamp": utc_now(),
                })
                last_health = now

            elapsed = time.perf_counter() - started
            if elapsed < interval:
                time.sleep(interval - elapsed)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
    except Exception as exc:
        emit({"type": "error", "message": str(exc)})
        sys.exit(1)
