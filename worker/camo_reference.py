"""Cached camo-thumbnail reference matching for MW4 unlock popups.

The reference library is built from public camo thumbnails on mw4.gg and cached under
LOCALAPPDATA. Detection continues to work if the site/network is unavailable; image matching
simply stays disabled until references are available.
"""

from __future__ import annotations

import html as html_lib
import json
import os
import re
import threading
import time
from pathlib import Path
from urllib.parse import unquote, urljoin, urlparse, parse_qs
from urllib.request import Request, urlopen

import cv2
import numpy as np

INDEX_URL = "https://mw4.gg/camos/"
UA = "MW4-Camo-Tracker/0.3 (+https://github.com/synaptik-solutions/mw4-camo-tracker)"
ALT_RE = re.compile(r"(?P<name>[^\"<>]{2,80}?)\s+camo\s+icon\s+[—-]\s+MW4", re.I)
IMG_RE = re.compile(r"<img\b[^>]*>", re.I)
ATTR_RE = re.compile(r"([:\w-]+)\s*=\s*([\"'])(.*?)\2", re.I | re.S)


def _cache_dir() -> Path:
    root = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA") or str(Path.home())
    path = Path(root) / "MW4-Camo-Tracker" / "camo-reference"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _safe_name(value: str) -> str:
    clean = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return clean[:80] or "camo"


def _fetch_bytes(url: str, timeout: float = 7.0) -> bytes:
    req = Request(url, headers={"User-Agent": UA, "Accept": "image/avif,image/webp,image/*,*/*;q=0.8"})
    with urlopen(req, timeout=timeout) as response:
        return response.read()


def _fetch_text(url: str, timeout: float = 8.0) -> str:
    req = Request(url, headers={"User-Agent": UA, "Accept": "text/html,application/xhtml+xml"})
    with urlopen(req, timeout=timeout) as response:
        return response.read().decode("utf-8", "replace")


def _unwrap_next_image(url: str) -> str:
    """Keep Next.js optimizer URLs usable, while decoding their embedded URL when obvious."""
    parsed = urlparse(url)
    if parsed.path.endswith("/_next/image") or parsed.path == "/_next/image":
        query = parse_qs(parsed.query)
        embedded = query.get("url", [None])[0]
        if embedded:
            return urljoin(INDEX_URL, unquote(embedded))
    return url


def _extract_index_images(page_html: str):
    found = []
    seen = set()
    for tag in IMG_RE.findall(page_html):
        attrs = {m.group(1).lower(): html_lib.unescape(m.group(3)) for m in ATTR_RE.finditer(tag)}
        alt = attrs.get("alt", "")
        match = ALT_RE.search(alt)
        if not match:
            continue
        name = html_lib.unescape(match.group("name")).strip()
        src = attrs.get("src") or attrs.get("data-src") or attrs.get("data-lazy-src")
        if not src:
            srcset = attrs.get("srcset") or attrs.get("data-srcset") or ""
            if srcset:
                src = srcset.split(",")[0].strip().split(" ")[0]
        if not src:
            continue
        url = _unwrap_next_image(urljoin(INDEX_URL, html_lib.unescape(src)))
        key = (name.lower(), url)
        if key in seen:
            continue
        seen.add(key)
        found.append((name, url))
    return found


def _decode_image(data: bytes):
    arr = np.frombuffer(data, dtype=np.uint8)
    image = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if image is None or image.size == 0:
        return None
    return image


def _center_square(image):
    h, w = image.shape[:2]
    side = min(h, w)
    if side <= 2:
        return image
    x = max(0, (w - side) // 2)
    y = max(0, (h - side) // 2)
    return image[y:y + side, x:x + side]


def _descriptor(image):
    if image is None or image.size == 0:
        return None
    image = _center_square(image)
    image = cv2.resize(image, (96, 96), interpolation=cv2.INTER_AREA)

    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    hist = cv2.calcHist([hsv], [0, 1], None, [16, 8], [0, 180, 0, 256]).astype(np.float32).reshape(-1)
    norm = float(np.linalg.norm(hist))
    if norm > 0:
        hist /= norm

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    small = cv2.resize(gray, (17, 16), interpolation=cv2.INTER_AREA)
    dhash = (small[:, 1:] > small[:, :-1]).astype(np.uint8).reshape(-1)

    edges = cv2.Canny(gray, 60, 140)
    edge_small = cv2.resize(edges, (16, 16), interpolation=cv2.INTER_AREA).astype(np.float32).reshape(-1) / 255.0
    return hist, dhash, edge_small


def _thumbnail_candidates(bgr):
    """Find likely square camo thumbnails inside the unlock card.

    This uses the same green/yellow header signature as detector.py, then searches the card
    immediately left/below the header for a square textured block. A broad fallback crop is
    included because UI scale/HDR can weaken the square border.
    """
    h, w = bgr.shape[:2]
    if h < 30 or w < 60:
        return []

    scale = min(1.0, 520.0 / float(w))
    sample = cv2.resize(bgr, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA) if scale < 1 else bgr
    sh, sw = sample.shape[:2]
    hsv = cv2.cvtColor(sample, cv2.COLOR_BGR2HSV)
    green = cv2.inRange(hsv, np.array([25, 28, 110], np.uint8), np.array([95, 255, 255], np.uint8))
    green = cv2.morphologyEx(green, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (5, 3)))
    contours, _ = cv2.findContours(green, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    candidates = []
    for contour in contours:
        x, y, bw, bh = cv2.boundingRect(contour)
        if bw < max(18, int(sw * 0.035)) or bh < 3:
            continue
        ratio = bw / float(max(1, bh))
        if not (1.6 <= ratio <= 14.0):
            continue

        card_x0 = max(0, x - int(bw * 3.4))
        card_y0 = max(0, y - int(bh * 0.2))
        card_x1 = min(sw, x + int(bw * 0.7))
        card_y1 = min(sh, y + int(bh * 7.0))
        if card_x1 - card_x0 < 30 or card_y1 - card_y0 < 20:
            continue

        card = sample[card_y0:card_y1, card_x0:card_x1]
        ch, cw = card.shape[:2]
        gray = cv2.cvtColor(card, cv2.COLOR_BGR2GRAY)
        edges = cv2.Canny(gray, 55, 145)
        econtours, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
        scored = []
        for ec in econtours:
            ex, ey, ew, eh = cv2.boundingRect(ec)
            if min(ew, eh) < max(12, int(min(cw, ch) * 0.12)):
                continue
            sq = ew / float(max(1, eh))
            if not (0.65 <= sq <= 1.45):
                continue
            # Camo tile is normally on the left half of the unlock card.
            if ex > cw * 0.58:
                continue
            area = ew * eh
            scored.append((area, ex, ey, ew, eh))
        for _, ex, ey, ew, eh in sorted(scored, reverse=True)[:3]:
            pad = max(1, int(min(ew, eh) * 0.05))
            x0 = max(0, ex + pad)
            y0 = max(0, ey + pad)
            x1 = min(cw, ex + ew - pad)
            y1 = min(ch, ey + eh - pad)
            crop = card[y0:y1, x0:x1]
            if crop.size:
                candidates.append(crop)

        # Fallback based on the screenshot geometry: thumbnail is the left block under header.
        fw = min(int(cw * 0.36), int(ch * 0.72))
        fh = fw
        fx = max(0, int(cw * 0.02))
        fy = max(0, int(ch * 0.20))
        if fw >= 14 and fy + fh <= ch:
            candidates.append(card[fy:fy + fh, fx:fx + fw])

    return candidates[:8]


class CamoReferenceMatcher:
    def __init__(self):
        self.cache = _cache_dir()
        self.manifest_path = self.cache / "manifest.json"
        self._lock = threading.Lock()
        self._ready = False
        self._building = False
        self._names = []
        self._hist = None
        self._dhash = None
        self._edges = None
        self._last_error = None
        self._load_cached()

    @property
    def ready(self):
        with self._lock:
            return self._ready

    @property
    def count(self):
        with self._lock:
            return len(self._names)

    @property
    def last_error(self):
        with self._lock:
            return self._last_error

    def start_async(self):
        with self._lock:
            if self._building:
                return
            self._building = True
        thread = threading.Thread(target=self._refresh_worker, name="mw4-camo-reference", daemon=True)
        thread.start()

    def _set_descriptors(self, rows):
        names, hists, hashes, edges = [], [], [], []
        for name, image in rows:
            desc = _descriptor(image)
            if desc is None:
                continue
            hist, dhash, edge = desc
            names.append(name)
            hists.append(hist)
            hashes.append(dhash)
            edges.append(edge)
        with self._lock:
            self._names = names
            self._hist = np.stack(hists).astype(np.float32) if hists else None
            self._dhash = np.stack(hashes).astype(np.uint8) if hashes else None
            self._edges = np.stack(edges).astype(np.float32) if edges else None
            self._ready = bool(names)

    def _load_cached(self):
        try:
            manifest = json.loads(self.manifest_path.read_text("utf-8")) if self.manifest_path.exists() else {}
            rows = []
            for item in manifest.get("items", []):
                path = self.cache / item.get("file", "")
                if not path.exists():
                    continue
                image = cv2.imread(str(path), cv2.IMREAD_COLOR)
                if image is not None:
                    rows.append((item.get("name", path.stem), image))
            self._set_descriptors(rows)
        except Exception as exc:
            with self._lock:
                self._last_error = f"cache-load: {exc}"

    def _refresh_worker(self):
        try:
            page = _fetch_text(INDEX_URL)
            refs = _extract_index_images(page)
            if not refs:
                raise RuntimeError("No camo icon images found on MW4.GG index")

            items = []
            rows = []
            for idx, (name, url) in enumerate(refs[:180]):
                filename = f"{idx:03d}-{_safe_name(name)}.jpg"
                path = self.cache / filename
                image = None
                if path.exists():
                    image = cv2.imread(str(path), cv2.IMREAD_COLOR)
                if image is None:
                    try:
                        data = _fetch_bytes(url, timeout=5.5)
                        image = _decode_image(data)
                        if image is None:
                            continue
                        cv2.imwrite(str(path), image, [int(cv2.IMWRITE_JPEG_QUALITY), 92])
                    except Exception:
                        continue
                items.append({"name": name, "url": url, "file": filename})
                rows.append((name, image))
                # Be polite to the source and keep this background work low priority.
                if idx % 12 == 11:
                    time.sleep(0.08)

            if rows:
                self.manifest_path.write_text(json.dumps({"source": INDEX_URL, "updated": time.time(), "items": items}, indent=2), "utf-8")
                self._set_descriptors(rows)
            elif not self.ready:
                raise RuntimeError("Camo reference images could not be downloaded")
        except Exception as exc:
            with self._lock:
                self._last_error = f"refresh: {exc}"
        finally:
            with self._lock:
                self._building = False

    def match_frame(self, bgr):
        with self._lock:
            if not self._ready or self._hist is None:
                return None
            names = list(self._names)
            hists = self._hist
            hashes = self._dhash
            edges = self._edges

        best = None
        for crop in _thumbnail_candidates(bgr):
            desc = _descriptor(crop)
            if desc is None:
                continue
            hist, dhash, edge = desc
            # Histograms are L2-normalized, so dot product is cosine similarity.
            hist_sim = np.clip(hists @ hist, 0.0, 1.0)
            hash_sim = 1.0 - np.mean(hashes != dhash[None, :], axis=1)
            edge_dist = np.mean(np.abs(edges - edge[None, :]), axis=1)
            edge_sim = np.clip(1.0 - edge_dist, 0.0, 1.0)
            scores = 0.56 * hist_sim + 0.29 * hash_sim + 0.15 * edge_sim
            idx = int(np.argmax(scores))
            score = float(scores[idx])
            if best is None or score > best["score"]:
                best = {"name": names[idx], "score": score}
        if best and best["score"] >= 0.62:
            return best
        return None
