"""Detector entrypoint that layers thumbnail cross-checking and weapon anchoring onto OCR."""

from __future__ import annotations

import difflib
import time

import numpy as np

import detector as core
import capture_backend as capture_mss
from camo_reference import CamoReferenceMatcher

# detector.py imports the normal mss API, but this entrypoint replaces it with our hybrid
# Windows -> DXGI -> real MSS backend before core.main() creates its capture object.
core.mss = capture_mss

matcher = CamoReferenceMatcher()
matcher.start_async()

_state = {
    "matches": {},
    "match_times": {},
    "last_match_run": {},
    "current_zone": None,
    "weapon_anchor": None,
    "weapon_anchor_time": 0.0,
    "capture_backend": None,
}
_region_names = {}


def _fresh_match(zone_name=None, max_age=1.35):
    zone = str(zone_name or _state.get("current_zone") or "unknown").lower()
    match = _state["matches"].get(zone)
    if not match:
        return None
    if time.monotonic() - float(_state["match_times"].get(zone) or 0.0) > max_age:
        return None
    return match


def _fresh_weapon(max_age=12.0):
    weapon = _state.get("weapon_anchor")
    if not weapon:
        return None
    if time.monotonic() - float(_state.get("weapon_anchor_time") or 0.0) > max_age:
        return None
    return weapon


def _name_similarity(a, b):
    ca = core.compact_text(a or "")
    cb = core.compact_text(b or "")
    if not ca or not cb:
        return 0.0
    return difflib.SequenceMatcher(None, ca, cb).ratio()


def _region_key(region):
    return (int(region.get("left",0)), int(region.get("top",0)), int(region.get("width",0)), int(region.get("height",0)))


_original_scaled_region = core.scaled_region

def _scaled_region_with_name(monitor, reference_width, reference_height, scale_x, scale_y, spec):
    region = _original_scaled_region(monitor, reference_width, reference_height, scale_x, scale_y, spec)
    _region_names[_region_key(region)] = str(spec.get("name") or "").lower()
    return region

core.scaled_region = _scaled_region_with_name

_original_grab = capture_mss.mss.grab

def _grab_with_image_match(self, region):
    frame = _original_grab(self, region)
    now = time.monotonic()
    zone_name = str(_region_names.get(_region_key(region)) or "unknown").lower()
    _state["current_zone"] = zone_name
    _state["capture_backend"] = getattr(self, "backend", None)

    if "weapon" in zone_name:
        _state["matches"].pop(zone_name, None)
        _state["match_times"].pop(zone_name, None)
        return frame

    last_run = float(_state["last_match_run"].get(zone_name) or 0.0)
    if matcher.ready and now - last_run >= 0.06:
        _state["last_match_run"][zone_name] = now
        try:
            bgr = np.asarray(frame, dtype=np.uint8)[:, :, :3]
            match = matcher.match_frame(bgr)
        except Exception:
            match = None
        if match:
            _state["matches"][zone_name] = match
            _state["match_times"][zone_name] = now
        else:
            _state["matches"].pop(zone_name, None)
            _state["match_times"].pop(zone_name, None)
    elif not matcher.ready:
        _state["matches"].pop(zone_name, None)
        _state["match_times"].pop(zone_name, None)
    return frame

capture_mss.mss.grab = _grab_with_image_match

_original_parse = core.parse_candidate

def _parse_with_image_crosscheck(lines):
    clean = [core.normalize_ocr_line(x) for x in lines if x and str(x).strip()]
    zone_name = str(_state.get("current_zone") or "unknown").lower()
    if "weapon" in zone_name:
        weapon = core.fuzzy_weapon(clean)
        if weapon:
            _state["weapon_anchor"] = weapon
            _state["weapon_anchor_time"] = time.monotonic()
        return None

    candidate = _original_parse(lines)
    image_match = _fresh_match(zone_name)
    anchor = _fresh_weapon()
    if candidate:
        if (not candidate.get("weapon") or candidate.get("weapon") == "UNKNOWN") and anchor:
            candidate["weapon"] = anchor
            candidate["weaponAnchored"] = True
        if image_match:
            candidate["imageMatch"] = image_match["name"]
            candidate["imageScore"] = float(image_match["score"])
            if candidate.get("kind") == "named":
                agreement = _name_similarity(candidate.get("camo"), image_match.get("name"))
                candidate["imageAgreement"] = agreement
                if image_match["score"] >= 0.66 and agreement >= 0.58:
                    candidate["camo"] = image_match["name"]
        return candidate

    if image_match and image_match["score"] >= 0.80:
        weapon = core.fuzzy_weapon(clean) or anchor
        joined = " | ".join(clean)
        upper = joined.upper()
        if weapon and ("UNLOCK" in upper or "CAMO" in upper or image_match["score"] >= 0.88):
            return {"kind":"named","weapon":weapon,"camo":image_match["name"],"rawText":joined,"imageMatch":image_match["name"],"imageScore":float(image_match["score"]),"imageAgreement":1.0,"imageRecovered":True,"weaponAnchored":bool(anchor and weapon==anchor)}
    return candidate

core.parse_candidate = _parse_with_image_crosscheck

_original_read = core.read_frame_variants

def _read_with_image_vote(ocr, bgr, aggressive=False):
    lines, confidence = _original_read(ocr, bgr, aggressive=aggressive)
    zone_name = str(_state.get("current_zone") or "unknown").lower()
    image_match = _fresh_match(zone_name)
    if image_match and image_match["score"] >= 0.66:
        joined = " ".join(core.normalize_ocr_line(x).upper() for x in lines)
        parsed = _original_parse(lines)
        if parsed or "CAMO" in joined or "UNLOCK" in joined:
            confidence = max(float(confidence), min(0.66, 0.35 + image_match["score"] * 0.34))
    return lines, confidence

core.read_frame_variants = _read_with_image_vote


def _emit_candidate(candidate, confidence, zone_name):
    payload={"type":"unlock","weapon":candidate.get("weapon") or "UNKNOWN","family":candidate.get("family") if candidate["kind"]=="family" else None,"number":candidate.get("number") if candidate["kind"]=="family" else None,"camo":candidate.get("camo") if candidate["kind"]=="named" else None,"rawText":candidate.get("rawText", ""),"confidence":round(float(confidence),3),"zone":zone_name,"timestamp":core.utc_now(),"imageMatch":candidate.get("imageMatch"),"imageScore":round(float(candidate.get("imageScore") or 0.0),3),"imageAgreement":round(float(candidate.get("imageAgreement") or 0.0),3),"imageRecovered":bool(candidate.get("imageRecovered")),"weaponAnchored":bool(candidate.get("weaponAnchored"))}
    core.emit(payload)
    return (payload.get("weapon"),payload.get("family"),payload.get("number"),payload.get("camo"))

core.emit_candidate = _emit_candidate

_original_emit = core.emit

def _emit_with_image_status(payload):
    if isinstance(payload,dict):
        if payload.get("type")=="status" and payload.get("message")=="detector-ready":
            payload=dict(payload)
            payload["camoImageMatching"]=True
            payload["weaponReferenceZone"]=True
            payload["imageReferenceReady"]=matcher.ready
            payload["imageReferenceCount"]=matcher.count
            payload["captureBackend"]=_state.get("capture_backend")
        elif payload.get("type")=="capture-health":
            payload=dict(payload)
            zones=[]
            for item in payload.get("zones",[]):
                z=dict(item)
                zone_name=str(z.get("name") or "unknown").lower()
                current=_fresh_match(zone_name,1.8)
                z["imageMatch"]=current.get("name") if current else None
                z["imageScore"]=round(float(current.get("score") or 0.0),3) if current else 0.0
                zones.append(z)
            payload["zones"]=zones
            payload["imageReferenceReady"]=matcher.ready
            payload["imageReferenceCount"]=matcher.count
            payload["imageReferenceError"]=matcher.last_error
            payload["weaponAnchor"]=_fresh_weapon()
            payload["captureBackend"]=_state.get("capture_backend")
        elif payload.get("type")=="ocr-debug":
            payload=dict(payload)
            zone_name=str(payload.get("zone") or _state.get("current_zone") or "unknown").lower()
            current=_fresh_match(zone_name,1.5)
            payload["imageMatch"]=current.get("name") if current else None
            payload["imageScore"]=round(float(current.get("score") or 0.0),3) if current else 0.0
            payload["activeZone"]=zone_name
            payload["weaponAnchor"]=_fresh_weapon()
            payload["captureBackend"]=_state.get("capture_backend")
    _original_emit(payload)

core.emit = _emit_with_image_status

if __name__ == "__main__":
    try:
        core.main()
    except KeyboardInterrupt:
        pass
    except Exception as exc:
        core.emit({"type":"error","message":str(exc)})
        raise
