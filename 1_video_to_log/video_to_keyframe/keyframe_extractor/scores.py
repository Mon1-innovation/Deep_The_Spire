from __future__ import annotations

import cv2
import numpy as np

from .config import Roi


def small_gray(frame: np.ndarray) -> np.ndarray:
    return cv2.resize(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), (320, 180), interpolation=cv2.INTER_AREA)


def is_black_frame(frame: np.ndarray, mean_threshold: float = 8.0,
                   std_threshold: float = 12.0, dark_ratio: float = 0.995) -> bool:
    """Recognize fade-to-black frames without rejecting dark game artwork."""
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    mean = float(np.mean(gray))
    if mean <= mean_threshold and float(np.std(gray)) <= std_threshold:
        return True
    return float(np.mean(gray <= 16)) >= dark_ratio


def roi_scores(previous: np.ndarray, current: np.ndarray, rois: list[Roi],
               change_threshold: float | dict[str, float] = 0.04) -> tuple[float, float, list[str]]:
    height, width = current.shape[:2]
    weighted = 0.0
    total_weight = 0.0
    changed: list[str] = []
    for roi in rois:
        x, y, right, bottom = roi.pixels(width, height)
        before = cv2.cvtColor(previous[y:bottom, x:right], cv2.COLOR_BGR2GRAY)
        after = cv2.cvtColor(current[y:bottom, x:right], cv2.COLOR_BGR2GRAY)
        if before.size == 0 or after.size == 0:
            continue
        score = float(np.mean(cv2.absdiff(before, after)) / 255.0)
        weighted += score * roi.weight
        total_weight += roi.weight
        threshold = (change_threshold.get(roi.name, 0.04)
                     if isinstance(change_threshold, dict) else change_threshold)
        if score >= threshold:
            changed.append(roi.name)
    local = weighted / total_weight if total_weight else 0.0
    global_score = float(np.mean(cv2.absdiff(small_gray(previous), small_gray(current))) / 255.0)
    return local, global_score, changed


def phash(frame: np.ndarray) -> np.ndarray:
    gray = cv2.resize(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), (32, 32), interpolation=cv2.INTER_AREA).astype(np.float32)
    dct = cv2.dct(gray)[:8, :8]
    return dct > np.median(dct[1:, :])


def phash_distance(left: np.ndarray, right: np.ndarray) -> int:
    return int(np.count_nonzero(left != right))


def ssim(left: np.ndarray, right: np.ndarray) -> float:
    a = small_gray(left).astype(np.float32)
    b = small_gray(right).astype(np.float32)
    c1, c2 = 6.5025, 58.5225
    mean_a, mean_b = cv2.mean(a)[0], cv2.mean(b)[0]
    var_a = float(np.var(a)); var_b = float(np.var(b)); cov = float(np.mean((a - mean_a) * (b - mean_b)))
    return ((2 * mean_a * mean_b + c1) * (2 * cov + c2)) / ((mean_a ** 2 + mean_b ** 2 + c1) * (var_a + var_b + c2))
