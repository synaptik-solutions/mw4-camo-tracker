"""Detector entrypoint that layers thumbnail cross-checking and weapon anchoring onto OCR."""

from __future__ import annotations

import difflib
import time
import os

import numpy as np

import detector as core
import capture_backend as capture_mss
from camo_reference import CamoReferenceMatcher

# detector.py imports the normal mss API, but this entrypoint replaces it with our hybrid
# Windows -> DXGI -> real MSS backend before core.main() creates its capture object.
core.mss = capture_mss
# Keep the emergency/default zone set aligned with Electron even if --zones is missing/bad.
core.DEFAULT_ZONES = [
    {"name": "upper-right", "x": 0.58, "y": 0.05, "width": 0.40, "height": 0.40},
    {"name": "center", "x": 0.27, "y": 0.25, "width": 0.46, "height": 0.50},
    {"name": "weapon-reference", "x": 0.52, "y": 0.62, "width": 0.44, "height": 0.22},
]

matcher = CamoReferenceMatcher()
if not os.environ.get("MW4_REFERENCE_OFFLINE"):
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
_COMPLETIONIST_NAMES = ("Gold", "Platinum", "Harmonic Break")


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


def _unambiguous_weapon(lines):
    """Return a weapon only when the reference zone supports one clear gun.

    End-of-match recap screens can contain several weapon rows at once. In that case we
    deliberately avoid setting an anchor rather than attaching camos to the wrong gun.
    """
    matched = set()
    for raw in lines:
        candidate = core.normalize_ocr_line(raw).strip(" -|:[]()")
        upper = candidate.upper()
        if not candidate or "CAMO" in upper or "UNLOCK" in upper or len(candidate) > 45:
            continue
        comp = core.compact_text(candidate)
        if len(comp) < 2:
            continue
        best_name, best_score = None, 0.0
        for weapon in core.KNOWN_WEAPONS:
            score = difflib.SequenceMatcher(None, comp, core.compact_text(weapon)).ratio()
            if score > best_score:
                best_name, best_score = weapon, score
        if best_name and best_score >= 0.68:
            matched.add(best_name)
            if len(matched) > 1:
                return None
    return next(iter(matched)) if len(matched) == 1 else None


def _best_line_agreement(lines, name):
    best = 0.0
    for line in lines:
        cleaned = core.normalize_ocr_line(line)
        cleaned = cleaned.replace("UNLOCKED", "").replace("CAMO", "").strip(" -|:[]()")
        if cleaned:
            best = max(best, _name_similarity(cleaned, name))
    return best


def _completionist_from_text(lines):
    best_name, best_score = None, 0.0
    for name in _COMPLETIONIST_NAMES:
        score = _best_line_agreement(lines, name)
        if score > best_score:
            best_name, best_score = name, score
    return best_name if best_score >= 0.74 else None


def _region_key(region):
    return (int(region.get("left",0)), int(region.get("top",0)), int(region.get("width",0)), int(region.get("height",0)))


_original_scaled_region = core.scaled_region

def _scaled_region_with_name(monitor, reference_width, reference_height, scale_x, scale_y, spec):
    region = _original_scaled_region(monitor, reference_width, reference_height, scale_x, scale_y, spec)
    _region_names[_region_key(region)] = str(spec.get("name") or "").lower()
    return region

core.scaled_region = _scaled_region_with_name

def _prepare_frame(bgr, zone_name, header_score, backend):
    # Recognition state belongs only to the OCR consumer. Capture never mutates it.
    _state["current_zone"] = zone_name
    _state["capture_backend"] = backend
    _state["popup_header_score"] = header_score
    _state["matches"].pop(zone_name, None)
    _state["match_times"].pop(zone_name, None)


core.prepare_frame = _prepare_frame


def _match_for_recovery(bgr):
    if not matcher.ready:
        return
    zone_name = str(_state.get("current_zone") or "unknown").lower()
    try:
        match = matcher.match_frame(bgr)
    except Exception:
        return
    if match:
        _state["matches"][zone_name] = match
        _state["match_times"][zone_name] = time.monotonic()


_original_parse = core.parse_candidate

def _parse_with_image_crosscheck(lines):
    clean = [core.normalize_ocr_line(x) for x in lines if x and str(x).strip()]
    zone_name = str(_state.get("current_zone") or "unknown").lower()
    if "weapon" in zone_name:
        weapon = _unambiguous_weapon(clean)
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

    weapon = core.fuzzy_weapon(clean) or anchor
    joined = " | ".join(clean)
    upper = joined.upper()

    # Completionist titles are sometimes rendered without the literal word CAMO.
    completionist = _completionist_from_text(clean)
    if completionist and weapon:
        return {
            "kind": "named", "weapon": weapon, "camo": completionist,
            "rawText": joined, "weaponAnchored": bool(anchor and weapon == anchor),
            "textRecovered": True,
        }

    # A moderate image match may recover a named camo when OCR independently reads a
    # similar title even if the UI omits the word CAMO. Requiring both signals avoids
    # making the thumbnail database a single-point source of false unlocks.
    if image_match and weapon:
        agreement = _best_line_agreement(clean, image_match["name"])
        if image_match["score"] >= 0.64 and agreement >= 0.58:
            return {
                "kind": "named", "weapon": weapon, "camo": image_match["name"],
                "rawText": joined, "imageMatch": image_match["name"],
                "imageScore": float(image_match["score"]), "imageAgreement": agreement,
                "imageRecovered": True, "weaponAnchored": bool(anchor and weapon == anchor),
            }

    return candidate

core.parse_candidate = _parse_with_image_crosscheck

_original_read = core.read_frame_variants

def _read_with_image_vote(ocr, bgr, aggressive=False):
    lines, confidence = _original_read(ocr, bgr, aggressive=aggressive)
    zone_name = str(_state.get("current_zone") or "unknown").lower()
    parsed = core.parse_candidate(lines)
    if not parsed and not core.non_camo_banner(lines):
        # Reference matching is a recovery step, never work that delays a clear text read.
        _match_for_recovery(bgr)
    image_match = _fresh_match(zone_name)
    if image_match and image_match["score"] >= 0.66:
        joined = " ".join(core.normalize_ocr_line(x).upper() for x in lines)
        parsed = _original_parse(lines)
        if parsed or "CAMO" in joined or "UNLOCK" in joined:
            confidence = max(float(confidence), min(0.66, 0.35 + image_match["score"] * 0.34))
    return lines, confidence

core.read_frame_variants = _read_with_image_vote


def _emit_candidate(candidate, confidence, zone_name):
    payload={"type":"unlock","weapon":candidate.get("weapon") or "UNKNOWN","family":candidate.get("family") if candidate["kind"]=="family" else None,"number":candidate.get("number") if candidate["kind"]=="family" else None,"camo":candidate.get("camo") if candidate["kind"]=="named" else None,"rawText":candidate.get("rawText", ""),"confidence":round(float(confidence),3),"zone":zone_name,"timestamp":candidate.get("capturedAt") or core.utc_now(),"sourceTime":candidate.get("sourceTime"),"imageMatch":candidate.get("imageMatch"),"imageScore":round(float(candidate.get("imageScore") or 0.0),3),"imageAgreement":round(float(candidate.get("imageAgreement") or 0.0),3),"imageRecovered":bool(candidate.get("imageRecovered")),"textRecovered":bool(candidate.get("textRecovered")),"weaponAnchored":bool(candidate.get("weaponAnchored"))}
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
            payload["captureBackend"]=payload.get("captureBackend") or _state.get("capture_backend")
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
            payload["captureBackend"]=payload.get("captureBackend") or _state.get("capture_backend")
        elif payload.get("type")=="ocr-debug":
            payload=dict(payload)
            zone_name=str(payload.get("zone") or _state.get("current_zone") or "unknown").lower()
            current=_fresh_match(zone_name,1.5)
            payload["imageMatch"]=current.get("name") if current else None
            payload["imageScore"]=round(float(current.get("score") or 0.0),3) if current else 0.0
            payload["activeZone"]=zone_name
            payload["weaponAnchor"]=_fresh_weapon()
            payload["captureBackend"]=payload.get("captureBackend") or _state.get("capture_backend")
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

