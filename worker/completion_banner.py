"""Separate visual trigger for the cyan CHALLENGE COMPLETED center banner.

The reference contains only header lettering from supplied gameplay. OCR must confirm
its text before a review item is created; this trigger never assigns a camo.
"""
import base64
import zlib
import re
import cv2
import numpy as np
from popup_signature import _high_pass, popup_card_bounds

_REFERENCE = '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'
_template = np.frombuffer(zlib.decompress(base64.b64decode(_REFERENCE)),np.uint8).reshape(15,220)
_templates = [_high_pass(cv2.resize(_template,None,fx=s,fy=s)) for s in (.65,.8,1.,1.2,1.5,1.8,2.,2.4,2.8,3.,3.4)]


def find_completion_header(bgr):
    if bgr is None or bgr.size==0:
        return None
    h,w=bgr.shape[:2]
    scale=min(1.,588./w)
    sample=cv2.resize(bgr,None,fx=scale,fy=scale,interpolation=cv2.INTER_AREA) if scale<1 else bgr
    hsv=cv2.cvtColor(sample,cv2.COLOR_BGR2HSV)
    cyan=cv2.inRange(hsv,np.array([80,35,90],np.uint8),np.array([110,255,255],np.uint8))
    # The sky can connect to cyan lettering; do not require an isolated contour.
    # A row with enough cyan pixels is only a cheap gate, never recognition proof.
    if np.count_nonzero(cyan)<100 or np.max(np.count_nonzero(cyan,axis=1))<60:
        return None
    regions=[(0,0,sample.shape[1],sample.shape[0])]
    best=.68;bounds=None
    for x0,y0,x1,y1 in regions:
        gray=_high_pass(cv2.cvtColor(sample[y0:y1,x0:x1],cv2.COLOR_BGR2GRAY))
        energy_sum=cv2.integral(gray*gray)
        local_cyan=cyan[y0:y1,x0:x1]/255.
        color_sum=cv2.integral(local_cyan)
        for template in _templates:
            th,tw=template.shape
            if th>gray.shape[0] or tw>gray.shape[1]:continue
            result=cv2.matchTemplate(gray,template,cv2.TM_CCOEFF_NORMED)
            energy=energy_sum[th:,tw:]-energy_sum[:-th,tw:]-energy_sum[th:,:-tw]+energy_sum[:-th,:-tw]
            color=color_sum[th:,tw:]-color_sum[:-th,tw:]-color_sum[th:,:-tw]+color_sum[:-th,:-tw]
            result[(energy<9.*th*tw)|(color<.1*th*tw)]=0
            _,score,_,(x,y)=cv2.minMaxLoc(result)
            if np.isfinite(score) and score>=best:
                best=float(score);bounds=tuple(int(round(v/scale)) for v in (x+x0,y+y0,tw,th))
    return (best,bounds,'challenge') if bounds else None


def is_completion_text(lines):
    text=''.join(c for c in ' '.join(lines).upper() if c.isalnum())
    return 'CHALLENGECOMPLETED' in text


def banner_bounds(shape,header):
    if len(header)<3 or header[2]!='challenge':
        return popup_card_bounds(shape,header[1])
    height,width=shape[:2];x,y,w,h=header[1]
    return max(0,x-int(.15*w)),max(0,y-5*h),min(width,x+int(1.15*w)),min(height,y+4*h)


def review_image(frame,header,context=None):
    # Review uses the wider same-frame capture, never the tight OCR/diagnostic crop.
    crop=(context if context is not None else frame)[:,:,:3]
    if crop.size==0:return None
    scale=min(1.,1600./max(crop.shape[:2]))
    if scale<1:
        crop=cv2.resize(crop,None,fx=scale,fy=scale,interpolation=cv2.INTER_AREA)
    for quality in (88,76,64):
        ok,data=cv2.imencode('.jpg',crop,[cv2.IMWRITE_JPEG_QUALITY,quality])
        if not ok:return None
        if len(data)<=1000000:
            return 'data:image/jpeg;base64,'+base64.b64encode(data).decode()
    # Bound storage even for unusually noisy high-resolution source frames.
    crop=cv2.resize(crop,None,fx=.7,fy=.7,interpolation=cv2.INTER_AREA)
    ok,data=cv2.imencode('.jpg',crop,[cv2.IMWRITE_JPEG_QUALITY,76])
    return 'data:image/jpeg;base64,'+base64.b64encode(data).decode() if ok and len(data)<=1000000 else None
