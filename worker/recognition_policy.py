"""Conservative recognition policy layered over detector_entry.

The base entrypoint intentionally favors recall. This policy prevents the expensive thumbnail
matcher and fuzzy named-camo recovery from treating ordinary HUD/gameplay text as an unlock.
"""
from __future__ import annotations

import detector_entry as entry

_POPUP_MATCH_GATE = 0.42
_COMPLETIONIST_GATE = 0.50
_popup_scores = {}

_original_match_frame = entry.matcher.match_frame
_original_parse = entry.core.parse_candidate


def _zone_name():
    return str(entry._state.get("current_zone") or "unknown").lower()


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


entry.matcher.match_frame = _guarded_match_frame
entry.core.parse_candidate = _guarded_parse_candidate
