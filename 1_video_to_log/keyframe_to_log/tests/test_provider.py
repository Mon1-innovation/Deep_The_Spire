from pathlib import Path

from PIL import Image

from keyframe_to_log.models import Keyframe
from keyframe_to_log.provider import ENERGY_PROMPT, OpenAICompatibleProvider


def test_combat_energy_is_read_from_bottom_left_crop(tmp_path: Path, monkeypatch):
    image_path = tmp_path / "combat.png"
    Image.new("RGB", (1280, 720), "black").save(image_path)
    provider = OpenAICompatibleProvider("https://example.invalid", "test", "test-model")
    boxes = []
    ask_calls = []
    monkeypatch.setattr(provider, "_image_data", lambda frame, box=None: (boxes.append(box) or "image", "image/png"))
    responses = iter([
        {"page_type": "combat", "confidence": 0.95},
        {"page_type": "combat", "confidence": 0.9, "state": {"player": {"hp": 52, "max_hp": 70, "energy": None}}},
        {"confidence": 0.9, "state": {"floor": 14, "player": {"hp": 52, "max_hp": 70, "gold": 14}}},
        {"confidence": 0.95, "state": {"player": {"energy": 1}}},
    ])
    def fake_ask(*args, **kwargs):
        ask_calls.append((args, kwargs))
        return next(responses)

    monkeypatch.setattr(provider, "_ask", fake_ask)

    result = provider.observe(Keyframe(str(image_path), 17.2))

    assert boxes == [None, (0, 0, 435, 100), (0, 503, 256, 705)]
    assert result["state"]["player"]["energy"] == 1
    assert result["state"]["player"]["hp"] == 52
    assert len(result["evidence"]) == 2
    assert ask_calls[-1][1]["system_prompt"] == ENERGY_PROMPT
    assert ask_calls[-1][1]["max_tokens"] == 256


def test_noncombat_page_skips_energy_crop(tmp_path: Path, monkeypatch):
    image_path = tmp_path / "event.png"
    Image.new("RGB", (1280, 720), "black").save(image_path)
    provider = OpenAICompatibleProvider("https://example.invalid", "test", "test-model")
    boxes = []
    monkeypatch.setattr(provider, "_image_data", lambda frame, box=None: (boxes.append(box) or "image", "image/png"))
    responses = iter([
        {"page_type": "event", "confidence": 0.95},
        {"page_type": "event", "confidence": 0.9, "state": {"player": {"energy": None}}},
        {"confidence": 0.9, "state": {"player": {"gold": 14}}},
    ])
    monkeypatch.setattr(provider, "_ask", lambda *args, **kwargs: next(responses))

    result = provider.observe(Keyframe(str(image_path), 17.2))

    assert boxes == [None, (0, 0, 435, 100)]
    assert result["state"]["player"]["energy"] is None


def test_unreadable_energy_crop_does_not_erase_existing_value(tmp_path: Path, monkeypatch):
    image_path = tmp_path / "combat.png"
    Image.new("RGB", (1280, 720), "black").save(image_path)
    provider = OpenAICompatibleProvider("https://example.invalid", "test", "test-model")
    monkeypatch.setattr(provider, "_image_data", lambda frame, box=None: ("image", "image/png"))
    responses = iter([
        {"page_type": "combat", "confidence": 0.95},
        {"page_type": "combat", "confidence": 0.9, "state": {"player": {"energy": 2}}},
        {"confidence": 0.9, "state": {"player": {"gold": 14, "energy": None}}},
        {"confidence": 0.6, "state": {"player": {"energy": None}}},
    ])
    monkeypatch.setattr(provider, "_ask", lambda *args, **kwargs: next(responses))

    result = provider.observe(Keyframe(str(image_path), 17.2))

    assert result["state"]["player"]["energy"] == 2
