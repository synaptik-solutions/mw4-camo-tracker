import argparse
import difflib
import json
import re
import sys
import time
from collections import Counter
from datetime import datetime, timezone

import cv2
import mss
import numpy as np
from rapidocr_onnxruntime import RapidOCR

UNLOCK_RE = re.compile(r"\b(MILITARY|SPECIAL|COMPLETIONIST|PRESTIGE)\s+CAMO\s*#?\s*(\d+)\b", re.I)
CAMO_RE = re.compile(r"\b([A-Z][A-Z0-9' .\-]{2,30})\s+CAMO\b", re.I)
DEFAULT_ZONES = [
    {"name": "upper-right", "x": 0.58, "y": 0.05, "width": 0.40, "height": 0.40},
    {"name": "center", "x": 0.27, "y": 0.25, "width": 0.46, "height": 0.50},
]
KNOWN_WEAPONS = [
    "Axion", "Han 86", "M4", "Hyeon Burst", "Kastov 762", "Patriot XMR", "Oden", "Cronen Squall",
    "Wz.55 Striga", "ISO Nightshade", "PPSh-41", "X-58 Nyx", "VEL 46", "REZI 12", "Warlord",
    "FiNN LMG", "Type 73", "APOC-338", "MAR-9", "Oris 8.6", "Mosin-Nagant", "KG-7 Vulcan",
    "Signal 50", "Astaroth .57", "Sang 9mm", "Krait P68", ".50 GS", "Mojave .357", "PILA", "RPG-8",
    "JOKR", "PM-40 Anvil", "FSS Carbon Edge 1095",
]


def emit(payload):
    print(json.dumps(payload, ensure_ascii=True), flush=True)


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def normalize_ocr_line(text):
    text = re.sub(r"\s+", " ", str(text or "").strip())
    for pattern, value in [
        (r"\bCAM[0O]\b", "CAMO"),
        (r"\bUNL[0O]CKE[D0]?\b", "UNLOCKED"),
        (r"\bMIL1TARY\b", "MILITARY"),
        (r"\bMILITAR[VY]\b", "MILITARY"),
        (r"\bSPEC1AL\b", "SPECIAL"),
        (r"\bC[0O]MPLETI[0O]NIST\b", "COMPLETIONIST"),
        (r"\bPREST1GE\b", "PRESTIGE"),
    ]:
        text = re.sub(pattern, value, text, flags=re.I)
    return text


def compact_text(text):
    return re.sub(r"[^A-Z0-9]+", "", normalize_ocr_line(text).upper())


def fuzzy_weapon(lines):
    best_name, best_score = None, 0.0
    for raw in lines:
        candidate = normalize_ocr_line(raw).strip(" -|:[]()")
        upper = candidate.upper()
        if not candidate or "CAMO" in upper or "UNLOCK" in upper or len(candidate) > 45:
            continue
        comp = compact_text(candidate)
        if len(comp) < 2:
            continue
        for weapon in KNOWN_WEAPONS:
            score = difflib.SequenceMatcher(None, comp, compact_text(weapon)).ratio()
            if score > best_score:
                best_name, best_score = weapon, score
    return best_name if best_score >= 0.58 else None


def parse_candidate(lines):
    clean = [normalize_ocr_line(x) for x in lines if x and str(x).strip()]
    clean = [x for x in clean if x]
    if not clean:
        return None
    joined = " | ".join(clean)
    compact = re.sub(r"[^A-Z0-9]+", " ", joined.upper())
    compact = normalize_ocr_line(compact).upper()
    weapon = fuzzy_weapon(clean) or "UNKNOWN"

    # Do not require the small UNLOCKED header; OCR often misses it.
    match = UNLOCK_RE.search(compact)
    if match:
        return {
            "kind": "family",
            "weapon": weapon,
            "family": f"{match.group(1).upper()} CAMO",
            "number": int(match.group(2)),
            "rawText": joined,
        }

    for line in [x.upper() for x in clean]:
        match = CAMO_RE.search(line)
        if match and not any(x in line for x in ("MILITARY", "SPECIAL", "COMPLETIONIST", "PRESTIGE")):
            return {"kind": "named", "weapon": weapon, "camo": match.group(1).strip(), "rawText": joined}
    return None


def fingerprint(gray):
    return cv2.resize(gray, (48, 27), interpolation=cv2.INTER_AREA).astype(np.int16)


def text_activity(gray):
    small = cv2.resize(gray, (140, 79), interpolation=cv2.INTER_AREA)
    _, bright = cv2.threshold(small, 185, 255, cv2.THRESH_BINARY)
    return float(np.count_nonzero(bright)) / float(bright.size)


def popup_layout_score(bgr):
    """Cheap structural match based on the supplied MW4 unlock popup screenshot.

    The reusable visual signature is the bright yellow/green UNLOCKED tab sitting over
    a compact card with a square thumbnail at the left and high-contrast text below.
    We deliberately do not template-match the exact camo image so this works for every camo.
    """
    h, w = bgr.shape[:2]
    if h < 24 or w < 48:
        return 0.0

    max_w = 420
    scale = min(1.0, max_w / float(w))
    if scale < 1.0:
        sample = cv2.resize(bgr, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
    else:
        sample = bgr
    sh, sw = sample.shape[:2]

    hsv = cv2.cvtColor(sample, cv2.COLOR_BGR2HSV)
    # The screenshot's header is a muted yellow-green. Keep the range broad enough for
    # HDR/brightness changes while still excluding most HUD whites/oranges.
    green = cv2.inRange(hsv, np.array([25, 28, 115], dtype=np.uint8), np.array([95, 255, 255], dtype=np.uint8))
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 3))
    green = cv2.morphologyEx(green, cv2.MORPH_CLOSE, kernel)
    contours, _ = cv2.findContours(green, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    gray = cv2.cvtColor(sample, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 70, 150)
    best = 0.0
    for contour in contours:
        x, y, bw, bh = cv2.boundingRect(contour)
        if bw < max(18, int(sw * 0.035)) or bh < 3:
            continue
        ratio = bw / float(max(bh, 1))
        if ratio < 1.6 or ratio > 14.0:
            continue
        if y > sh * 0.82:
            continue

        area_ratio = (bw * bh) / float(sw * sh)
        if area_ratio < 0.0007 or area_ratio > 0.09:
            continue

        # Unlock card extends mostly left and downward from the green header.
        card_x0 = max(0, x - int(bw * 2.8))
        card_y0 = max(0, y - int(bh * 0.4))
        card_x1 = min(sw, x + int(bw * 1.15))
        card_y1 = min(sh, y + int(bh * 6.5))
        if card_x1 <= card_x0 or card_y1 <= card_y0:
            continue

        card_edges = edges[card_y0:card_y1, card_x0:card_x1]
        card_gray = gray[card_y0:card_y1, card_x0:card_x1]
        if card_edges.size == 0 or card_gray.size == 0:
            continue
        edge_density = float(np.count_nonzero(card_edges)) / float(card_edges.size)
        contrast = float(np.std(card_gray)) / 64.0

        # Search the left side of the card for a roughly square thumbnail/detail block.
        left_w = max(1, int((card_x1 - card_x0) * 0.38))
        left = card_edges[:, :left_w]
        square_hint = 0.0
        if left.size:
            lcontours, _ = cv2.findContours(left, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
            for lc in lcontours:
                lx, ly, lw, lh = cv2.boundingRect(lc)
                if min(lw, lh) < 8:
                    continue
                sq_ratio = lw / float(max(lh, 1))
                if 0.65 <= sq_ratio <= 1.45:
                    square_hint = 1.0
                    break

        ratio_score = 1.0 - min(abs(ratio - 4.0) / 6.0, 1.0)
        score = 0.38 + 0.20 * ratio_score + 0.22 * min(edge_density / 0.12, 1.0) + 0.12 * min(contrast, 1.0) + 0.08 * square_hint
        best = max(best, score)

    return float(min(best, 1.0))


def ocr_lines(ocr, image, min_conf=0.15):
    result, _ = ocr(image)
    if not result:
        return [], 0.0
    good = [item for item in result if len(item) >= 3 and float(item[2]) >= min_conf]
    return [item[1] for item in good], float(np.mean([item[2] for item in good])) if good else 0.0


def merge_lines(existing, incoming):
    merged = list(existing)
    seen = {normalize_ocr_line(x).upper() for x in merged}
    for value in incoming:
        norm = normalize_ocr_line(value)
        if norm and norm.upper() not in seen:
            merged.append(norm)
            seen.add(norm.upper())
    return merged[-50:]


def read_frame_variants(ocr, bgr, aggressive=False):
    merged, best_conf = [], 0.0
    lines, conf = ocr_lines(ocr, bgr, 0.13 if aggressive else 0.18)
    merged = merge_lines(merged, lines)
    best_conf = max(best_conf, conf)

    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    clahe = cv2.createCLAHE(clipLimit=2.8 if aggressive else 2.0, tileGridSize=(8, 8)).apply(gray)
    variants = [
        cv2.resize(clahe, None, fx=1.55 if aggressive else 1.30, fy=1.55 if aggressive else 1.30, interpolation=cv2.INTER_CUBIC),
        cv2.resize(cv2.adaptiveThreshold(clahe, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 7), None, fx=1.45, fy=1.45, interpolation=cv2.INTER_CUBIC),
    ]
    for image in variants:
        more, more_conf = ocr_lines(ocr, image, 0.12 if aggressive else 0.16)
        merged = merge_lines(merged, more)
        best_conf = max(best_conf, more_conf)
    return merged, best_conf


def sanitize_zones(raw):
    zones = []
    if not isinstance(raw, list):
        return DEFAULT_ZONES
    for i, item in enumerate(raw[:4]):
        if not isinstance(item, dict):
            continue
        try:
            x = min(max(float(item.get("x", 0)), 0.0), 0.95)
            y = min(max(float(item.get("y", 0)), 0.0), 0.95)
            width = min(max(float(item.get("width", 0.1)), 0.03), 1.0 - x)
            height = min(max(float(item.get("height", 0.1)), 0.03), 1.0 - y)
        except (TypeError, ValueError):
            continue
        zones.append({"name": str(item.get("name") or f"zone-{i+1}").lower(), "x": x, "y": y, "width": width, "height": height})
    return zones or DEFAULT_ZONES


def scaled_region(monitor, reference_width, reference_height, scale_x, scale_y, spec):
    region = {
        "left": monitor["left"] + int(reference_width * spec["x"] * scale_x),
        "top": monitor["top"] + int(reference_height * spec["y"] * scale_y),
        "width": max(1, int(reference_width * spec["width"] * scale_x)),
        "height": max(1, int(reference_height * spec["height"] * scale_y)),
    }
    region["width"] = min(region["width"], monitor["left"] + monitor["width"] - region["left"])
    region["height"] = min(region["height"], monitor["top"] + monitor["height"] - region["top"])
    return region


def candidate_key(candidate):
    if not candidate:
        return None
    if candidate["kind"] == "family":
        return (candidate["family"], candidate["number"])
    return ("NAMED", compact_text(candidate.get("camo", "")))


def emit_candidate(candidate, confidence, zone_name):
    payload = {
        "type": "unlock",
        "weapon": candidate.get("weapon") or "UNKNOWN",
        "family": candidate.get("family") if candidate["kind"] == "family" else None,
        "number": candidate.get("number") if candidate["kind"] == "family" else None,
        "camo": candidate.get("camo") if candidate["kind"] == "named" else None,
        "rawText": candidate.get("rawText", ""),
        "confidence": round(confidence, 3),
        "zone": zone_name,
        "timestamp": utc_now(),
    }
    emit(payload)
    return (payload.get("weapon"), payload.get("family"), payload.get("number"), payload.get("camo"))


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--monitor", type=int, default=0)
    p.add_argument("--left", type=int)
    p.add_argument("--top", type=int)
    p.add_argument("--width", type=int)
    p.add_argument("--height", type=int)
    p.add_argument("--fps", type=float, default=4.0)
    p.add_argument("--zones", type=str, default="")
    args = p.parse_args()

    # UI supports 2/4/6 checks per second. 4 remains the recommended default; 6 is an
    # opt-in faster scan mode and stays below the native capture backend's ~10 Hz request.
    fps = min(max(args.fps, 1.0), 6.0)
    interval = 1.0 / fps
    try:
        cv2.setNumThreads(1)
    except Exception:
        pass

    ocr = RapidOCR(det_use_dilation=True)
    last_event_key = None
    last_event_time = 0.0
    last_health = 0.0
    try:
        zone_specs = sanitize_zones(json.loads(args.zones)) if args.zones else DEFAULT_ZONES
    except Exception:
        zone_specs = DEFAULT_ZONES

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
        scale_x = float(monitor["width"]) / max(reference_width, 1)
        scale_y = float(monitor["height"]) / max(reference_height, 1)
        zones = []
        for spec in zone_specs:
            zones.append({
                "name": spec["name"],
                "percent": {k: spec[k] for k in ("x", "y", "width", "height")},
                "region": scaled_region(monitor, reference_width, reference_height, scale_x, scale_y, spec),
                "last_fp": None,
                "baseline_activity": None,
                "last_ocr": 0.0,
                "last_debug": 0.0,
                "last_mean": 0.0,
                "last_stddev": 0.0,
                "last_activity": 0.0,
                "last_ocr_text": "",
                "last_ocr_confidence": 0.0,
                "last_popup_score": 0.0,
                "burst_until": 0.0,
                "next_burst_ocr": 0.0,
                "burst_attempts": 0,
                "burst_lines": [],
                "burst_votes": Counter(),
                "burst_candidates": {},
            })

        emit({"type": "status", "message": "detector-ready", "monitor": args.monitor, "monitorSource": monitor_source, "monitorBounds": monitor, "settingsResolution": {"width": reference_width, "height": reference_height}, "captureScale": {"x": round(scale_x, 4), "y": round(scale_y, 4)}, "zones": [{"name": z["name"], "percent": z["percent"], "region": z["region"]} for z in zones], "fps": fps, "popupLayoutTrigger": True})

        while True:
            started = time.perf_counter()
            now = time.monotonic()
            for zone in zones:
                frame = np.asarray(sct.grab(zone["region"]), dtype=np.uint8)
                bgr = frame[:, :, :3]
                gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
                fp = fingerprint(gray)
                activity = text_activity(gray)
                popup_score = popup_layout_score(bgr)
                zone["last_popup_score"] = popup_score
                zone["last_mean"] = float(np.mean(gray))
                zone["last_stddev"] = float(np.std(gray))
                zone["last_activity"] = activity
                zone["baseline_activity"] = activity if zone["baseline_activity"] is None else zone["baseline_activity"] * 0.99 + activity * 0.01
                mean_delta = 999.0 if zone["last_fp"] is None else float(np.mean(np.abs(fp - zone["last_fp"])))
                zone["last_fp"] = fp

                activity_spike = activity > (zone["baseline_activity"] + 0.0010)
                visual_change = mean_delta >= 1.0
                strong_change = mean_delta >= 2.0
                popup_match = popup_score >= 0.58

                if visual_change or activity_spike or popup_match:
                    # Gameplay motion keeps extending burst_until; rearm exhausted bursts
                    # so a later unlock cannot fall into the five-second heartbeat gap.
                    if now > zone["burst_until"] or zone["burst_attempts"] >= (12 if popup_match else 9):
                        zone["burst_lines"] = []
                        zone["burst_votes"] = Counter()
                        zone["burst_candidates"] = {}
                        zone["burst_attempts"] = 0
                    zone["burst_until"] = max(zone["burst_until"], now + (3.0 if popup_match else 2.2))
                    zone["next_burst_ocr"] = min(zone["next_burst_ocr"] or now, now)

                in_burst = now <= zone["burst_until"] and zone["burst_attempts"] < (12 if popup_match else 9)
                burst_due = in_burst and now >= zone["next_burst_ocr"]
                heartbeat_due = (now - zone["last_ocr"]) >= 5.0
                if not (burst_due or heartbeat_due):
                    continue

                zone["last_ocr"] = now
                if burst_due:
                    zone["burst_attempts"] += 1
                    zone["next_burst_ocr"] = now + (0.16 if popup_match else 0.20)

                lines, confidence = read_frame_variants(ocr, bgr, aggressive=(strong_change or burst_due or popup_match))
                zone["burst_lines"] = merge_lines(zone["burst_lines"], lines)
                candidate = parse_candidate(zone["burst_lines"] if in_burst else lines)
                if candidate:
                    ckey = candidate_key(candidate)
                    zone["burst_votes"][ckey] += 1
                    zone["burst_candidates"][ckey] = candidate

                debug_text = " | ".join(zone["burst_lines"] if in_burst else lines)
                zone["last_ocr_text"] = debug_text
                zone["last_ocr_confidence"] = confidence
                if now - zone["last_debug"] >= 1.2:
                    emit({"type": "ocr-debug", "zone": zone["name"], "rawText": debug_text, "confidence": round(confidence, 3), "delta": round(mean_delta, 3), "activity": round(activity, 5), "popupScore": round(popup_score, 3), "popupMatch": bool(popup_match), "burst": bool(in_burst), "burstAttempt": zone["burst_attempts"], "timestamp": utc_now()})
                    zone["last_debug"] = now

                winner = None
                if zone["burst_votes"]:
                    vote_key, votes = zone["burst_votes"].most_common(1)[0]
                    candidate_obj = zone["burst_candidates"].get(vote_key)
                    strong_single = candidate_obj and candidate_obj.get("kind") == "family" and confidence >= 0.45
                    popup_single = popup_match and candidate_obj and candidate_obj.get("kind") == "family" and confidence >= 0.28
                    if votes >= 2 or strong_single or popup_single:
                        winner = candidate_obj

                if winner:
                    event_key = (winner.get("weapon"), winner.get("family"), winner.get("number"), winner.get("camo"))
                    if event_key != last_event_key or now - last_event_time > 8.0:
                        last_event_key = emit_candidate(winner, confidence, zone["name"])
                        last_event_time = now
                    zone["burst_until"] = 0.0
                    zone["burst_attempts"] = 0
                    zone["burst_lines"] = []
                    zone["burst_votes"] = Counter()
                    zone["burst_candidates"] = {}

            if now - last_health >= 5.0:
                emit({"type": "capture-health", "monitor": args.monitor, "settingsResolution": {"width": reference_width, "height": reference_height}, "zones": [{"name": z["name"], "region": z["region"], "mean": round(z["last_mean"], 2), "stddev": round(z["last_stddev"], 2), "activity": round(z["last_activity"], 5), "popupScore": round(z["last_popup_score"], 3), "ocrText": z["last_ocr_text"], "ocrConfidence": round(z["last_ocr_confidence"], 3), "burstActive": time.monotonic() <= z["burst_until"]} for z in zones], "timestamp": utc_now()})
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
