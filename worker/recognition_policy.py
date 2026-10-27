"""Conservative recognition policy layered over detector_entry.

The base entrypoint intentionally favors recall. This policy prevents the expensive thumbnail
matcher and fuzzy named-camo recovery from treating ordinary HUD/gameplay text as an unlock.
"""
from __future__ import annotations

import difflib

import detector_entry as entry

_POPUP_MATCH_GATE = 0.42
_COMPLETIONIST_GATE = 0.50
_popup_scores = {}

_original_match_frame = entry.matcher.match_frame
_original_parse = entry.core.parse_candidate
_original_emit_candidate = entry.core.emit_candidate


def _zone_name():
    return str(entry._state.get("current_zone") or "unknown").lower()


def _safer_fuzzy_weapon(lines):
    best_overall = None
    best_overall_score = 0.0
    for raw in lines:
        candidate = entry.core.normalize_ocr_line(raw).strip(" -|:[]()")
        upper = candidate.upper()
        if not candidate or "CAMO" in upper or "UNLOCK" in upper or len(candidate) > 45:
            continue
        comp = entry.core.compact_text(candidate)
        if len(comp) < 2:
            continue

        scored = []
        for weapon in entry.core.KNOWN_WEAPONS:
            target = entry.core.compact_text(weapon)
            score = difflib.SequenceMatcher(None, comp, target).ratio()
            scored.append((score, weapon, target))
        scored.sort(reverse=True, key=lambda x: x[0])
        score, weapon, target = scored[0]
        second = scored[1][0] if len(scored) > 1 else 0.0

        if comp == target:
            return weapon

        # Short weapon names are easy false positives in noisy HUD text. Require much
        # stronger similarity for those; longer names can tolerate realistic OCR mistakes.
        target_len = len(target)
        threshold = 0.86 if target_len <= 4 else (0.74 if target_len <= 7 else 0.63)
        margin = 0.08 if target_len <= 7 else 0.055
        if score >= threshold and (score - second) >= margin and score > best_overall_score:
            best_overall = weapon
            best_overall_score = score

    return best_overall


def _guarded_match_frame(bgr):
    zone = _zone_name()
    try:
        score = float(entry.core.popup_layout_score(bgr))
    except Exception:
        score = 0.0
    _popup_scores[zone] = score
    if score < _POPUP_MATCH_GATE:
        return None
    return _original_match_frame(bgr)


def _guarded_parse_candidate(lines):
    candidate = _original_parse(lines)
    if not candidate or not candidate.get("textRecovered"):
        return candidate

    zone = _zone_name()
    joined = " | ".join(entry.core.normalize_ocr_line(x) for x in lines if x and str(x).strip()).upper()
    popup_score = float(_popup_scores.get(zone) or 0.0)
    image_match = entry._fresh_match(zone)

    # Gold/Platinum/Harmonic Break may omit the literal word CAMO, but a fuzzy heartbeat
    # text match by itself is not enough. Require the unlock header, a structural popup
    # match, or an independently agreeing thumbnail reference.
    if "UNLOCK" in joined or popup_score >= _COMPLETIONIST_GATE or image_match:
        candidate["popupScore"] = popup_score
        return candidate
    return None


def _guarded_emit_candidate(candidate, confidence, zone_name):
    if candidate and candidate.get("kind") == "family":
        family = str(candidate.get("family") or "").upper()
        number = int(candidate.get("number") or 0)
        # MW4 launch weapons have eight numbered Military camos. Reject OCR hallucinations
        # such as "88" instead of silently writing hidden bogus progression data.
        if family == "MILITARY CAMO" and not (1 <= number <= 8):
            return None
    return _original_emit_candidate(candidate, confidence, zone_name)


entry.core.fuzzy_weapon = _safer_fuzzy_weapon
entry.matcher.match_frame = _guarded_match_frame
entry.core.parse_candidate = _guarded_parse_candidate
entry.core.emit_candidate = _guarded_emit_candidate
