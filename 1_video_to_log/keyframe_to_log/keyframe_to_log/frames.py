from __future__ import annotations
import re
import json
from pathlib import Path
from .models import Keyframe

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
_TIME_PATTERNS = (re.compile(r"(?:^|[_-])t(?:ime)?[_-]?(\d+(?:\.\d+)?)", re.I), re.compile(r"(?:^|[_-])(\d+(?:\.\d+)?)s(?:[_-]|$)", re.I))
_FRAME_PATTERN = re.compile(r"(?:^|[_-])(?:frame|kf|f)[_-]?(\d+)(?:[_-]|\.|$)", re.I)

def _number_from_name(path: Path) -> float | None:
    for pattern in _TIME_PATTERNS:
        match = pattern.search(path.stem)
        if match:
            return float(match.group(1))
    numbers = re.findall(r"\d+(?:\.\d+)?", path.stem)
    return float(numbers[-1]) if numbers else None

def _frame_index(path: Path) -> int | None:
    match = _FRAME_PATTERN.search(path.stem)
    return int(match.group(1)) if match else None

def discover_keyframes(root: str | Path) -> list[Keyframe]:
    root = Path(root)
    paths = [p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS]
    metadata_by_path: dict[str, dict] = {}
    for metadata_path in (root / "keyframes.jsonl", root.parent / "keyframes.jsonl"):
        if not metadata_path.is_file():
            continue
        for line in metadata_path.read_text(encoding="utf-8").splitlines():
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            relative = item.get("path")
            if isinstance(relative, str):
                normalized = relative.replace("\\", "/")
                metadata_by_path[normalized] = item
                if normalized.startswith("keyframes/"):
                    metadata_by_path[normalized[len("keyframes/"):]] = item
        break
    frames = []
    for ordinal, image_path in enumerate(sorted(paths)):
        relative = image_path.relative_to(root).as_posix()
        item = metadata_by_path.get(relative)
        if item is None and root.parent != root:
            item = metadata_by_path.get(image_path.relative_to(root.parent).as_posix())
        timestamp = item.get("timestamp_sec") if item else _number_from_name(image_path)
        frame_index = item.get("frame_index") if item else _frame_index(image_path)
        frames.append(Keyframe(str(image_path), float(timestamp) if timestamp is not None else float(ordinal), frame_index, item or {}))
    if metadata_by_path:
        order = {key: index for index, key in enumerate(metadata_by_path)}
        return sorted(frames, key=lambda frame: (order.get(Path(frame.path).relative_to(root).as_posix(), len(order)), frame.timestamp, frame.path))
    return sorted(frames, key=lambda frame: (frame.timestamp, frame.path))

