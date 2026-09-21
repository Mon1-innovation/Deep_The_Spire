from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any

PAGE_TYPES = {"unknown", "run_start", "map", "combat", "event", "shop", "rest", "treasure", "card_reward", "relic_reward", "potion_reward", "card_select", "boss_relic", "deck_view", "relic_view", "act_transition", "game_over", "victory"}

@dataclass(frozen=True)
class Keyframe:
    path: str
    timestamp: float
    frame_index: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

@dataclass
class Observation:
    keyframe: Keyframe
    page_type: str = "unknown"
    confidence: float = 0.0
    state: dict[str, Any] = field(default_factory=dict)
    action: dict[str, Any] | None = None
    evidence: list[str] = field(default_factory=list)
    extractor: str = "unknown"

    def as_dict(self) -> dict[str, Any]:
        return {"path": self.keyframe.path, "t": self.keyframe.timestamp, "frame_index": self.keyframe.frame_index, "keyframe_metadata": self.keyframe.metadata, "page_type": self.page_type, "confidence": self.confidence, "state": self.state, "action": self.action, "evidence": self.evidence, "extractor": self.extractor}

