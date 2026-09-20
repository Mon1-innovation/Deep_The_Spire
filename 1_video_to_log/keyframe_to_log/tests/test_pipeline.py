import json
from pathlib import Path
import pytest
from keyframe_to_log.frames import discover_keyframes
from keyframe_to_log.pipeline import convert_keyframes
from keyframe_to_log.provider import MockProvider

def test_discover_keyframes_orders_by_timestamp(tmp_path: Path):
    for name in ["frame_20_t_2.0.png", "frame_10_t_1.0.png"]:
        (tmp_path / name).write_bytes(b"image")
    frames = discover_keyframes(tmp_path)
    assert [frame.timestamp for frame in frames] == [1.0, 2.0]

def test_mock_pipeline_is_repeatable_and_cached(tmp_path: Path):
    (tmp_path / "t_1.0.png").write_bytes(b"image")
    output = tmp_path / "log.json"
    result = convert_keyframes(tmp_path, output, MockProvider(), run_id="test")
    assert result["run_id"] == "test"
    assert result["provenance"]["schema_version"] == "2.0"
    assert result["provenance"]["observation_schema_version"] == "5"
    assert result["provenance"]["map_schema_version"] == "2"
    assert result["provenance"]["game_patch"] == "unknown"
    assert len(result["observations"]) == 1
    assert output.exists()
    assert output.with_suffix(".md").exists()
    assert output.with_suffix(".jsonl").exists()
    assert "\n    \"run_id\"" in output.read_text(encoding="utf-8")
    json.loads(output.read_text(encoding="utf-8"))
    lines = output.with_suffix(".jsonl").read_text(encoding="utf-8").splitlines()
    assert lines[0].startswith('{"id": 0, "by": "world", "type": "info"')

def test_empty_input_is_rejected(tmp_path: Path):
    with pytest.raises(ValueError, match="no supported keyframe images"):
        convert_keyframes(tmp_path, tmp_path / "log.json", MockProvider())

