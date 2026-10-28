"""Distinguish unchanged imagery from capture stalls and report measured throughput."""
import hashlib
import time
import cv2


class CaptureHealth:
    def __init__(self, target_fps, clock=time.monotonic):
        self.clock = clock
        self.target_fps = target_fps
        self.started = clock()
        self.last_capture = None
        self.last_changed = {}
        self.signatures = {}
        self.count = 0
        self.window_at = self.started
        self.window_count = 0
        self.fps = 0.
        self.blank_since = {}

    def observe(self, frame, zone):
        now = self.clock()
        small = cv2.resize(frame[:,:,:3],(32,18),interpolation=cv2.INTER_AREA)
        signature = hashlib.blake2b(small.tobytes(),digest_size=8).digest()
        if signature != self.signatures.get(zone):
            self.last_changed[zone] = now
            self.signatures[zone] = signature
        if float(small.std()) < 1.:
            self.blank_since.setdefault(zone,now)
        else:
            self.blank_since.pop(zone,None)
        self.count += 1
        self.last_capture = now
        return dict(unchangedForSec=round(now-self.last_changed.get(zone,now),1),
                    blankForSec=round(now-self.blank_since.get(zone,now),1))

    def status(self, zone_count, pending=0, dropped=0):
        now = self.clock()
        elapsed = now-self.window_at
        if elapsed >= 2:
            self.fps = (self.count-self.window_count)/max(1,zone_count)/elapsed
            self.window_at, self.window_count = now,self.count
        age = now-self.last_capture if self.last_capture is not None else now-self.started
        issues = []
        if age > 3:
            issues.append('Capture has not delivered a frame for more than 3 seconds.')
        if now-self.started > 4 and self.fps < self.target_fps*.5:
            issues.append('Capture is running below half the selected scan rate.')
        if pending >= 3:
            issues.append('Text recognition is falling behind capture.')
        return dict(captureFps=round(self.fps,2),lastFrameAgeSec=round(age,1),
                    capturedFrames=self.count,pendingFrames=pending,droppedFrames=dropped,issues=issues)
