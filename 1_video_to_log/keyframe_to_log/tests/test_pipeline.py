import json
from pathlib import Path
import pytest
from keyframe_to_log.codex import CodexCatalog
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
    assert result["provenance"]["observation_schema_version"] == "7"
    assert result["provenance"]["map_schema_version"] == "2"
    assert result["provenance"]["game_patch"] == "unknown"
    assert result["provenance"]["codex_catalogs"] == {}
    assert len(result["observations"]) == 1
    assert output.exists()
    assert output.with_suffix(".md").exists()
    assert output.with_suffix(".jsonl").exists()
    assert "\n    \"run_id\"" in output.read_text(encoding="utf-8")
    json.loads(output.read_text(encoding="utf-8"))
    lines = output.with_suffix(".jsonl").read_text(encoding="utf-8").splitlines()
    assert lines[0].startswith('{"id": 0, "by": "world", "type": "info"')


def test_pipeline_writes_normalized_combat_entities_to_log(tmp_path: Path):
    (tmp_path / "t_1.0.png").write_bytes(b"image")
    output = tmp_path / "log.json"

    class EntityProvider:
        cache_identity = "entity-test"

        def observe(self, keyframe):
            return {
                "page_type": "combat",
                "confidence": 0.9,
                "state": {
                    "enemies": [{"name": "Cultist", "hp": 10}],
                    "relics": [{"name": "Old Coin"}],
                    "potions": [{"name": "Fire Potion"}],
                },
                "action": None,
                "evidence": [],
            }

    catalog_args = {"lang": "zhs", "channel": "stable", "requested_version": None, "data_version": None, "source": "test"}
    catalogs = {
        "monsters": CodexCatalog([{"id": "CULTIST", "name": "Cultist"}], entity_type="monsters", **catalog_args),
        "relics": CodexCatalog([{"id": "OLD_COIN", "name": "Old Coin"}], entity_type="relics", **catalog_args),
        "potions": CodexCatalog([{"id": "FIRE_POTION", "name": "Fire Potion"}], entity_type="potions", **catalog_args),
    }

    result = convert_keyframes(tmp_path, output, EntityProvider(), run_id="entities", patch="0.111.0", catalogs=catalogs)

    observation = result["observations"][0]
    assert observation["state"]["enemies"][0]["entity_id"] == "CULTIST"
    assert observation["state"]["enemies"][0]["raw_name"] == "Cultist"
    assert observation["state"]["relics"][0]["entity_id"] == "OLD_COIN"
    assert observation["state"]["potions"][0]["entity_id"] == "FIRE_POTION"
    assert result["events"][-1]["info"]["state"]["potions"][0]["entity_id"] == "FIRE_POTION"
    assert result["provenance"]["codex_catalogs"]["monsters"]["entity_type"] == "monsters"

def test_empty_input_is_rejected(tmp_path: Path):
    with pytest.raises(ValueError, match="no supported keyframe images"):
        convert_keyframes(tmp_path, tmp_path / "log.json", MockProvider())



def test_discovers_upstream_keyframe_manifest_and_kf_names(tmp_path: Path):
    keyframes = tmp_path / "keyframes"
    keyframes.mkdir()
    (keyframes / "kf_000002_t_000002.000.jpg").write_bytes(b"image")
    (keyframes / "kf_000001_t_000001.000.jpg").write_bytes(b"image")
    (tmp_path / "keyframes.jsonl").write_text(
        json.dumps({"keyframe_id": "run-kf-000002", "frame_index": 60, "timestamp_sec": 2.0, "path": "keyframes/kf_000002_t_000002.000.jpg", "trigger": "roi_change"}) + "\n"
        + json.dumps({"keyframe_id": "run-kf-000001", "frame_index": 30, "timestamp_sec": 1.0, "path": "keyframes/kf_000001_t_000001.000.jpg", "trigger": "periodic_anchor"}) + "\n",
        encoding="utf-8",
    )
    frames = discover_keyframes(tmp_path)
    assert [frame.frame_index for frame in frames] == [60, 30]
    assert frames[0].metadata["trigger"] == "roi_change"
