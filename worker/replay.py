"""Offline, clocked or exhaustive video replay through production OCR/policies."""
import argparse
from datetime import datetime, timezone
import json
import math
import re
import os
from pathlib import Path
import statistics
import sys
import time

import cv2


def load_recognizer():
    os.environ['MW4_REFERENCE_OFFLINE'] = '1'
    import capture_perf, monitor_order_policy, reference_policy, window_capture_policy
    import detector_entry
    import recognition_policy
    return detector_entry.core


def event_key(event):
    from recognition_session import compact
    from camo_catalog import CATALOG
    camo = event.get('camo') or f"{event.get('family','')} {event.get('number','')}"
    weapon = next((name for name in CATALOG if compact(name)==compact(event.get('weapon'))),None)
    numbered = re.fullmatch(r'(SPECIAL|COMPLETIONIST)CAMO([1-3])',compact(camo))
    if weapon and numbered:
        offset = 8 if numbered.group(1)=='SPECIAL' else 11
        camo = CATALOG[weapon][offset+int(numbered.group(2))-1]
    return compact(event.get('weapon')),compact(camo)


def score_events(events, expected):
    if expected is None:
        return dict(scoring='unscored',expected=None,matched=None,missed=None,falseDetections=None)
    remaining = list(range(len(events)))
    matches,misses = [],[]
    for want in expected:
        start = float(want['start']) if 'start' in want else float(want.get('at',0))-1
        end = float(want['end']) if 'end' in want else float(want.get('at',0))+1
        if not math.isfinite(start) or not math.isfinite(end) or not 0 <= start <= end:
            raise ValueError('Expected-event windows require 0 <= start <= end')
        match = next((i for i in remaining if event_key(events[i])==event_key(want)
                      and start<=float(events[i]['sourceTime'])<=end),None)
        if match is None:
            misses.append(want)
        else:
            remaining.remove(match)
            matches.append(dict(expected=want,detected=events[match]))
    return dict(scoring='scored',expected=len(expected),matched=len(matches),missed=misses,
                falseDetections=[events[i] for i in remaining])


class VideoSource:
    def __init__(self, filename, fps, resize=None):
        self.filename,self.fps,self.resize = filename,fps,resize
        self.backend = 'offline-video'
        self.source_time = 0.
    def __enter__(self):
        self.video = cv2.VideoCapture(str(self.filename))
        if not self.video.isOpened():
            raise ValueError('Unable to open recording')
        self.native_fps = self.video.get(cv2.CAP_PROP_FPS) or 30.
        self.total = int(self.video.get(cv2.CAP_PROP_FRAME_COUNT))
        self.duration = self.total/self.native_fps
        self.width,self.height = int(self.video.get(3)),int(self.video.get(4))
        if self.resize:
            self.width,self.height = self.resize
        self.monitors = [dict(left=0,top=0,width=self.width,height=self.height)]*2
        self.started = time.monotonic()
        self.decoded = -1
        self.frame = None
        return self
    def __exit__(self,*_): self.video.release()
    def at(self, second):
        target = int(second*self.native_fps)
        if target >= self.total:
            raise StopIteration
        if target != self.decoded:
            while self.decoded < target:
                if not self.video.grab(): raise StopIteration
                self.decoded += 1
            ok,self.frame = self.video.retrieve()
            if not ok: raise StopIteration
            if self.resize:
                self.frame = cv2.resize(self.frame,self.resize)
        self.source_time = target/self.native_fps
        return self.frame
    def grab(self, region):
        tick = int((time.monotonic()-self.started)*self.fps)
        frame = self.at(tick/self.fps)
        x,y,w,h = [int(region[key]) for key in ('left','top','width','height')]
        return frame[y:y+h,x:x+w,:3]


def run_replay(filename, report_path, expected=None, mode='timed', fps=4., resize=None, zones=None, progress=None, save_snapshots=True):
    from capture_pipeline import CapturePump,PopupFrame
    from diagnostic_store import DiagnosticStore
    from recognition_session import RecognitionSession
    core = load_recognizer()
    cv2.setNumThreads(1)
    events,reads,reviews = [],[],[]
    def on_message(payload):
        if payload.get('type')=='unlock': events.append(payload)
        if payload.get('type')=='completion-review': reviews.append(payload)
        if payload.get('type')=='ocr-debug': reads.append(payload)
    core.emit = on_message
    ocr = core.create_ocr()
    report_path = Path(report_path)
    report_path.parent.mkdir(parents=True,exist_ok=True)
    diagnostics = DiagnosticStore(report_path.parent/'failed-reads' if save_snapshots else None)
    session = RecognitionSession(ocr,core.read_frame_variants,core.parse_candidate,core.prepare_frame,
                                 on_message,core.emit_candidate,core.non_camo_banner,diagnostics)
    specs = core.sanitize_zones(zones) if zones else core.DEFAULT_ZONES
    specs = [z for z in specs if 'weapon' not in z['name']]
    def layout(source):
        monitor = source.monitors[1]
        return [dict(name=z['name'],region=core.scaled_region(monitor,monitor['width'],monitor['height'],1.,1.,z)) for z in specs]
    dropped,captured = 0,0
    started = time.monotonic()
    if mode=='timed':
        def heartbeat(payload):
            if progress:
                progress(dict(message='Replaying at the recording clock',capturedFrames=payload['capturedFrames']))
        with CapturePump(lambda:VideoSource(filename,fps,resize),core.inspect_capture_frame,core.utc_now,
                         fps,heartbeat=heartbeat) as pump:
            selected = layout(pump)
            pump.configure(selected)
            while True:
                pump.check_error()
                item = pump.queue.get(.25)
                if item is not None:
                    session.process(item,pump.queue)
                if pump.finished and not len(pump.queue): break
            captured,dropped = pump.capture_count,pump.queue.dropped
    else:
        with VideoSource(filename,fps,resize) as source:
            selected = layout(source)
            second = 0.
            while second < source.duration:
                try: frame = source.at(second)
                except StopIteration: break
                for zone in selected:
                    region = zone['region']; x,y,w,h = [region[k] for k in ('left','top','width','height')]
                    crop = frame[y:y+h,x:x+w,:3]
                    header,_ = core.inspect_capture_frame(crop,zone['name'])
                    captured += 1
                    if header:
                        item = PopupFrame(zone['name'],crop.copy(),header,time.monotonic(),core.utc_now(),
                                          'offline-video',source.source_time)
                        session.process(item)
                second += 1./fps
                if progress and int(second*fps) % int(fps*5)==0:
                    progress(dict(message='Checking every sampled frame',videoSeconds=round(second,1)))
    durations = [read['ocrDurationMs'] for read in reads]
    delays = [read['captureAgeMs'] for read in reads if read['reason']=='recognized']
    report = dict(reviews=reviews,version=1,mode=mode,scanFps=fps,resize=resize,events=events,reads=reads,
                  elapsedSeconds=round(time.monotonic()-started,2),capturedFrames=captured,droppedFrames=dropped,
                  attempts=session.attempts,uncertainReads=session.failures,retryRecoveries=session.recovered,
                  medianReadMs=round(statistics.median(durations)) if durations else None,
                  maxReadMs=max(durations) if durations else None,
                  maxRecognitionDelayMs=max(delays) if delays else None,
                  **score_events(events,expected))
    report_path.write_text(json.dumps(report,indent=2),encoding='utf-8')
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--replay',required=True)
    parser.add_argument('--report',required=True)
    parser.add_argument('--expected')
    parser.add_argument('--mode',choices=['timed','exhaustive'],default='timed')
    parser.add_argument('--fps',type=float,default=4.)
    parser.add_argument('--resize',help='Example: 1920x1080')
    parser.add_argument('--zones')
    parser.add_argument('--assert-expected',action='store_true')
    parser.add_argument('--no-snapshots',action='store_true')
    args = parser.parse_args(argv)
    expected = json.loads(Path(args.expected).read_text(encoding='utf-8')) if args.expected else None
    resize = tuple(map(int,args.resize.lower().split('x'))) if args.resize else None
    def progress(value): print(json.dumps({'type':'job-progress',**value}),flush=True)
    result = run_replay(args.replay,args.report,expected,args.mode,min(6.,max(1.,args.fps)),resize,
                        json.loads(args.zones) if args.zones else None,progress,not args.no_snapshots)
    print(json.dumps({'type':'job-result','result':result,'reportPath':str(args.report)}),flush=True)
    if args.assert_expected and (result['scoring']!='scored' or result['missed'] or result['falseDetections']):
        raise SystemExit(2)


if __name__=='__main__': main()
