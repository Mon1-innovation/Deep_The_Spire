from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any


@dataclass
class Roi:
    name: str
    x: float
    y: float
    w: float
    h: float
    weight: float = 1.0

    def pixels(self, width: int, height: int) -> tuple[int, int, int, int]:
        x = max(0, min(width - 1, round(self.x * width)))
        y = max(0, min(height - 1, round(self.y * height)))
        right = max(x + 1, min(width, round((self.x + self.w) * width)))
        bottom = max(y + 1, min(height, round((self.y + self.h) * height)))
        return x, y, right, bottom


DEFAULT_ROIS = [
    Roi("top_hud", 0.0, 0.0, 0.42, 0.18, 0.7),
    Roi("combat_center", 0.20, 0.18, 0.60, 0.58, 1.5),
    Roi("hand", 0.12, 0.72, 0.76, 0.28, 1.5),
    Roi("combat_hand", 0.18, 0.64, 0.64, 0.30, 2.2),
    Roi("selection_overlay", 0.28, 0.16, 0.44, 0.58, 2.0),
    Roi("deck_overlay", 0.10, 0.08, 0.80, 0.84, 1.8),
    Roi("potion_bar", 0.78, 0.56, 0.22, 0.30, 1.6),
    Roi("player_status", 0.68, 0.00, 0.32, 0.28, 1.2),
    Roi("shop_decision", 0.10, 0.16, 0.80, 0.70, 1.8),
    Roi("event_options", 0.18, 0.24, 0.64, 0.54, 2.4),
    Roi("full_frame", 0.0, 0.0, 1.0, 1.0, 0.9),
]


@dataclass
class Settings:
    # A card can appear and settle in well under half a second.  Keep the
    # coarse pass dense enough to see it; deduplication controls output size.
    coarse_fps: float = 6.0
    change_threshold: float = 0.08
    page_threshold: float = 0.18
    roi_change_threshold: float = 0.025
    combat_change_threshold: float = 0.018
    event_change_threshold: float = 0.018
    shop_change_threshold: float = 0.018
    stable_frames: int = 5
    stable_threshold: float = 0.025
    anchor_interval: float = 5.0
    phash_distance: int = 6
    ssim_threshold: float = 0.985
    pre_roll: float = 0.5
    settle_timeout: float = 2.0
    jpeg_quality: int = 95
    max_decode_errors: int = 10
    black_mean_threshold: float = 8.0
    black_std_threshold: float = 12.0
    black_dark_ratio: float = 0.995
    rois: list[Roi] = field(default_factory=lambda: list(DEFAULT_ROIS))
    pseudo_keyframe_fallback: bool = True
    pseudo_keyframe_rois: tuple[str, ...] = ("combat_hand", "hand")
    # combat keeps the conservative default; decision also covers event/shop/deck views.
    pseudo_keyframe_scope: str = "combat"
    decision_merge_window: float = 1.5
    decision_merge_ssim: float = 0.94
    decision_merge_phash_distance: int = 12
    decision_merge_rois: tuple[str, ...] = ("event_options", "shop_decision", "deck_overlay")
    battle_start_ocr_enabled: bool = False
    battle_start_ocr_interval: float = 1.0
    battle_start_ocr_keywords: tuple[str, ...] = ("battle start", "combat start", "战斗开始")


def load_settings(path: str | Path | None) -> Settings:
    settings = Settings()
    if not path:
        return settings
    data: dict[str, Any] = json.loads(Path(path).read_text(encoding="utf-8"))
    for key in ("coarse_fps", "change_threshold", "page_threshold", "roi_change_threshold",
                "combat_change_threshold", "event_change_threshold", "shop_change_threshold", "stable_frames",
                "stable_threshold", "anchor_interval", "phash_distance", "ssim_threshold",
                "pre_roll", "settle_timeout", "jpeg_quality", "max_decode_errors",
                "black_mean_threshold", "black_std_threshold", "black_dark_ratio",
                "decision_merge_window", "decision_merge_ssim",
                "decision_merge_phash_distance"):
        if key in data:
            setattr(settings, key, type(getattr(settings, key))(data[key]))
    if "rois" in data:
        settings.rois = [Roi(r["name"], r["x"], r["y"], r["w"], r["h"], r.get("weight", 1.0)) for r in data["rois"]]
    settings.pseudo_keyframe_fallback = bool(data.get("pseudo_keyframe_fallback", settings.pseudo_keyframe_fallback))
    if "pseudo_keyframe_rois" in data:
        settings.pseudo_keyframe_rois = tuple(str(value) for value in data["pseudo_keyframe_rois"])
    if "pseudo_keyframe_scope" in data:
        scope = str(data["pseudo_keyframe_scope"]).lower()
        if scope not in {"combat", "decision", "global"}:
            raise ValueError("pseudo_keyframe_scope must be one of: combat, decision, global")
        settings.pseudo_keyframe_scope = scope
    if "decision_merge_rois" in data:
        settings.decision_merge_rois = tuple(str(value) for value in data["decision_merge_rois"])
    ocr = data.get("battle_start_ocr", {})
    if isinstance(ocr, dict):
        settings.battle_start_ocr_enabled = bool(ocr.get("enabled", settings.battle_start_ocr_enabled))
        settings.battle_start_ocr_interval = float(ocr.get("interval", settings.battle_start_ocr_interval))
        if "keywords" in ocr:
            settings.battle_start_ocr_keywords = tuple(str(value).lower() for value in ocr["keywords"])
    return settings
