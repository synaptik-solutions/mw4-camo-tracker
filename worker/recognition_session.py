"""Shared live/replay recognition, bounded retries, and failed-read diagnostics."""
import time
import re
import difflib
from completion_banner import is_completion_text, review_image
from camo_catalog import CATALOG


def compact(text):
    return ''.join(c for c in str(text or '').upper() if c.isalnum())


def supported(candidate):
    if not candidate:
        return False
    weapon = next((name for name in CATALOG if compact(name)==compact(candidate.get('weapon'))),None)
    if not weapon:
        return False
    if candidate.get('kind')=='family':
        limit = {'MILITARY CAMO':8,'SPECIAL CAMO':3,'COMPLETIONIST CAMO':3}.get(candidate.get('family'),0)
        return 1 <= int(candidate.get('number') or 0) <= limit
    return compact(candidate.get('camo')) in {compact(name) for name in CATALOG[weapon]}


class RecognitionSession:
    def __init__(self, ocr, reader, parser, prepare, emit, emit_unlock, non_camo, diagnostics=None):
        self.ocr,self.reader,self.parser,self.prepare = ocr,reader,parser,prepare
        self.emit,self.emit_unlock,self.non_camo = emit,emit_unlock,non_camo
        self.diagnostics = diagnostics
        self.recent = {}
        self.last_review = None
        self.attempts = 0
        self.failures = 0
        self.recovered = 0

    def process(self, item, queue=None):
        first_time = item.captured_at
        for attempt in range(3):
            self.prepare(item.frame,item.zone,item.header[0],item.backend)
            started = time.monotonic()
            lines, confidence = self.reader(self.ocr,item.frame[:,:,:3],aggressive=True)
            candidate = self.parser(lines)
            finished = time.monotonic()
            self.attempts += 1
            other_banner = self.non_camo(lines)
            completion = is_completion_text(lines)
            valid = not completion and not other_banner and supported(candidate) and confidence >= .45
            review = confidence >= .45 and not other_banner and completion
            reason = 'review-required' if review else 'recognized' if valid else 'other-banner' if other_banner else 'uncertain-read'
            saved = None
            if not valid and not other_banner:
                self.failures += 1
                if self.diagnostics:
                    saved = self.diagnostics.save(item,lines,confidence,reason,attempt)
            result = dict(zone=item.zone,rawText=' | '.join(lines),confidence=round(float(confidence),3),
                          ocrDurationMs=round((finished-started)*1000),
                          captureAgeMs=round(max(0.,finished-item.captured_at)*1000),
                          timestamp=item.captured_utc,popupScore=item.header[0],popupMatch=True,
                          retryAttempt=attempt,reason=reason,diagnosticId=saved,
                          sourceTime=getattr(item,'source_time',None),candidate=candidate,emitted=False)
            if review:
                at = item.source_time if getattr(item,'source_time',None) is not None else item.captured_at
                review_key = ('review',compact(' '.join(lines)))
                self.recent = {key:t for key,t in self.recent.items() if at-t<60}
                text=compact(' '.join(lines))
                digits=sorted(set(re.findall(r'\d+', re.sub(r'[IL](?=\d)','1',' '.join(lines).upper()))))
                previous=self.last_review
                duplicate=previous and 0<=at-previous[0]<4 and digits==previous[2] and difflib.SequenceMatcher(None,text,previous[1]).ratio()>=.7
                if review_key not in self.recent and not duplicate:
                    self.emit(dict(type='completion-review',rawText=' | '.join(lines),
                                   confidence=round(float(confidence),3),zone=item.zone,
                                   timestamp=item.captured_utc,sourceTime=getattr(item,'source_time',None),
                                   image=review_image(item.frame,item.header,getattr(item,'review_frame',None))))
                    self.recent[review_key] = at
                    self.last_review = (at,text,digits)
            if valid:
                at = item.source_time if getattr(item,'source_time',None) is not None else item.captured_at
                self.recent = {key:t for key,t in self.recent.items() if at-t<60}
                key = (candidate.get('weapon'),candidate.get('family'),candidate.get('number'),candidate.get('camo'))
                if key not in self.recent:
                    candidate['capturedAt'] = item.captured_utc
                    candidate['sourceTime'] = getattr(item,'source_time',None)
                    if self.emit_unlock(candidate,confidence,item.zone):
                        self.recent[key] = at
                        result['emitted'] = True
                        if attempt:
                            self.recovered += 1
            self.emit({'type':'ocr-debug',**{k:v for k,v in result.items() if k!='candidate'}})
            if valid or review or other_banner or attempt==2 or queue is None:
                return result
            next_item = queue.take_best(item.zone,item.captured_at+.001,first_time+2.5)
            if next_item is None:
                return result
            # Re-read the entire next card. Never graft a previous digit/name onto it.
            item = next_item
        return result
