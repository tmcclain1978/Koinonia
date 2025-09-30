"""
PocketOption chart digitizer for a single frame or a video.
- Tuned for the dark theme in the provided screenshot (green/red bodies, gray grid).
- Extracts OHLC per bar by detecting candle bodies/wicks and mapping pixel Y -> price via OCR of Y-axis labels.

Prereqs:
  pip install opencv-python-headless numpy pytesseract
  + Install Tesseract binary (and ensure it's on PATH) for best OCR.

Usage (single PNG frame):
  from utils.video_to_candles import extract_ohlc_from_image
  bars = extract_ohlc_from_image("/mnt/data/Screenshot 2025-09-16 020943.png")

Usage (video):
  from utils.video_to_candles import extract_ohlc_from_video
  bars = extract_ohlc_from_video("/path/to/video.mp4", fps_sample=3.0)

Each bar is a dict: {"x": center_x_px, "open":..., "high":..., "low":..., "close":...}
You can post-process to assign timestamps based on bar order and chart timeframe (M1).
"""
from __future__ import annotations
import cv2
import numpy as np
import pytesseract
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

# -----------------------------
# Configuration (tuned defaults for your screenshot)
# -----------------------------

# HSV ranges for green/red bodies on PocketOption dark theme
HSV_GREEN = (np.array([35, 40, 40]),  np.array([85, 255, 255]))
HSV_RED_1 = (np.array([0, 50, 50]),   np.array([10, 255, 255]))
HSV_RED_2 = (np.array([170, 50, 50]), np.array([180, 255, 255]))

# Morphology kernel for noise cleanup
KERNEL = np.ones((3, 3), np.uint8)

@dataclass
class AxesMap:
    a: float  # price = a*y + b
    b: float
    bar_px: int      # approximate candle spacing in pixels
    rightmost_x: int # x of the latest candle center

# -----------------------------
# OCR helpers
# -----------------------------

def _ocr_text(img_gray: np.ndarray) -> List[Tuple[str, Tuple[int,int,int,int]]]:
    cfg = "--psm 6"
    data = pytesseract.image_to_data(img_gray, output_type=pytesseract.Output.DICT, config=cfg)
    out = []
    for i in range(len(data['text'])):
        txt = (data['text'][i] or '').strip()
        if not txt:
            continue
        x,y,w,h = data['left'][i], data['top'][i], data['width'][i], data['height'][i]
        out.append((txt, (x,y,w,h)))
    return out

# -----------------------------
# Core steps
# -----------------------------

def _detect_chart_roi(frame: np.ndarray) -> Tuple[int,int,int,int]:
    """Return (x,y,w,h) of chart area. For now, use a conservative crop to remove UI sidebars.
    Tuned to your screenshot layout.
    """
    H, W = frame.shape[:2]
    # Left panel is small, right trade panel is wide; crop ~12% left, ~20% right.
    x0 = int(0.12 * W)
    x1 = int(0.80 * W)
    y0 = int(0.06 * H)  # drop the top toolbar
    y1 = int(0.96 * H)  # keep bottom timestamps
    x = max(0, x0); y = max(0, y0)
    w = max(10, x1 - x)
    h = max(10, y1 - y)
    return x, y, w, h


def _calibrate_axes(chart_bgr: np.ndarray) -> Optional[AxesMap]:
    gray = cv2.cvtColor(chart_bgr, cv2.COLOR_BGR2GRAY)
    H, W = gray.shape[:2]

    # Y-axis labels are near the right edge on PocketOption (because of the crosshair label).
    # But the fixed scale labels are along the right border inside the chart. Crop a right strip.
    ystrip = gray[:, int(0.90 * W):]
    texts = _ocr_text(ystrip)

    ys, prices = [], []
    for txt, (x,y,w,h) in texts:
        # Filter numbers like 2.00805 or 1.99500
        try:
            val = float(txt.replace(',', ''))
        except Exception:
            continue
        cy = y + h//2
        ys.append(cy)
        prices.append(val)

    if len(ys) < 2:
        # Fallback: try left strip too
        lstrip = gray[:, :int(0.15 * W)]
        texts2 = _ocr_text(lstrip)
        for txt, (x,y,w,h) in texts2:
            try:
                val = float(txt.replace(',', ''))
            except Exception:
                continue
            cy = y + h//2
            ys.append(cy)
            prices.append(val)

    if len(ys) < 2:
        return None

    A = np.vstack([np.array(ys, dtype=float), np.ones(len(ys))]).T
    yvec = np.array(prices, dtype=float)
    a, b = np.linalg.lstsq(A, yvec, rcond=None)[0]

    # Estimate bar spacing from vertical edges in middle band
    mid = gray[int(0.25*H):int(0.9*H), int(0.05*W):int(0.95*W)]
    edges = cv2.Canny(mid, 60, 160)
    lines = cv2.HoughLinesP(edges, 1, np.pi/180, threshold=80, minLineLength=8, maxLineGap=3)
    xs = []
    if lines is not None:
        for (x1,y1,x2,y2) in lines[:,0]:
            if abs(x1 - x2) <= 1 and abs(y1 - y2) > 4:
                xs.append(x1)
    if len(xs) >= 8:
        xs = np.sort(xs)
        diffs = np.diff(xs)
        hist = np.histogram(diffs, bins=np.arange(1,51))[0]
        bar_px = int(np.argmax(hist) + 1)
    else:
        bar_px = 8  # default

    rightmost_x = int(0.95 * W)
    return AxesMap(a=a, b=b, bar_px=bar_px, rightmost_x=rightmost_x)


def _mask_bodies(hsv: np.ndarray) -> np.ndarray:
    gmask = cv2.inRange(hsv, HSV_GREEN[0], HSV_GREEN[1])
    rmask = cv2.inRange(hsv, HSV_RED_1[0], HSV_RED_1[1]) | cv2.inRange(hsv, HSV_RED_2[0], HSV_RED_2[1])
    mask = cv2.morphologyEx(gmask | rmask, cv2.MORPH_OPEN, KERNEL)
    return mask


def _extract_bars_from_chart(chart_bgr: np.ndarray, axes: AxesMap) -> Dict[int, Dict[str, float]]:
    H, W = chart_bgr.shape[:2]
    hsv = cv2.cvtColor(chart_bgr, cv2.COLOR_BGR2HSV)
    mask = _mask_bodies(hsv)

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    obs: Dict[int, Dict[str, float]] = {}

    for cnt in contours:
        x,y,w,h = cv2.boundingRect(cnt)
        if w < max(2, axes.bar_px//3) or h < 5:
            continue
        cx = x + w//2
        bar_idx = max(0, int(round((axes.rightmost_x - cx) / max(1, axes.bar_px))))  # 0=latest

        # Map top/bottom of body to prices
        top = y
        bot = y + h
        p_top = axes.a * float(top) + axes.b
        p_bot = axes.a * float(bot) + axes.b

        # Determine color via mean hue in ROI
        roi_h = hsv[y:y+h, x:x+w, 0]
        mean_hue = int(np.mean(roi_h)) if roi_h.size else 0
        is_green = 35 <= mean_hue <= 85

        o = min(p_top, p_bot) if is_green else max(p_top, p_bot)
        c = max(p_top, p_bot) if is_green else min(p_top, p_bot)

        # Wick estimation: look along a narrow column at cx
        col = chart_bgr[:, max(0,cx-1):min(W,cx+2)]
        col_gray = cv2.cvtColor(col, cv2.COLOR_BGR2GRAY)
        # Non-background pixels (threshold)
        ys = np.where(col_gray < 200)[0]
        p_high = axes.a * float(ys.min()) + axes.b if ys.size else max(o, c)
        p_low  = axes.a * float(ys.max()) + axes.b if ys.size else min(o, c)

        slot = obs.setdefault(bar_idx, {"open": o, "close": c, "high": p_high, "low": p_low})
        slot["high"] = max(slot["high"], p_high)
        slot["low"]  = min(slot["low"],  p_low)
        slot["close"] = c  # latest overwrite

    return obs

# -----------------------------
# Public APIs
# -----------------------------

def extract_ohlc_from_image(path: str) -> List[Dict[str, float]]:
    """Extract OHLC from a single chart image. Returns list of bars from oldest->newest.
    Each bar dict contains: x (center pixel), open, high, low, close.
    """
    img = cv2.imread(path)
    if img is None:
        raise RuntimeError(f"Failed to read image: {path}")

    x,y,w,h = _detect_chart_roi(img)
    chart = img[y:y+h, x:x+w]

    axes = _calibrate_axes(chart)
    if axes is None:
        raise RuntimeError("Axis calibration failed (OCR). Ensure Tesseract installed and ROI contains y-axis labels.")

    obs = _extract_bars_from_chart(chart, axes)
    bars = []
    for k in sorted(obs.keys(), reverse=True):  # oldest first
        # Convert slot index to x-position (optional; useful for debug)
        cx = axes.rightmost_x - k * max(1, axes.bar_px)
        item = obs[k].copy()
        item["x"] = float(cx)
        bars.append(item)
    return bars


def extract_ohlc_from_video(path: str, fps_sample: float = 3.0) -> List[Dict[str, float]]:
    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        raise RuntimeError(f"Cannot open video: {path}")

    ok, frame0 = cap.read()
    if not ok:
        raise RuntimeError("Empty video")

    x,y,w,h = _detect_chart_roi(frame0)
    chart0 = frame0[y:y+h, x:x+w]
    axes = _calibrate_axes(chart0)
    if axes is None:
        raise RuntimeError("Axis calibration failed (OCR).")

    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    step = max(1, int(round(fps / fps_sample)))

    buckets: Dict[int, Dict[str, float]] = {}
    fidx = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        if (fidx % step) != 0:
            fidx += 1
            continue
        fidx += 1

        chart = frame[y:y+h, x:x+w]
        obs = _extract_bars_from_chart(chart, axes)
        # merge
        for k, v in obs.items():
            slot = buckets.get(k)
            if slot is None:
                buckets[k] = v.copy()
            else:
                slot["high"] = max(slot["high"], v["high"])
                slot["low"]  = min(slot["low"],  v["low"])
                slot["close"] = v["close"]

    cap.release()

    bars = []
    for k in sorted(buckets.keys(), reverse=True):
        cx = axes.rightmost_x - k * max(1, axes.bar_px)
        item = buckets[k].copy()
        item["x"] = float(cx)
        bars.append(item)
    return bars

# -----------------------------
# Debug visualization (optional)
# -----------------------------

def debug_preview(image_path: str, save_path: Optional[str] = None) -> np.ndarray:
    img = cv2.imread(image_path)
    x,y,w,h = _detect_chart_roi(img)
    chart = img[y:y+h, x:x+w]
    axes = _calibrate_axes(chart)
    if axes is None:
        raise RuntimeError("Axis calibration failed (OCR)")
    H,W = chart.shape[:2]

    hsv = cv2.cvtColor(chart, cv2.COLOR_BGR2HSV)
    mask = _mask_bodies(hsv)
    overlay = chart.copy()
    overlay[mask>0] = (0, 255, 255)

    out = cv2.addWeighted(chart, 0.7, overlay, 0.3, 0)
    # Draw some vertical slots for reference
    for i in range(0, int(W/axes.bar_px)):
        cx = axes.rightmost_x - i*axes.bar_px
        if 0 <= cx < W:
            cv2.line(out, (cx, 0), (cx, H-1), (255, 0, 255), 1)
    if save_path:
        cv2.imwrite(save_path, out)
    return out
