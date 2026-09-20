from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import cv2


def write_json_atomic(path: Path, value: Any) -> None:
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    os.replace(temp, path)


def write_jpeg(path: Path, frame, quality: int) -> None:
    ok, encoded = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
    if not ok:
        raise OSError(f"failed to encode JPEG: {path}")
    path.write_bytes(encoded.tobytes())

