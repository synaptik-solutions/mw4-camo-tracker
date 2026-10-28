"""Read the visible camo menu into reviewable suggestions; never write progress."""
import argparse
import base64
import json
import re

import cv2
import numpy as np
from camo_catalog import CATALOG
from ocr_runtime import create_ocr
from recognition_session import compact


def status_of(text):
    value = re.sub(r'\s+',' ',str(text).upper()).strip(' :|-')
    if value in ('LOCKED','NOT UNLOCKED','NOT COMPLETED','INCOMPLETE'):
        return 'locked'
    if value in ('UNLOCKED','COMPLETED','COMPLETE'):
        return 'unlocked'
    return None


def parse_menu_result(result, weapon):
    if weapon not in CATALOG:
        raise ValueError('Choose a supported weapon')
    entries = []
    statuses = []
    for item in result or []:
        if len(item)<3 or float(item[2])<.65:
            continue
        points = np.asarray(item[0],dtype=float)
        x0,y0 = points.min(axis=0); x1,y1 = points.max(axis=0)
        text = str(item[1]).strip()
        text = re.sub(r'\bMIL[1ILT][1ILT]ARY\b','MILITARY',text,flags=re.I)
        entry = dict(text=text,confidence=float(item[2]),bounds=[float(x0),float(y0),float(x1),float(y1)])
        if status_of(text): statuses.append(entry)
        entries.append(entry)
    rows = {}
    for entry in entries:
        text = entry['text']
        # Only an explicit status suffix, not requirement prose, can confirm a row.
        suffix = re.search(r'\b(NOT UNLOCKED|NOT COMPLETED|UNLOCKED|COMPLETED|COMPLETE|LOCKED|INCOMPLETE)\s*$',text,re.I)
        direct_status = status_of(suffix.group(1)) if suffix else None
        title = text[:suffix.start()].strip(' :|-') if suffix else text
        for name in CATALOG[weapon]:
            alternatives = {compact(name)}
            if not name.startswith('Military Camo'): alternatives.add(compact(name+' CAMO'))
            if compact(title) in alternatives:
                previous = rows.get(name)
                if previous is None or entry['confidence']>previous['confidence']:
                    rows[name] = dict(name=name,status=direct_status or 'unclear',confidence=entry['confidence'],
                                      evidence=entry['text'],bounds=entry['bounds'])
    # Assign a standalone status to its nearest camo label, never to an entire board.
    for label in statuses:
        lx0,ly0,lx1,ly1 = label['bounds']
        choices = []
        for row in rows.values():
            x0,y0,x1,y1 = row['bounds']
            overlap = max(0,min(x1,lx1)-max(x0,lx0))
            vertical = abs((y0+y1-ly0-ly1)/2)
            if overlap>=.4*max(1,min(x1-x0,lx1-lx0)) and vertical<=max(4*(y1-y0),6*(ly1-ly0)):
                choices.append((vertical+abs((x0+x1-lx0-lx1)/2),row))
        if choices:
            _,row = min(choices,key=lambda pair:pair[0])
            if row['status']=='unclear':
                row['status'] = status_of(label['text'])
                row['evidence'] += ' | '+label['text']
                row['confidence'] = min(row['confidence'],label['confidence'])
    return list(rows.values())


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--scan-menu',action='store_true')
    parser.add_argument('--weapon',required=True,choices=list(CATALOG))
    parser.add_argument('--monitor',type=int,default=1)
    for key in ('left','top','width','height'): parser.add_argument('--'+key,type=int)
    args,_ = parser.parse_known_args(argv)
    import capture_backend
    from windows_dpi import enable_per_monitor_dpi_awareness
    enable_per_monitor_dpi_awareness()
    print(json.dumps({'type':'job-progress','message':'Capturing the visible camo menu'}),flush=True)
    with capture_backend.mss() as capture:
        if args.monitor>0 and args.monitor<len(capture.monitors):
            region = capture.monitors[args.monitor]
        elif None not in (args.left,args.top,args.width,args.height):
            region = {key:getattr(args,key) for key in ('left','top','width','height')}
        else:
            region = capture.monitors[1]
        image = np.asarray(capture.grab(region),np.uint8)[:,:,:3].copy()
    if float(image.std())<1:
        raise RuntimeError('Menu capture was blank. Show the game camo menu on the selected source and try again.')
    scale = min(1.,1920./max(image.shape[1],1))
    image = cv2.resize(image,None,fx=scale,fy=scale) if scale<1 else image
    print(json.dumps({'type':'job-progress','message':'Reading camo labels and explicit completion text'}),flush=True)
    result,_ = create_ocr()(image)
    rows = parse_menu_result(result,args.weapon)
    preview = cv2.resize(image,None,fx=min(1.,960./image.shape[1]),fy=min(1.,960./image.shape[1]))
    ok,encoded = cv2.imencode('.jpg',preview,[cv2.IMWRITE_JPEG_QUALITY,75])
    data = dict(weapon=args.weapon,rows=rows,weaponTextSeen=any(compact(row[1])==compact(args.weapon) for row in result or []),
                preview='data:image/jpeg;base64,'+base64.b64encode(encoded).decode() if ok else None,
                message='Review the screenshot and select earned camos. Unclear or locked entries are not selected automatically.')
    print(json.dumps({'type':'job-result','result':data}),flush=True)
