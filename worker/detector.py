import argparse
import difflib
import json
import re
import sys
import time
from datetime import datetime, timezone

import cv2
import mss
import numpy as np
from rapidocr_onnxruntime import RapidOCR

from popup_signature import find_popup_header, popup_card_bounds
from capture_pipeline import CapturePump

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
        (r"\bMIL[1ILT][1ILT]ARY\b", "MILITARY"),
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


def non_camo_banner(lines):
    joined = " | ".join(normalize_ocr_line(x) for x in lines if x).upper()
    return bool(re.search(r"\b(WEAPON\s*LEVEL|LEVEL\s*UP|RANK\s*UP|BATTLE\s*PASS|ATTACHMENT|XP\s*TOKEN|NEW\s*UNLOCK|KILL\s*STREAK|BEST\s*PLAY)\b", joined))


def parse_candidate(lines):
    clean = [normalize_ocr_line(x) for x in lines if x and str(x).strip()]
    clean = [x for x in clean if x]
    if not clean or non_camo_banner(clean):
        return None
    joined = " | ".join(clean)
    compact = re.sub(r"[^A-Z0-9]+", " ", joined.upper())
    compact = normalize_ocr_line(compact).upper()
    weapon = fuzzy_weapon(clean) or "UNKNOWN"

    # Do not require the small UNLOCKED header; OCR often misses it.
    match = next((m for m in UNLOCK_RE.finditer(compact)
                  if m.group(1).upper() != "MILITARY" or 1 <= int(m.group(2)) <= 8), None)
    if match:
        return {
            "kind": "family",
            "weapon": weapon,
            "family": f"{match.group(1).upper()} CAMO",
            "number": int(match.group(2)),
            "rawText": joined,
        }

    # A numbered family title missing its digit is incomplete, not a named camo.
    if re.search(r"\b(MILITARY|SPECIAL|COMPLETIONIST|PRESTIGE)\s+CAMO\b", compact):
        return None

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


def ocr_lines(ocr, image, min_conf=0.15, focus_popup=False, bounds=None):
    result, _ = ocr(image)
    if not result:
        return [], 0.0
    good = [item for item in result if len(item) >= 3 and float(item[2]) >= min_conf]
    if bounds is not None:
        x0, y0, x1, y1 = bounds
        good = [item for item in good if x0 <= np.mean(np.asarray(item[0])[:, 0]) <= x1
                and y0 <= np.mean(np.asarray(item[0])[:, 1]) <= y1]
    lines = [item[1] for item in good]
    confidence = float(np.mean([item[2] for item in good])) if good else 0.0
    if focus_popup:
        # Full-zone text detection can drop the small camo digit. Use the OCR header
        # bounds to enlarge only its card, preserving positions across resolutions.
        for item in good:
            if compact_text(item[1]) != "UNLOCKED":
                continue
            points = np.asarray(item[0])
            x0, y0 = points.min(axis=0)
            x1, y1 = points.max(axis=0)
            bw, bh = max(1, x1-x0), max(1, y1-y0)
            h, w = image.shape[:2]
            card = image[max(0, int(y0-bh)):min(h, int(y1+3.5*bh)),
                         max(0, int(x0-2.8*bw)):min(w, int(x1+.2*bw))]
            if card.size:
                scale = min(4.0, max(1.0, 51.0 / bh))
                enlarged = cv2.resize(card, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
                more, more_conf = ocr_lines(ocr, enlarged, min_conf)
                lines = merge_lines(more, lines)
                confidence = max(confidence, more_conf)
            break
    return lines, confidence


def merge_lines(existing, incoming):
    merged = list(existing)
    seen = {normalize_ocr_line(x).upper() for x in merged}
    for value in incoming:
        norm = normalize_ocr_line(value)
        if norm and norm.upper() not in seen:
            merged.append(norm)
            seen.add(norm.upper())
    return merged[-50:]


def complete_candidate(lines, confidence):
    candidate = parse_candidate(lines)
    return bool(candidate and candidate.get("weapon") not in (None, "UNKNOWN") and confidence >= .45)


def read_frame_variants(ocr, bgr, aggressive=False):
    header = find_popup_header(bgr)
    if not header:
        return [], 0.
    bounds = popup_card_bounds(bgr.shape, header[1])
    x0, y0, x1, y1 = bounds
    card = bgr[y0:y1, x0:x1]
    scale = min(3., max(1., 48. / max(1, header[1][3])))
    enlarged = cv2.resize(card, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    lines, confidence = ocr_lines(ocr, enlarged, .15)
    if non_camo_banner(lines) or complete_candidate(lines, confidence):
        return lines, confidence

    gray = cv2.cvtColor(enlarged, cv2.COLOR_BGR2GRAY)
    contrast = cv2.createCLAHE(clipLimit=2., tileGridSize=(8, 8)).apply(gray)
    more, more_conf = ocr_lines(ocr, contrast, .15)
    lines = merge_lines(lines, more)
    confidence = max(confidence, more_conf)
    if non_camo_banner(lines) or complete_candidate(lines, confidence):
        return lines, confidence

    # Detection at the original zone scale sometimes reads the short gun name better.
    # Only accept boxes inside this card, never text from another banner or the HUD.
    more, more_conf = ocr_lines(ocr, bgr, .15, bounds=bounds)
    return merge_lines(lines, more), max(confidence, more_conf)


def inspect_capture_frame(frame, zone_name):
    bgr = np.asarray(frame, dtype=np.uint8)[:, :, :3]
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    sample = cv2.resize(gray, (96, 54), interpolation=cv2.INTER_AREA)
    header = None if "weapon" in zone_name else find_popup_header(bgr)
    return header, {"mean": round(float(np.mean(sample)), 2),
                    "stddev": round(float(np.std(sample)), 2),
                    "activity": round(text_activity(gray), 5),
                    "popupScore": round(float(header[0]), 3) if header else 0.}


def prepare_frame(bgr, zone_name, header_score, backend):
    """Entrypoint may attach recognition context here; never run it in capture."""


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
        "timestamp": candidate.get("capturedAt") or utc_now(),
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
    try:
        cv2.setNumThreads(1)
    except Exception:
        pass

    ocr = RapidOCR(det_use_dilation=True, use_cls=False,
                   intra_op_num_threads=1, inter_op_num_threads=1)
    recent_events = {}
    last_health = 0.0
    try:
        zone_specs = sanitize_zones(json.loads(args.zones)) if args.zones else DEFAULT_ZONES
    except Exception:
        zone_specs = DEFAULT_ZONES

    with CapturePump(mss.mss, inspect_capture_frame, utc_now, fps) as sct:
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
                "last_ocr_text": "",
                "last_ocr_confidence": 0.,
                "ocr_duration_ms": 0.,
                "capture_age_ms": 0.,
            })

        emit({"type": "status", "message": "detector-ready", "monitor": args.monitor, "monitorSource": monitor_source, "monitorBounds": monitor, "settingsResolution": {"width": reference_width, "height": reference_height}, "captureScale": {"x": round(scale_x, 4), "y": round(scale_y, 4)}, "zones": [{"name": z["name"], "percent": z["percent"], "region": z["region"]} for z in zones], "fps": fps, "popupLayoutTrigger": False, "popupHeaderTrigger": True, "asyncCapture": True, "maxPendingFrames": sct.queue.capacity})

        sct.configure(zones)
        by_name = {zone["name"]: zone for zone in zones}
        while True:
            sct.check_error()
            item = sct.queue.get(timeout=.25)
            now = time.monotonic()
            if item is not None and now - item.captured_at <= 15.:
                zone = by_name[item.zone]
                bgr = np.asarray(item.frame, dtype=np.uint8)[:, :, :3]
                prepare_frame(bgr, item.zone, item.header[0], item.backend)
                ocr_started = time.monotonic()
                lines, confidence = read_frame_variants(ocr, bgr, aggressive=True)
                # Every candidate comes from one captured card; do not combine separate
                # banners' weapon names, camo numbers or text across time.
                candidate = parse_candidate(lines)
                finished = time.monotonic()
                zone["last_ocr_text"] = " | ".join(lines)
                zone["last_ocr_confidence"] = confidence
                zone["ocr_duration_ms"] = round((finished - ocr_started) * 1000)
                zone["capture_age_ms"] = round((finished - item.captured_at) * 1000)
                emit({"type": "ocr-debug", "zone": item.zone,
                      "rawText": zone["last_ocr_text"], "confidence": round(confidence, 3),
                      "popupScore": round(item.header[0], 3), "popupMatch": True,
                      "ocrDurationMs": zone["ocr_duration_ms"],
                      "captureAgeMs": zone["capture_age_ms"], "timestamp": item.captured_utc})
                if candidate and confidence >= .45:
                    candidate["capturedAt"] = item.captured_utc
                    event_key = (candidate.get("weapon"), candidate.get("family"),
                                 candidate.get("number"), candidate.get("camo"))
                    recent_events = {key: at for key, at in recent_events.items() if finished - at < 60.}
                    if event_key not in recent_events:
                        saved = emit_candidate(candidate, confidence, item.zone)
                        if saved:
                            recent_events[event_key] = finished

            now = time.monotonic()
            if now - last_health >= 2.:
                latest, count, backend = sct.snapshot()
                health = []
                for zone in zones:
                    stats = latest.get(zone["name"], {})
                    health.append({"name": zone["name"], "region": zone["region"], **stats,
                                   "ocrText": zone["last_ocr_text"],
                                   "ocrConfidence": round(zone["last_ocr_confidence"], 3),
                                   "ocrDurationMs": zone["ocr_duration_ms"],
                                   "captureAgeMs": zone["capture_age_ms"]})
                emit({"type": "capture-health", "monitor": args.monitor,
                      "settingsResolution": {"width": reference_width, "height": reference_height},
                      "zones": health, "capturedFrames": count, "pendingFrames": len(sct.queue),
                      "droppedFrames": sct.queue.dropped, "captureBackend": backend,
                      "timestamp": utc_now()})
                last_health = now


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
    except Exception as exc:
        emit({"type": "error", "message": str(exc)})
        sys.exit(1)


