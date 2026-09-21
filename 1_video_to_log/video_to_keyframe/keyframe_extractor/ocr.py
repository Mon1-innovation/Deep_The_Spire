from __future__ import annotations

import re

import cv2

from .config import Roi, Settings


def battle_start_text(frame, settings: Settings) -> str | None:
    """Return matching OCR text when the optional battle-start banner is visible."""
    if not settings.battle_start_ocr_enabled:
        return None
    try:
        import pytesseract
    except ImportError:
        return None
    height, width = frame.shape[:2]
    x, y, right, bottom = Roi("battle_start_ocr", 0.20, 0.20, 0.60, 0.35).pixels(width, height)
    crop = cv2.cvtColor(frame[y:bottom, x:right], cv2.COLOR_BGR2GRAY)
    crop = cv2.resize(crop, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)
    text = re.sub(r"\s+", " ", pytesseract.image_to_string(crop, config="--psm 6").strip().lower())
    return text if any(keyword in text for keyword in settings.battle_start_ocr_keywords) else None
