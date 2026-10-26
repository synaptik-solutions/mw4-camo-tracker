import argparse
import json
import re
import sys
import time
from datetime import datetime, timezone

import cv2
import mss
import numpy as np
from rapidocr_onnxruntime import RapidOCR

UNLOCK_RE = re.compile(r"\b(MILITARY|SPECIAL|COMPLETIONIST|PRESTIGE)\s+CAMO\s+(\d+)\b", re.I)
CAMO_RE = re.compile(r"\b([A-Z][A-Z0-9' .\-]{2,30})\s+CAMO\b", re.I)
DEFAULT_ZONES = [
    {"name": "upper-right", "x": 0.58, "y": 0.05, "width": 0.40, "height": 0.40},
    {"name": "center", "x": 0.27, "y": 0.25, "width": 0.46, "height": 0.50},
]

def emit(payload): print(json.dumps(payload, ensure_ascii=True), flush=True)
def utc_now(): return datetime.now(timezone.utc).isoformat()

def normalize_ocr_line(text):
    text = re.sub(r"\s+", " ", str(text or "").strip())
    text = re.sub(r"\bCAM0\b", "CAMO", text, flags=re.I)
    text = re.sub(r"\bUNL0CKED\b", "UNLOCKED", text, flags=re.I)
    text = re.sub(r"\bUNLOCKE[D0]\b", "UNLOCKED", text, flags=re.I)
    return text

def parse_text(lines):
    clean=[normalize_ocr_line(x) for x in lines if x and str(x).strip()];clean=[x for x in clean if x]
    if not clean:return None
    joined=" | ".join(clean);upper=[x.upper() for x in clean]
    unlock_idx=next((i for i,x in enumerate(upper) if "UNLOCK" in x or "NLOCK" in x),None)
    if unlock_idx is None:return None
    weapon=None
    for candidate in upper[unlock_idx+1:unlock_idx+6]:
        if "CAMO" not in candidate and len(candidate)>=2: weapon=candidate;break
    for line in upper:
        m=UNLOCK_RE.search(line)
        if m:return {"type":"unlock","weapon":weapon or "UNKNOWN","family":f"{m.group(1).upper()} CAMO","number":int(m.group(2)),"camo":None,"rawText":joined,"timestamp":utc_now()}
    for line in upper:
        m=CAMO_RE.search(line)
        if m and not any(x in line for x in ("MILITARY","SPECIAL","COMPLETIONIST","PRESTIGE")):
            return {"type":"unlock","weapon":weapon or "UNKNOWN","family":None,"number":None,"camo":m.group(1).strip(),"rawText":joined,"timestamp":utc_now()}
    return None

def fingerprint(gray): return cv2.resize(gray,(48,27),interpolation=cv2.INTER_AREA).astype(np.int16)
def text_activity(gray):
    small=cv2.resize(gray,(140,79),interpolation=cv2.INTER_AREA);_,bright=cv2.threshold(small,190,255,cv2.THRESH_BINARY)
    return float(np.count_nonzero(bright))/float(bright.size)
def ocr_lines(ocr,image):
    result,_=ocr(image)
    if not result:return [],0.0
    good=[item for item in result if len(item)>=3 and float(item[2])>=0.26]
    return [item[1] for item in good],float(np.mean([item[2] for item in good])) if good else 0.0

def sanitize_zones(raw):
    zones=[]
    if not isinstance(raw,list):return DEFAULT_ZONES
    for i,item in enumerate(raw[:4]):
        if not isinstance(item,dict):continue
        try:
            x=min(max(float(item.get("x",0)),0.0),0.95);y=min(max(float(item.get("y",0)),0.0),0.95)
            width=min(max(float(item.get("width",0.1)),0.03),1.0-x);height=min(max(float(item.get("height",0.1)),0.03),1.0-y)
        except (TypeError,ValueError):continue
        zones.append({"name":str(item.get("name") or f"zone-{i+1}").lower(),"x":x,"y":y,"width":width,"height":height})
    return zones or DEFAULT_ZONES

def scaled_region(monitor,reference_width,reference_height,scale_x,scale_y,spec):
    region={"left":monitor["left"]+int(reference_width*spec["x"]*scale_x),"top":monitor["top"]+int(reference_height*spec["y"]*scale_y),"width":max(1,int(reference_width*spec["width"]*scale_x)),"height":max(1,int(reference_height*spec["height"]*scale_y))}
    region["width"]=min(region["width"],monitor["left"]+monitor["width"]-region["left"]);region["height"]=min(region["height"],monitor["top"]+monitor["height"]-region["top"])
    return region

def main():
    p=argparse.ArgumentParser();p.add_argument("--monitor",type=int,default=0);p.add_argument("--left",type=int);p.add_argument("--top",type=int);p.add_argument("--width",type=int);p.add_argument("--height",type=int);p.add_argument("--fps",type=float,default=4.0);p.add_argument("--zones",type=str,default="")
    args=p.parse_args();fps=min(max(args.fps,1.0),4.0);interval=1.0/fps
    try:cv2.setNumThreads(1)
    except Exception:pass
    ocr=RapidOCR(det_use_dilation=True);last_event_key=None;last_event_time=0.0;last_health=0.0
    try:zone_specs=sanitize_zones(json.loads(args.zones)) if args.zones else DEFAULT_ZONES
    except Exception:zone_specs=DEFAULT_ZONES
    with mss.mss() as sct:
        if 1<=args.monitor<len(sct.monitors):monitor=dict(sct.monitors[args.monitor]);monitor_source=f"mss-{args.monitor}"
        elif None not in (args.left,args.top,args.width,args.height):monitor={"left":args.left,"top":args.top,"width":args.width,"height":args.height};monitor_source="electron-fallback"
        else:monitor=dict(sct.monitors[1]);monitor_source="mss-1-fallback"
        reference_width=int(args.width or monitor["width"]);reference_height=int(args.height or monitor["height"]);scale_x=float(monitor["width"])/max(reference_width,1);scale_y=float(monitor["height"])/max(reference_height,1)
        zones=[]
        for spec in zone_specs:
            zones.append({"name":spec["name"],"percent":{k:spec[k] for k in ("x","y","width","height")},"region":scaled_region(monitor,reference_width,reference_height,scale_x,scale_y,spec),"last_fp":None,"baseline_activity":None,"last_ocr":0.0,"last_debug":0.0,"last_mean":0.0,"last_stddev":0.0,"last_activity":0.0,"last_ocr_text":"","last_ocr_confidence":0.0})
        emit({"type":"status","message":"detector-ready","monitor":args.monitor,"monitorSource":monitor_source,"monitorBounds":monitor,"settingsResolution":{"width":reference_width,"height":reference_height},"captureScale":{"x":round(scale_x,4),"y":round(scale_y,4)},"zones":[{"name":z["name"],"percent":z["percent"],"region":z["region"]} for z in zones],"fps":fps})
        while True:
            started=time.perf_counter();now=time.monotonic()
            for zone in zones:
                frame=np.asarray(sct.grab(zone["region"]),dtype=np.uint8);bgr=frame[:,:,:3];gray=cv2.cvtColor(bgr,cv2.COLOR_BGR2GRAY);fp=fingerprint(gray);activity=text_activity(gray)
                zone["last_mean"]=float(np.mean(gray));zone["last_stddev"]=float(np.std(gray));zone["last_activity"]=activity
                zone["baseline_activity"]=activity if zone["baseline_activity"] is None else zone["baseline_activity"]*0.99+activity*0.01
                mean_delta=999.0 if zone["last_fp"] is None else float(np.mean(np.abs(fp-zone["last_fp"])));zone["last_fp"]=fp
                activity_spike=activity>(zone["baseline_activity"]+0.0015);visual_change=mean_delta>=1.5;strong_change=mean_delta>=2.9
                if not ((now-zone["last_ocr"]>=6.0) or (now-zone["last_ocr"]>=0.60 and (visual_change or activity_spike))):continue
                zone["last_ocr"]=now;lines,confidence=ocr_lines(ocr,bgr);event=parse_text(lines)
                if not event and (strong_change or activity_spike):
                    h,w=bgr.shape[:2];focus=bgr[int(h*0.08):int(h*0.92),int(w*0.08):int(w*0.92)];focus_gray=cv2.cvtColor(focus,cv2.COLOR_BGR2GRAY);focus_gray=cv2.createCLAHE(clipLimit=2.0,tileGridSize=(8,8)).apply(focus_gray);focus_up=cv2.resize(focus_gray,None,fx=1.20,fy=1.20,interpolation=cv2.INTER_CUBIC);focus_lines,focus_conf=ocr_lines(ocr,focus_up)
                    if focus_lines:
                        merged=list(lines)
                        for value in focus_lines:
                            if value not in merged:merged.append(value)
                        lines=merged;confidence=max(confidence,focus_conf);event=parse_text(lines)
                debug_text=" | ".join(normalize_ocr_line(x) for x in lines if normalize_ocr_line(x));zone["last_ocr_text"]=debug_text;zone["last_ocr_confidence"]=confidence
                if now-zone["last_debug"]>=2.0:emit({"type":"ocr-debug","zone":zone["name"],"rawText":debug_text,"confidence":round(confidence,3),"delta":round(mean_delta,3),"activity":round(activity,5),"timestamp":utc_now()});zone["last_debug"]=now
                if event:
                    event["confidence"]=round(confidence,3);event["zone"]=zone["name"];event_key=(event.get("weapon"),event.get("family"),event.get("number"),event.get("camo"))
                    if event_key!=last_event_key or now-last_event_time>8.0:emit(event);last_event_key=event_key;last_event_time=now
            if now-last_health>=5.0:
                emit({"type":"capture-health","monitor":args.monitor,"settingsResolution":{"width":reference_width,"height":reference_height},"zones":[{"name":z["name"],"region":z["region"],"mean":round(z["last_mean"],2),"stddev":round(z["last_stddev"],2),"activity":round(z["last_activity"],5),"ocrText":z["last_ocr_text"],"ocrConfidence":round(z["last_ocr_confidence"],3)} for z in zones],"timestamp":utc_now()});last_health=now
            elapsed=time.perf_counter()-started
            if elapsed<interval:time.sleep(interval-elapsed)

if __name__=="__main__":
    try:main()
    except KeyboardInterrupt:pass
    except Exception as exc:emit({"type":"error","message":str(exc)});sys.exit(1)
