"""Bounded local popup crops and text; no uploads and no full desktop screenshots."""
from datetime import datetime, timezone
import json
import re
from pathlib import Path
import shutil
import time
import uuid

import cv2
from completion_banner import banner_bounds


class DiagnosticStore:
    def __init__(self, root, max_entries=60, max_bytes=50*1024*1024, max_age_days=7):
        self.root = Path(root) if root else None
        self.max_entries = max_entries
        self.max_bytes = max_bytes
        self.max_age = max_age_days*86400
        self.last_error = None
        self._recent = {}
        try:
            self.prune()
        except OSError as exc:
            self.last_error = str(exc)

    def save(self, item, lines, confidence, reason, attempt=0):
        if not self.root:
            return None
        now = time.time()
        identity = (item.zone, reason, tuple(lines))
        if now-self._recent.get(identity, 0) < 2:
            return None
        self._recent = {key:at for key,at in self._recent.items() if now-at < 30}
        self._recent[identity] = now
        directory = None
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')+'-'+uuid.uuid4().hex[:8]
            directory = self.root/stamp
            directory.mkdir()
            bounds = banner_bounds(item.frame.shape, item.header)
            x0,y0,x1,y1 = bounds
            crop = item.frame[y0:y1,x0:x1,:3]
            ok, image = cv2.imencode('.png',crop)
            if not ok:
                raise ValueError('Unable to encode popup crop')
            (directory/'popup.png').write_bytes(image.tobytes())
            record = dict(reason=reason, zone=item.zone, confidence=round(float(confidence),4),
                          lines=list(lines), attempt=attempt, capturedAt=item.captured_utc,
                          sourceTime=getattr(item,'source_time',None), headerScore=item.header[0])
            (directory/'read.json').write_text(json.dumps(record,indent=2),encoding='utf-8')
            self.prune()
            self.last_error = None
            return stamp if directory.exists() else None
        except Exception as exc:
            if directory is not None:
                shutil.rmtree(directory,ignore_errors=True)
            self.last_error = str(exc)
            return None

    def prune(self):
        if not self.root or not self.root.exists():
            return
        entries = []
        for directory in self.root.iterdir():
            if not directory.is_dir() or directory.is_symlink() or not re.fullmatch(r"\d{8}T\d{6}-[0-9a-f]{8}",directory.name):
                continue
            size = sum(p.stat().st_size for p in directory.iterdir() if p.is_file())
            entries.append((directory.stat().st_mtime,size,directory))
        entries.sort()
        total = sum(row[1] for row in entries)
        for index,(mtime,size,directory) in enumerate(entries):
            if time.time()-mtime > self.max_age or len(entries)-index > self.max_entries or total > self.max_bytes:
                shutil.rmtree(directory)
                total -= size
