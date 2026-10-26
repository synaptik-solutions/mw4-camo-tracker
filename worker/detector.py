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
    small = cv2.resize(gray, (72, 40), interpolation=cv2.INTER_AREA)
    return small.astype(np.int16)


def text_activity(gray):
    small = cv2.resize(gray, (220, 124), interpolation=cv2.INTER_AREA)
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


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--monitor", type=int, default=0, help="1-based MSS monitor index")
    p.add_argument("--left", type=int)
    p.add_argument("--top", type=int)
    p.add_argument("--width", type=int)
    p.add_argument("--height", type=int)
    p.add_argument("--fps", type=float, default=4.0)
    args = p.parse_args()

    fps = min(max(args.fps, 1.0), 6.0)
    interval = 1.0 / fps

    # Limit inference parallelism. The tracker is latency-insensitive and should not
    # compete with the game for all CPU cores during an OCR pass.
    try:
        cv2.setNumThreads(1)
    except Exception:
        pass

    ocr = RapidOCR(det_use_dilation=True)
    last_fp = None
    baseline_activity = None
    last_ocr = 0.0
    last_debug = 0.0
    last_health = 0.0
    last_event_key = None
    last_event_time = 0.0

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

        # MW4 unlock cards live on the upper/right side. Keeping the capture region
        # tighter cuts memory bandwidth and OCR work substantially.
        region = {
            "left": monitor["left"] + int(monitor["width"] * 0.43),
            "top": monitor["top"],
            "width": max(420, int(monitor["width"] * 0.56)),
            "height": max(420, int(monitor["height"] * 0.82)),
        }

        emit({
            "type": "status",
            "message": "detector-ready",
            "monitor": args.monitor,
            "monitorSource": monitor_source,
            "monitorBounds": monitor,
            "region": region,
            "fps": fps,
        })

        while True:
            started = time.perf_counter()
            frame = np.asarray(sct.grab(region), dtype=np.uint8)
            bgr = frame[:, :, :3]
            gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
            fp = fingerprint(gray)
            activity = text_activity(gray)

            if baseline_activity is None:
                baseline_activity = activity
            else:
                baseline_activity = baseline_activity * 0.99 + activity * 0.01

            mean_delta = 999.0
            if last_fp is not None:
                mean_delta = float(np.mean(np.abs(fp - last_fp)))
            last_fp = fp

            now = time.monotonic()
            activity_spike = activity > (baseline_activity + 0.0014)
            visual_change = mean_delta >= 1.45
            strong_change = mean_delta >= 2.8

            # Event-driven OCR is the normal path. A much slower safety heartbeat
            # catches a missed popup without running ONNX inference every second.
            heartbeat_due = (now - last_ocr) >= 4.0
            burst_due = (now - last_ocr) >= 0.55 and (visual_change or activity_spike)
            should_ocr = heartbeat_due or burst_due

            if should_ocr:
                last_ocr = now

                # Use the raw crop first; avoid expensive full-frame upscaling unless needed.
                lines, confidence = ocr_lines(ocr, bgr)
                event = parse_text(lines)

                if not event and (strong_change or activity_spike):
                    h, w = bgr.shape[:2]
                    focus = bgr[0:int(h * 0.72), int(w * 0.20):w]
                    focus_gray = cv2.cvtColor(focus, cv2.COLOR_BGR2GRAY)
                    focus_gray = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(focus_gray)
                    focus_up = cv2.resize(focus_gray, None, fx=1.35, fy=1.35, interpolation=cv2.INTER_CUBIC)
                    focus_lines, focus_conf = ocr_lines(ocr, focus_up)
                    if focus_lines:
                        merged = list(lines)
                        for value in focus_lines:
                            if value not in merged:
                                merged.append(value)
                        lines = merged
                        confidence = max(confidence, focus_conf)
                        event = parse_text(lines)

                if lines and (now - last_debug) >= 3.0:
                    emit({
                        "type": "ocr-debug",
                        "rawText": " | ".join(normalize_ocr_line(x) for x in lines),
                        "delta": round(mean_delta, 3),
                        "activity": round(activity, 5),
                        "timestamp": utc_now(),
                    })
                    last_debug = now

                if event:
                    event["confidence"] = round(confidence, 3)
                    key = (event.get("weapon"), event.get("family"), event.get("number"), event.get("camo"))
                    if key != last_event_key or (now - last_event_time) > 8.0:
                        emit(event)
                        last_event_key = key
                        last_event_time = now

            if (now - last_health) >= 8.0:
                emit({
                    "type": "capture-health",
                    "mean": round(float(np.mean(gray)), 2),
                    "stddev": round(float(np.std(gray)), 2),
                    "activity": round(activity, 5),
                    "monitor": args.monitor,
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
