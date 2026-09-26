from pathlib import Path

from PIL import Image

from keyframe_to_log.models import Keyframe
from keyframe_to_log.provider import ENEMY_PROMPT, ENERGY_PROMPT, INVENTORY_PROMPT, OpenAICompatibleProvider


def test_combat_energy_is_read_from_bottom_left_crop(tmp_path: Path, monkeypatch):
    image_path = tmp_path / "combat.png"
    Image.new("RGB", (1280, 720), "black").save(image_path)
    provider = OpenAICompatibleProvider("https://example.invalid", "test", "test-model")
    boxes = []
    ask_calls = []
    monkeypatch.setattr(provider, "_image_data", lambda frame, box=None, scale=1.0: (boxes.append((box, scale)) or "image", "image/png"))
    responses = iter([
        {"page_type": "combat", "confidence": 0.95},
        {"page_type": "combat", "confidence": 0.9, "state": {"player": {"hp": 52, "max_hp": 70, "energy": None}, "enemies": [{"name": None, "hp": 39}, {"name": None, "hp": 26}]}},
        {"confidence": 0.9, "state": {"floor": 14, "player": {"hp": 52, "max_hp": 70, "gold": 14}}},
        {"confidence": 0.9, "state": {"relics": [{"name": "Old Coin", "entity_id": None, "amount": None, "upgraded": None, "cost": None, "entity_type": "relics", "visual_confidence": 0.9}], "potions": [{"name": "Fire Potion", "entity_id": None, "amount": None, "upgraded": None, "cost": None, "entity_type": "potions", "visual_confidence": 0.95}]}},
        {"confidence": 0.9, "state": {"enemies": [{"name": "Cultist", "entity_id": None, "hp": 39, "max_hp": 39, "block": 0, "energy": None, "gold": None, "intent": "attack", "visual_confidence": 0.9}, {"name": "Jaw Worm", "entity_id": None, "hp": 26, "max_hp": 26, "block": 0, "energy": None, "gold": None, "intent": "attack", "visual_confidence": 0.9}]}},
        {"confidence": 0.95, "state": {"player": {"energy": 1}}},
    ])
    def fake_ask(*args, **kwargs):
        ask_calls.append((args, kwargs))
        return next(responses)

    monkeypatch.setattr(provider, "_ask", fake_ask)

    result = provider.observe(Keyframe(str(image_path), 17.2))

    assert boxes == [(None, 1.0), ((0, 0, 435, 100), 1.0), ((281, 0, 793, 115), 2.0), ((384, 115, 1267, 568), 1.5), ((0, 503, 256, 705), 1.0)]
    assert result["state"]["player"]["energy"] == 1
    assert result["state"]["player"]["hp"] == 52
    assert result["state"]["enemies"][0]["name"] == "Cultist"
    assert result["state"]["relics"][0]["name"] == "Old Coin"
    assert result["state"]["potions"][0]["name"] == "Fire Potion"
    assert len(result["evidence"]) == 4
    assert ask_calls[-1][1]["system_prompt"] == ENERGY_PROMPT
    assert ask_calls[-1][1]["max_tokens"] == 256
    assert ask_calls[3][1]["system_prompt"] == INVENTORY_PROMPT
    assert ask_calls[4][1]["system_prompt"] == ENEMY_PROMPT


def test_noncombat_page_skips_energy_crop(tmp_path: Path, monkeypatch):
    image_path = tmp_path / "event.png"
    Image.new("RGB", (1280, 720), "black").save(image_path)
    provider = OpenAICompatibleProvider("https://example.invalid", "test", "test-model")
    boxes = []
    monkeypatch.setattr(provider, "_image_data", lambda frame, box=None, scale=1.0: (boxes.append((box, scale)) or "image", "image/png"))
    responses = iter([
        {"page_type": "event", "confidence": 0.95},
        {"page_type": "event", "confidence": 0.9, "state": {"player": {"energy": None}}},
        {"confidence": 0.9, "state": {"player": {"gold": 14}}},
        {"state": {"potions": [{"name": "Fire Potion"}], "relics": []}},
    ])
    monkeypatch.setattr(provider, "_ask", lambda *args, **kwargs: next(responses))

    result = provider.observe(Keyframe(str(image_path), 17.2))

    assert boxes == [(None, 1.0), ((0, 0, 435, 100), 1.0), ((281, 0, 793, 115), 2.0)]
    assert result["state"]["player"]["energy"] is None
    assert result["state"]["potions"][0]["name"] == "Fire Potion"


def test_unreadable_energy_crop_does_not_erase_existing_value(tmp_path: Path, monkeypatch):
    image_path = tmp_path / "combat.png"
    Image.new("RGB", (1280, 720), "black").save(image_path)
    provider = OpenAICompatibleProvider("https://example.invalid", "test", "test-model")
    monkeypatch.setattr(provider, "_image_data", lambda frame, box=None, scale=1.0: ("image", "image/png"))
    responses = iter([
        {"page_type": "combat", "confidence": 0.95},
        {"page_type": "combat", "confidence": 0.9, "state": {"player": {"energy": 2}}},
        {"confidence": 0.9, "state": {"player": {"gold": 14, "energy": None}}},
        {"state": {"relics": [], "potions": []}},
        {"state": {"enemies": []}},
        {"confidence": 0.6, "state": {"player": {"energy": None}}},
    ])
    monkeypatch.setattr(provider, "_ask", lambda *args, **kwargs: next(responses))

    result = provider.observe(Keyframe(str(image_path), 17.2))

    assert result["state"]["player"]["energy"] == 2


def test_null_player_state_is_initialized_before_hud_merge(tmp_path: Path, monkeypatch):
    image_path = tmp_path / "combat.png"
    Image.new("RGB", (1280, 720), "black").save(image_path)
    provider = OpenAICompatibleProvider("https://example.invalid", "test", "test-model")
    monkeypatch.setattr(provider, "_image_data", lambda frame, box=None, scale=1.0: ("image", "image/png"))
    responses = iter([
        {"page_type": "combat", "confidence": 0.95},
        {"page_type": "combat", "confidence": 0.9, "state": {"player": None}},
        {"confidence": 0.9, "state": {"player": {"hp": 52, "gold": 14, "energy": None}}},
        {"state": {"relics": [], "potions": []}},
        {"state": {"enemies": []}},
        {"state": {"player": {"energy": 1}}},
    ])
    monkeypatch.setattr(provider, "_ask", lambda *args, **kwargs: next(responses))

    result = provider.observe(Keyframe(str(image_path), 17.2))

    assert result["state"]["player"] == {"hp": 52, "gold": 14, "energy": 1}


def test_map_page_still_reads_inventory_crop(tmp_path: Path, monkeypatch):
    image_path = tmp_path / "map.png"
    Image.new("RGB", (1280, 720), "black").save(image_path)
    provider = OpenAICompatibleProvider("https://example.invalid", "test", "test-model")
    boxes = []
    monkeypatch.setattr(provider, "_image_data", lambda frame, box=None, scale=1.0: (boxes.append((box, scale)) or "image", "image/png"))
    responses = iter([
        {"page_type": "map", "confidence": 0.95},
        {"page_type": "map", "confidence": 0.9, "state": {"map": {"nodes": []}}},
        {"state": {"relics": [{"name": "Old Coin"}], "potions": []}},
    ])
    monkeypatch.setattr(provider, "_ask", lambda *args, **kwargs: next(responses))

    result = provider.observe(Keyframe(str(image_path), 17.2))

    assert boxes == [(None, 1.0), ((281, 0, 793, 115), 2.0)]
    assert result["state"]["relics"][0]["name"] == "Old Coin"
