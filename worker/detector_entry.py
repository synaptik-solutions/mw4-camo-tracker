"""Detector entrypoint that layers thumbnail cross-checking onto the stable OCR worker."""

from __future__ import annotations

import difflib
import time

import numpy as np

import detector as core
import mss as capture_mss
from camo_reference import CamoReferenceMatcher

matcher = CamoReferenceMatcher()
matcher.start_async()

_state = {
    "match": None,
    "match_time": 0.0,
    "last_match_run": 0.0,
}


def _fresh_match(max_age=0.9):
    match = _state.get("match")
    if not match:
        return None
    if time.monotonic() - float(_state.get("match_time") or 0.0) > max_age:
        return None
    return match


def _name_similarity(a, b):
    ca = core.compact_text(a or "")
    cb = core.compact_text(b or "")
    if not ca or not cb:
        return 0.0
    return difflib.SequenceMatcher(None, ca, cb).ratio()


# Capture each region exactly as before, but run the cheap thumbnail matcher against the
# same pixels. This keeps image matching synchronized with the OCR frame without changing
# monitor/capture behavior.
_original_grab = capture_mss.mss.grab


def _grab_with_image_match(self, region):
    frame = _original_grab(self, region)
    now = time.monotonic()
    # At the detector's 4 Hz ceiling this normally runs once per grabbed frame. Keep a small
    # guard anyway so two overlapping zones do not waste CPU within the same instant.
    if matcher.ready and now - _state["last_match_run"] >= 0.08:
        _state["last_match_run"] = now
        try:
            array = np.asarray(frame, dtype=np.uint8)
            bgr = array[:, :, :3]
            match = matcher.match_frame(bgr)
        except Exception:
            match = None
        _state["match"] = match
        _state["match_time"] = now if match else 0.0
    elif not matcher.ready:
        _state["match"] = None
        _state["match_time"] = 0.0
    return frame


capture_mss.mss.grab = _grab_with_image_match


# Add the image result to parsed OCR candidates. Exact family/number text still comes from
# OCR; an image never changes MILITARY CAMO 8 into another number. Named camos may be
# corrected to the canonical image-library spelling when the visual and OCR names agree.
_original_parse = core.parse_candidate


def _parse_with_image_crosscheck(lines):
    candidate = _original_parse(lines)
    image_match = _fresh_match()

    if candidate and image_match:
        candidate["imageMatch"] = image_match["name"]
        candidate["imageScore"] = float(image_match["score"])
        if candidate.get("kind") == "named":
            agreement = _name_similarity(candidate.get("camo"), image_match.get("name"))
            candidate["imageAgreement"] = agreement
            if image_match["score"] >= 0.72 and agreement >= 0.66:
                candidate["camo"] = image_match["name"]
        return candidate

    # Recovery mode: OCR got enough of the card to identify the weapon but failed to read
    # the camo line. Only a very strong thumbnail match can create a named-camo candidate.
    if candidate is None and image_match and image_match["score"] >= 0.86:
        clean = [core.normalize_ocr_line(x) for x in lines if x and str(x).strip()]
        weapon = core.fuzzy_weapon(clean)
        joined = " | ".join(clean)
        upper = joined.upper()
        context_ok = "UNLOCK" in upper or "CAMO" in upper or image_match["score"] >= 0.92
        if weapon and context_ok:
            return {
                "kind": "named",
                "weapon": weapon,
                "camo": image_match["name"],
                "rawText": joined,
                "imageMatch": image_match["name"],
                "imageScore": float(image_match["score"]),
                "imageAgreement": 1.0,
                "imageRecovered": True,
            }

    return candidate


core.parse_candidate = _parse_with_image_crosscheck


# A strong image hit is an independent visual vote. We only boost OCR confidence when the
# OCR itself sees unlock/camo-like text or already parses a candidate, preventing colorful
# gameplay from becoming a false unlock.
_original_read = core.read_frame_variants


def _read_with_image_vote(ocr, bgr, aggressive=False):
    lines, confidence = _original_read(ocr, bgr, aggressive=aggressive)
    image_match = _fresh_match()
    if image_match and image_match["score"] >= 0.74:
        joined = " ".join(core.normalize_ocr_line(x).upper() for x in lines)
        parsed = _original_parse(lines)
        if parsed or "CAMO" in joined or "UNLOCK" in joined:
            confidence = max(float(confidence), min(0.64, 0.36 + image_match["score"] * 0.30))
    return lines, confidence


core.read_frame_variants = _read_with_image_vote


# Surface image evidence in the unlock event and capture diagnostics so misses can be
# diagnosed without guessing whether OCR, popup layout, or thumbnail matching failed.
def _emit_candidate(candidate, confidence, zone_name):
    payload = {
        "type": "unlock",
        "weapon": candidate.get("weapon") or "UNKNOWN",
        "family": candidate.get("family") if candidate["kind"] == "family" else None,
        "number": candidate.get("number") if candidate["kind"] == "family" else None,
        "camo": candidate.get("camo") if candidate["kind"] == "named" else None,
        "rawText": candidate.get("rawText", ""),
        "confidence": round(float(confidence), 3),
        "zone": zone_name,
        "timestamp": core.utc_now(),
        "imageMatch": candidate.get("imageMatch"),
        "imageScore": round(float(candidate.get("imageScore") or 0.0), 3),
        "imageAgreement": round(float(candidate.get("imageAgreement") or 0.0), 3),
        "imageRecovered": bool(candidate.get("imageRecovered")),
    }
    core.emit(payload)
    return (payload.get("weapon"), payload.get("family"), payload.get("number"), payload.get("camo"))


core.emit_candidate = _emit_candidate

_original_emit = core.emit


def _emit_with_image_status(payload):
    if isinstance(payload, dict):
        if payload.get("type") == "status" and payload.get("message") == "detector-ready":
            payload = dict(payload)
            payload["camoImageMatching"] = True
            payload["imageReferenceReady"] = matcher.ready
            payload["imageReferenceCount"] = matcher.count
        elif payload.get("type") == "capture-health":
            payload = dict(payload)
            current = _fresh_match(1.5)
            payload["imageReferenceReady"] = matcher.ready
            payload["imageReferenceCount"] = matcher.count
            payload["imageReferenceError"] = matcher.last_error
            payload["lastImageMatch"] = current.get("name") if current else None
            payload["lastImageScore"] = round(float(current.get("score") or 0.0), 3) if current else 0.0
        elif payload.get("type") == "ocr-debug":
            payload = dict(payload)
            current = _fresh_match(1.0)
            payload["imageMatch"] = current.get("name") if current else None
            payload["imageScore"] = round(float(current.get("score") or 0.0), 3) if current else 0.0
    _original_emit(payload)


core.emit = _emit_with_image_status


if __name__ == "__main__":
    try:
        core.main()
    except KeyboardInterrupt:
        pass
    except Exception as exc:
        core.emit({"type": "error", "message": str(exc)})
        raise
