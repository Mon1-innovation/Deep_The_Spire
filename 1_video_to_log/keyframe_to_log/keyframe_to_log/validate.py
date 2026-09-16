from __future__ import annotations
from typing import Any
from .models import Observation, PAGE_TYPES

def validate_observation(value: dict[str, Any]) -> Observation:
    page_type = value.get("page_type", "unknown")
    if page_type not in PAGE_TYPES:
        raise ValueError(f"invalid page_type: {page_type}")
    confidence = float(value.get("confidence", 0.0))
    if not 0.0 <= confidence <= 1.0:
        raise ValueError("confidence must be between 0 and 1")
    state = value.get("state", {})
    if not isinstance(state, dict):
        raise ValueError("state must be an object")
    action = value.get("action")
    if action is not None and not isinstance(action, dict):
        raise ValueError("action must be an object or null")
    evidence = value.get("evidence", [])
    if not isinstance(evidence, list) or not all(isinstance(item, str) for item in evidence):
        raise ValueError("evidence must be a string array")
    return Observation(keyframe=value["keyframe"], page_type=page_type, confidence=confidence, state=state, action=action, evidence=evidence, extractor=str(value.get("extractor", "unknown")))

