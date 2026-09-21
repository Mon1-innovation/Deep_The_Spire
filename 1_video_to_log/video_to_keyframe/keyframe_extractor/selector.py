from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from .config import Settings
from .scores import is_black_frame, phash, phash_distance, roi_scores, ssim
from .ocr import battle_start_text


@dataclass
class Selected:
    frame_index: int
    timestamp_sec: float
    frame: Any
    trigger: str
    changed_rois: list[str]
    change_score: float
    stable_frames: int
    confidence: str


class Selector:
    def __init__(self, settings: Settings, fps: float):
        self.settings = settings
        self.fps = fps
        self.last_frame = None
        self.last_sample_frame = None
        self.last_sample_index = -1
        self.last_output = None
        self.last_output_hash = None
        self.last_anchor = -1e9
        self.pending: dict[str, Any] | None = None
        self.last_ocr_timestamp = -1e9

    def consider(self, index: int, timestamp: float, frame) -> Selected | None:
        if is_black_frame(frame, self.settings.black_mean_threshold,
                          self.settings.black_std_threshold,
                          self.settings.black_dark_ratio):
            # Do not use the transition frame as a baseline.  The next real
            # frame is then compared with the last useful game state.
            return None
        if self.last_frame is None:
            self.last_frame = frame
            self.last_sample_frame = frame
            self.last_sample_index = index
            return self._emit(index, timestamp, frame, "periodic_anchor", [], 0.0, 1, "candidate")
        sample_gap = max(1, round(self.fps / max(self.settings.coarse_fps, 0.1)))
        if index - self.last_sample_index < sample_gap:
            return None
        if (timestamp - self.last_ocr_timestamp >= self.settings.battle_start_ocr_interval
                and battle_start_text(frame, self.settings)):
            self.last_ocr_timestamp = timestamp
            return self._emit(index, timestamp, frame, "combat_start_ocr", ["combat_hand"], 1.0, 1, "candidate")
        thresholds = {roi.name: self.settings.roi_change_threshold for roi in self.settings.rois}
        thresholds.update({"combat_center": self.settings.combat_change_threshold,
                           "combat_hand": self.settings.combat_change_threshold,
                           "event_options": self.settings.event_change_threshold})
        thresholds["shop_decision"] = self.settings.shop_change_threshold
        previous_sample = self.last_sample_frame
        previous_index = self.last_sample_index
        previous_timestamp = previous_index / self.fps if self.fps else timestamp
        local, global_score, changed = roi_scores(self.last_frame, frame, self.settings.rois, thresholds)
        self.last_frame = frame
        self.last_sample_frame = frame
        self.last_sample_index = index
        if timestamp - self.last_anchor >= self.settings.anchor_interval:
            return self._emit(index, timestamp, frame, "periodic_anchor", [], global_score, 1, "candidate")
        sensitive = {"hand", "combat_center", "combat_hand", "event_options", "shop_decision"}
        sensitive_changed = bool(sensitive.intersection(changed))
        if (local < self.settings.change_threshold and
                global_score < self.settings.page_threshold and not sensitive_changed):
            return None
        if self.pending is None:
            self.pending = {"index": index, "timestamp": timestamp, "frame": frame.copy(), "trigger": "page_change" if global_score >= self.settings.page_threshold else "roi_change", "changed": changed, "score": max(local, global_score), "stable": 0, "best": frame.copy(), "best_score": max(local, global_score), "previous": previous_sample.copy() if previous_sample is not None else None, "previous_index": previous_index, "previous_timestamp": previous_timestamp}
            return None
        pending = self.pending
        stable_local, stable_global, _ = roi_scores(pending["frame"], frame, self.settings.rois, self.settings.roi_change_threshold)
        score = max(stable_local, stable_global)
        if score < self.settings.stable_threshold:
            pending["stable"] += 1
        else:
            pending["stable"] = 0
        if score < pending["best_score"]:
            pending["best"] = frame.copy(); pending["best_score"] = score
        if pending["stable"] >= self.settings.stable_frames:
            result = self._emit_pending(pending, "candidate")
            self.pending = None
            return result
        if timestamp - pending["timestamp"] >= self.settings.settle_timeout:
            result = self._emit_pending(pending, "low")
            self.pending = None
            return result
        return None

    def finish(self) -> Selected | None:
        """Flush a candidate that is still inside the settle window at EOF."""
        if self.pending is None:
            return None
        pending = self.pending
        self.pending = None
        return self._emit_pending(pending, "low")

    def _emit_pending(self, pending: dict[str, Any], confidence: str) -> Selected | None:
        use_previous = (self.settings.pseudo_keyframe_fallback
                        and pending.get("previous") is not None
                        and set(pending["changed"]).intersection(self.settings.pseudo_keyframe_rois))
        if use_previous:
            return self._emit(pending["previous_index"], pending["previous_timestamp"], pending["previous"],
                              pending["trigger"] + "_pre_coarse", pending["changed"], pending["score"],
                              pending["stable"], confidence)
        return self._emit(pending["index"], pending["timestamp"], pending["best"], pending["trigger"],
                          pending["changed"], pending["score"], pending["stable"], confidence)

    def _emit(self, index, timestamp, frame, trigger, changed, score, stable, confidence):
        image_hash = phash(frame)
        if self.last_output is not None:
            distance = phash_distance(self.last_output_hash, image_hash)
            if distance <= self.settings.phash_distance and ssim(self.last_output, frame) >= self.settings.ssim_threshold:
                return None
        self.last_output = frame.copy(); self.last_output_hash = image_hash; self.last_anchor = timestamp
        return Selected(index, timestamp, frame, trigger, changed, score, stable, confidence)
