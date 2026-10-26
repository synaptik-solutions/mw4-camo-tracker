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
CAMO_RE = re.compile(r"\b([A-Z][A-Z0-9' -]{2,30})\s+CAMO\b", re.I)


def emit(payload):
    print(json.dumps(payload, ensure_ascii=False), flush=True)


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def parse_text(lines):
    clean = [re.sub(r"\s+", " ", x.strip()) for x in lines if x and x.strip()]
    if not clean:
        return None
    joined = " | ".join(clean)
    upper = [x.upper() for x in clean]
    if not any("UNLOCK" in x for x in upper):
        return None

    weapon = None
    unlock_idx = next((i for i, x in enumerate(upper) if "UNLOCK" in x), None)
    if unlock_idx is not None:
        for candidate in upper[unlock_idx + 1:unlock_idx + 4]:
            if "CAMO" not in candidate and len(candidate) >= 3:
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
        if m and "MILITARY" not in line and "SPECIAL" not in line and "COMPLETIONIST" not in line and "PRESTIGE" not in line:
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
    small = cv2.resize(gray, (96, 54), interpolation=cv2.INTER_AREA)
    return small.astype(np.int16)


def text_activity(gray):
    # Cheap signal for bright HUD text. This runs every check; OCR does not.
    small = cv2.resize(gray, (320, 180), interpolation=cv2.INTER_AREA)
    _, bright = cv2.threshold(small, 205, 255, cv2.THRESH_BINARY)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 1))
    bright = cv2.morphologyEx(bright, cv2.MORPH_OPEN, kernel)
    return float(np.count_nonzero(bright)) / float(bright.size)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--left", type=int, required=True)
    p.add_argument("--top", type=int, required=True)
    p.add_argument("--width", type=int, required=True)
    p.add_argument("--height", type=int, required=True)
    p.add_argument("--fps", type=float, default=4.0)
    args = p.parse_args()

    fps = min(max(args.fps, 1.0), 8.0)
    interval = 1.0 / fps

    # Broad right-side region using percentages so 1080p/1440p both work.
    region = {
        "left": args.left + int(args.width * 0.54),
        "top": args.top + int(args.height * 0.04),
        "width": max(220, int(args.width * 0.44)),
        "height": max(220, int(args.height * 0.72)),
    }

    ocr = RapidOCR(det_use_dilation=False)
    last_fp = None
    baseline_activity = None
    last_ocr = 0.0
    last_event_key = None
    last_event_time = 0.0

    emit({"type":"status","message":"detector-ready","region":region,"fps":fps})

    with mss.mss() as sct:
        while True:
            started = time.perf_counter()
            frame = np.asarray(sct.grab(region), dtype=np.uint8)
            gray = cv2.cvtColor(frame, cv2.COLOR_BGRA2GRAY)
            fp = fingerprint(gray)
            activity = text_activity(gray)

            if baseline_activity is None:
                baseline_activity = activity
            else:
                baseline_activity = baseline_activity * 0.97 + activity * 0.03

            changed = True
            if last_fp is not None:
                changed = float(np.mean(np.abs(fp - last_fp))) >= 4.0
            last_fp = fp

            # OCR is intentionally throttled. We require both visible change and
            # above-baseline bright-text activity before waking the OCR engine.
            now = time.monotonic()
            activity_spike = activity > (baseline_activity + 0.0035)
            can_ocr = (now - last_ocr) >= 0.85

            if changed and activity_spike and can_ocr:
                last_ocr = now
                # Upscale once for OCR; only happens on likely notification activity.
                ocr_img = cv2.resize(frame[:, :, :3], None, fx=1.15, fy=1.15, interpolation=cv2.INTER_LINEAR)
                result, _ = ocr(ocr_img)
                if result:
                    lines = [item[1] for item in result if len(item) >= 3 and float(item[2]) >= 0.45]
                    event = parse_text(lines)
                    if event:
                        event["confidence"] = round(float(np.mean([item[2] for item in result if len(item) >= 3])), 3)
                        key = (event.get("weapon"), event.get("family"), event.get("number"), event.get("camo"))
                        if key != last_event_key or (now - last_event_time) > 8.0:
                            emit(event)
                            last_event_key = key
                            last_event_time = now

            elapsed = time.perf_counter() - started
            if elapsed < interval:
                time.sleep(interval - elapsed)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
    except Exception as exc:
        emit({"type":"error","message":str(exc)})
        sys.exit(1)
