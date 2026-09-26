from __future__ import annotations
import base64
import json
import mimetypes
import os
import time
import urllib.error
import urllib.request
from io import BytesIO
from PIL import Image
from .models import Keyframe

SYSTEM_PROMPT = """You are a careful Slay the Spire 2 screenshot annotator.
Return only valid JSON matching the requested structure. Report only information visibly supported by the image.
Use null for unreadable values, page_type=unknown for an unclear page, and lower confidence
when uncertain. Do not invent hidden state, action history, entity IDs, or long card descriptions.
An action is only present when the screenshot itself visibly supports it.
The JSON must contain page_type, confidence, state, action, and evidence. The state object should
contain floor, turn, player, enemies, hand, relics, potions, draw_count, discard_count,
exhaust_count, options, and visible_text; use null or empty arrays when not visible.
Return every visible enemy, potion, and relic as one object per entity. Transcribe a name only when
supported by visible text or clearly recognizable art; otherwise use null. Always set entity_id to
null because the local catalog resolves IDs. Never list empty item slots. Add visual_confidence from
0 to 1 for each identifiable entity, or null when its identity is not clear. Entity objects must
include entity_type (cards, relics, potions, or null). For the player actor, set entity_id and
visual_confidence to null.
Keep the response concise. Evidence should contain at most 5 short strings and visible_text at
most 10 short strings. Never include markdown fences or explanatory text outside the JSON.
"""

INVENTORY_PROMPT = """Inspect this enlarged top inventory bar crop from a Slay the Spire 2 screenshot.
Return only JSON shaped as {"confidence":0.0,"state":{"relics":[],"potions":[]},"evidence":[]}.
List each occupied player relic and potion slot exactly once; omit empty slots. Keep potion bottles
and passive relic icons in separate arrays. Name an item only when its icon or visible tooltip is
recognizable; otherwise include the occupied item with name=null and visual_confidence=null.
Do not count empty slots or infer hidden items. Each item must include name, entity_id, amount,
upgraded, cost, entity_type, and visual_confidence. entity_id must always be null.
"""

ENEMY_PROMPT = """Inspect this combat crop from a Slay the Spire 2 screenshot. Ignore the player.
Return only JSON shaped as {"confidence":0.0,"state":{"enemies":[]},"evidence":[]}.
Return one object per visible enemy, in left-to-right order. Read its name from visible text when
available; otherwise identify it from the enemy art only when confident. Read current/max HP, block,
and intent only when visible; do not infer intent from animation. Each enemy object must include
name, entity_id, hp, max_hp, block, energy, gold, intent, and visual_confidence. Set entity_id,
energy, and gold to null. Use null for unreadable fields.
"""

CLASSIFY_PROMPT = """Classify a Slay the Spire 2 screenshot.
Return only one compact JSON object with exactly these keys:
{"page_type":"unknown","confidence":0.0}
page_type must be one of: unknown, run_start, map, combat, event, shop, rest,
treasure, card_reward, relic_reward, potion_reward, card_select, boss_relic,
deck_view, relic_view, act_transition, game_over, victory.
Do not describe the screenshot and do not include markdown.
"""

ENERGY_PROMPT = """Read only the current energy number shown in the green gem in this bottom-left combat HUD crop. The display may look like 1/3; return the number before the slash as an integer. If unreadable or absent, return null. Do not infer it. Return only JSON in this shape: {"state":{"player":{"energy":1}}}."""

MAP_PROMPT = """Extract the entire visible Slay the Spire 2 map as compact JSON.
Return only valid JSON in exactly this shape:
{"page_type":"map","confidence":0.0,"state":{"floor":null,"map":{"current_node_id":null,"nodes":[],"paths":[]},"visible_text":[]},"action":null,"evidence":[]}
Each item in nodes is a room object with exactly these fields:
{"id":"r03n02","level":3,"type":"combat","status":"current","position":{"x":0.5,"y":0.4},"next_nodes":["r04n01"],"previous_nodes":["r02n01"]}
Use status "current", "visited", "available", or "unvisited". Use normalized position x/y values from 0 to 1.
The red downward arrow above a map node is the strongest and primary marker for the current node: assign status "current" to the node directly under its tip and set current_node_id to that node id. A black circle around a node means the node has already been visited; if the red arrow and black circle appear together, status must be "current" rather than only "visited". The yellow triangular mouse cursor is not a location marker and must be ignored. Never mark a node current only because it is circled, highlighted, near the bottom, or near the cursor. If no red arrow is visible or its target is unclear, use current_node_id=null and do not guess.
Each item in paths is a directed relationship with exactly these fields:
{"from":"r03n02","to":"r04n01","relation":"next_room"}
Include every visible room node and every visible connection. For every visible connection, add the target id to the source node's next_nodes and the source id to the target node's previous_nodes.
This representation must make it obvious which rooms are reachable next and what lies after them. Use short stable ids such as r03n02. Unknown room types must be "unknown".
Do not add descriptions, hidden nodes, inferred off-screen paths, or markdown.
"""

NULLABLE_INTEGER = {"anyOf": [{"type": "integer"}, {"type": "null"}]}
NULLABLE_STRING = {"anyOf": [{"type": "string"}, {"type": "null"}]}
ENTITY_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["name", "entity_id", "amount", "upgraded", "cost", "entity_type", "visual_confidence"],
    "properties": {
        "name": NULLABLE_STRING,
        "entity_id": NULLABLE_STRING,
        "amount": NULLABLE_INTEGER,
        "upgraded": {"anyOf": [{"type": "boolean"}, {"type": "null"}]},
        "cost": NULLABLE_INTEGER,
        "entity_type": {"anyOf": [{"type": "string", "enum": ["cards", "relics", "potions"]}, {"type": "null"}]},
        "visual_confidence": {"anyOf": [{"type": "number", "minimum": 0, "maximum": 1}, {"type": "null"}]},
    },
}
ACTOR_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["name", "entity_id", "hp", "max_hp", "block", "energy", "gold", "intent", "visual_confidence"],
    "properties": {
        "name": NULLABLE_STRING,
        "entity_id": NULLABLE_STRING,
        "hp": NULLABLE_INTEGER,
        "max_hp": NULLABLE_INTEGER,
        "block": NULLABLE_INTEGER,
        "energy": NULLABLE_INTEGER,
        "gold": NULLABLE_INTEGER,
        "intent": NULLABLE_STRING,
        "visual_confidence": {"anyOf": [{"type": "number", "minimum": 0, "maximum": 1}, {"type": "null"}]},
    },
}
STATE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["floor", "turn", "player", "enemies", "hand", "relics", "potions", "draw_count", "discard_count", "exhaust_count", "options", "visible_text"],
    "properties": {
        "floor": NULLABLE_INTEGER,
        "turn": NULLABLE_INTEGER,
        "player": ACTOR_SCHEMA,
        "enemies": {"type": "array", "items": ACTOR_SCHEMA},
        "hand": {"type": "array", "items": ENTITY_SCHEMA},
        "relics": {"type": "array", "items": ENTITY_SCHEMA},
        "potions": {"type": "array", "items": ENTITY_SCHEMA},
        "draw_count": NULLABLE_INTEGER,
        "discard_count": NULLABLE_INTEGER,
        "exhaust_count": NULLABLE_INTEGER,
        "options": {"type": "array", "items": ENTITY_SCHEMA},
        "visible_text": {"type": "array", "items": {"type": "string"}},
    },
}
ACTION_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["type", "choice", "card_name", "target"],
    "properties": {"type": "string", "choice": NULLABLE_STRING, "card_name": NULLABLE_STRING, "target": NULLABLE_STRING},
}
SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["page_type", "confidence", "state", "action", "evidence"],
    "properties": {
        "page_type": {"type": "string", "enum": ["unknown", "run_start", "map", "combat", "event", "shop", "rest", "treasure", "card_reward", "relic_reward", "potion_reward", "card_select", "boss_relic", "deck_view", "relic_view", "act_transition", "game_over", "victory"]},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "state": STATE_SCHEMA,
        "action": {"anyOf": [ACTION_SCHEMA, {"type": "null"}]},
        "evidence": {"type": "array", "items": {"type": "string"}},
    },
}

class Provider:
    name = "provider"

    @property
    def cache_identity(self) -> str:
        return self.name

    def observe(self, keyframe: Keyframe) -> dict:
        raise NotImplementedError

class MockProvider(Provider):
    name = "mock"
    def observe(self, keyframe: Keyframe) -> dict:
        return {"page_type": "unknown", "confidence": 0.0, "state": {}, "action": None, "evidence": []}

class OpenAICompatibleProvider(Provider):
    name = "openai-compatible"
    def __init__(self, base_url: str, api_key: str, model: str, timeout: int = 120, max_retries: int = 3):
        self.url = base_url.rstrip("/") + "/chat/completions"
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self.max_retries = max_retries

    @property
    def cache_identity(self) -> str:
        return f"{self.name}:{self.model}"

    def _request(self, image: str, content_type: str, retry: int, instruction: str, system_prompt: str, max_tokens: int) -> dict:
        retry_instruction = ""
        if retry:
            retry_instruction = " Previous output was invalid or truncated. Return a shorter JSON object with no prose."
        payload = {
            "model": self.model,
            "temperature": 0,
            "max_tokens": max_tokens,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": [
                    {"type": "text", "text": instruction + retry_instruction},
                    {"type": "image_url", "image_url": {"url": f"data:{content_type};base64,{image}"}},
                ]},
            ],
        }
        if retry < 2:
            payload["response_format"] = {"type": "json_object"}
        thinking_mode = os.environ.get("STS_VLM_THINKING", "disabled").lower()
        if thinking_mode != "omit":
            if retry == 0:
                payload["thinking"] = {"type": thinking_mode}
            elif retry == 1:
                payload["enable_thinking"] = False
        request = urllib.request.Request(self.url, data=json.dumps(payload).encode("utf-8"), method="POST")
        request.add_header("Authorization", f"Bearer {self.api_key}")
        request.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"VLM HTTP {error.code}: {detail[:1000]}") from error

    def _ask(self, image: str, content_type: str, instruction: str, system_prompt: str = SYSTEM_PROMPT, max_tokens: int | None = None) -> dict:
        errors = []
        token_limit = max_tokens or int(os.environ.get("STS_VLM_MAX_TOKENS", "8192"))
        for retry in range(self.max_retries):
            try:
                result = self._request(image, content_type, retry, instruction, system_prompt, token_limit)
            except RuntimeError as error:
                errors.append(f"attempt {retry + 1}: {error}")
                if retry + 1 < self.max_retries:
                    time.sleep(1 << retry)
                continue
            choice = result["choices"][0]
            content = choice.get("message", {}).get("content") or ""
            try:
                value = json.loads(content)
                if not isinstance(value, dict):
                    raise ValueError("model output is not a JSON object")
                return value
            except (json.JSONDecodeError, ValueError) as error:
                finish_reason = choice.get("finish_reason", "unknown")
                errors.append(f"attempt {retry + 1}: finish_reason={finish_reason}, chars={len(content)}, error={error}")
                if retry + 1 < self.max_retries:
                    time.sleep(1 << retry)
        raise RuntimeError(f"VLM returned invalid JSON after {self.max_retries} attempts: " + " | ".join(errors))

    def _image_data(self, keyframe: Keyframe, box: tuple[int, int, int, int] | None = None, scale: float = 1.0) -> tuple[str, str]:
        with Image.open(keyframe.path) as source:
            image = source.crop(box) if box else source.copy()
            if scale != 1.0:
                size = (max(1, round(image.width * scale)), max(1, round(image.height * scale)))
                image = image.resize(size, getattr(Image, "Resampling", Image).LANCZOS)
            buffer = BytesIO()
            image.save(buffer, format="PNG", optimize=True)
        return base64.b64encode(buffer.getvalue()).decode("ascii"), "image/png"

    @staticmethod
    def _merge_entities(existing: object, focused: object) -> list[dict]:
        if not isinstance(focused, list) or not focused:
            return existing if isinstance(existing, list) else []
        merged = [dict(item) for item in focused if isinstance(item, dict)]
        originals = existing if isinstance(existing, list) else []
        for index, item in enumerate(merged):
            if index < len(originals) and isinstance(originals[index], dict):
                combined = dict(originals[index])
                combined.update({key: value for key, value in item.items() if value is not None})
                merged[index] = combined
        if len(originals) > len(merged):
            merged.extend(dict(item) for item in originals[len(merged):] if isinstance(item, dict))
        return merged

    @staticmethod
    def _append_evidence(observation: dict, evidence: str) -> None:
        values = observation.get("evidence")
        if not isinstance(values, list):
            values = []
            observation["evidence"] = values
        values.append(evidence)

    def _inventory_observation(self, keyframe: Keyframe, width: int, height: int) -> dict:
        inventory_box = (int(width * 0.22), 0, int(width * 0.62), int(height * 0.16))
        inventory_image, inventory_type = self._image_data(keyframe, inventory_box, scale=2.0)
        return self._ask(inventory_image, inventory_type, "Read the occupied relic and potion slots from this crop.", system_prompt=INVENTORY_PROMPT, max_tokens=2048)

    def observe(self, keyframe: Keyframe) -> dict:
        full_image, content_type = self._image_data(keyframe)
        classification = self._ask(full_image, content_type, "Classify this screenshot only.", system_prompt=CLASSIFY_PROMPT, max_tokens=int(os.environ.get("STS_VLM_CLASSIFY_MAX_TOKENS", "1024")))
        page_type = classification.get("page_type", "unknown")
        with Image.open(keyframe.path) as source:
            width, height = source.size
        if page_type == "map":
            full = self._ask(full_image, content_type, "Extract the complete visible map using the required node objects and directed path relationships.", system_prompt=MAP_PROMPT)
            inventory = self._inventory_observation(keyframe, width, height)
            state = full.setdefault("state", {})
            if not isinstance(state, dict):
                state = {}
                full["state"] = state
            inventory_state = inventory.get("state", {})
            if isinstance(inventory_state, dict):
                for field in ("relics", "potions"):
                    state[field] = self._merge_entities(state.get(field), inventory_state.get(field))
            full["page_type"] = page_type
            full["confidence"] = min(float(full.get("confidence", 0)), float(classification.get("confidence", 0)))
            self._append_evidence(full, "Relics and potions read from the enlarged top inventory crop")
            return full
        full = self._ask(full_image, content_type, f"The page type is {page_type}. Extract the visible non-HUD state. Leave precise top-left HUD numbers null.")
        full["page_type"] = page_type
        full["confidence"] = min(float(full.get("confidence", 0)), float(classification.get("confidence", 0)))
        hud_box = (0, 0, max(1, int(width * 0.34)), max(1, int(height * 0.14)))
        hud_image, hud_type = self._image_data(keyframe, hud_box)
        hud = self._ask(hud_image, hud_type, "This is a crop of the top-left HUD, not the full screen. Read only visible HUD values: current/max HP, gold, and floor/act indicators. Do not read combat energy from this crop because energy is displayed separately at the bottom-left.")
        inventory = self._inventory_observation(keyframe, width, height)
        focused_enemies = None
        if page_type == "combat":
            enemy_box = (int(width * 0.30), int(height * 0.16), int(width * 0.99), int(height * 0.79))
            enemy_image, enemy_type = self._image_data(keyframe, enemy_box, scale=1.5)
            focused_enemies = self._ask(enemy_image, enemy_type, "Identify and read the visible enemies in this combat crop.", system_prompt=ENEMY_PROMPT, max_tokens=2048)
        energy = None
        if page_type == "combat":
            energy_box = (0, max(1, int(height * 0.70)), max(1, int(width * 0.20)), max(1, int(height * 0.98)))
            energy_image, energy_type = self._image_data(keyframe, energy_box)
            energy = self._ask(energy_image, energy_type, "Read the number before the slash in the bottom-left green energy gem.", system_prompt=ENERGY_PROMPT, max_tokens=256)
        state = full.setdefault("state", {})
        if not isinstance(state, dict):
            state = {}
            full["state"] = state
        inventory_state = inventory.get("state", {})
        if isinstance(inventory_state, dict):
            for field in ("relics", "potions"):
                state[field] = self._merge_entities(state.get(field), inventory_state.get(field))
        if isinstance(focused_enemies, dict):
            focused_state = focused_enemies.get("state", {})
            if isinstance(focused_state, dict):
                state["enemies"] = self._merge_entities(state.get("enemies"), focused_state.get("enemies"))
        player_state = state.get("player")
        if not isinstance(player_state, dict):
            player_state = {}
            state["player"] = player_state
        hud_state = hud.get("state", {})
        if isinstance(hud_state, dict):
            for key in ("floor",):
                if key in hud_state and hud_state[key] not in (None, {}):
                    state[key] = hud_state[key]
            if isinstance(hud_state.get("player"), dict):
                for key, value in hud_state["player"].items():
                    if key != "energy" or value is not None:
                        player_state[key] = value
        if energy is not None:
            energy_state = energy.get("state", {})
            if isinstance(energy_state, dict) and isinstance(energy_state.get("player"), dict):
                energy_value = energy_state["player"].get("energy")
                if energy_value is not None:
                    player_state["energy"] = energy_value
            self._append_evidence(full, "战斗能量来自左下角独立能量 ROI")
        self._append_evidence(full, "血量、金币等来自左上角独立 HUD ROI")
        self._append_evidence(full, "Relics and potions read from the enlarged top inventory crop")
        if focused_enemies is not None:
            self._append_evidence(full, "Enemy identities and combat stats read from the focused combat crop")
        full["confidence"] = min(float(full.get("confidence", 0)), float(hud.get("confidence", 0)))
        return full

def provider_from_environment(mode: str) -> Provider:
    if mode == "mock":
        return MockProvider()
    return OpenAICompatibleProvider(os.environ.get("STS_VLM_BASE_URL", "https://api.deepseek.com"), os.environ["STS_VLM_API_KEY"], os.environ.get("STS_VLM_MODEL", "deepseek-flash"))
