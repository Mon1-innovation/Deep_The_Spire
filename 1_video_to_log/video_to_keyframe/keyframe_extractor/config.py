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
    Roi("player_status", 0.68, 0.00, 0.32, 0.28, 1.2),
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


def load_settings(path: str | Path | None) -> Settings:
    settings = Settings()
    if not path:
        return settings
    data: dict[str, Any] = json.loads(Path(path).read_text(encoding="utf-8"))
    for key in ("coarse_fps", "change_threshold", "page_threshold", "roi_change_threshold",
                "combat_change_threshold", "event_change_threshold", "stable_frames",
                "stable_threshold", "anchor_interval", "phash_distance", "ssim_threshold",
                "pre_roll", "settle_timeout", "jpeg_quality", "max_decode_errors",
                "black_mean_threshold", "black_std_threshold", "black_dark_ratio"):
        if key in data:
            setattr(settings, key, type(getattr(settings, key))(data[key]))
    if "rois" in data:
        settings.rois = [Roi(r["name"], r["x"], r["y"], r["w"], r["h"], r.get("weight", 1.0)) for r in data["rois"]]
    return settings
