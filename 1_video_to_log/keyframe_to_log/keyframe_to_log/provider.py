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
when uncertain. Do not invent hidden state, action history, card IDs, or long card descriptions.
An action is only present when the screenshot itself visibly supports it.
The JSON must contain page_type, confidence, state, action, and evidence. The state object should
contain floor, turn, player, enemies, hand, relics, potions, draw_count, discard_count,
exhaust_count, options, and visible_text; use null or empty arrays when not visible.
Keep the response concise. Evidence should contain at most 5 short strings and visible_text at
most 10 short strings. Never include markdown fences or explanatory text outside the JSON.
"""

CLASSIFY_PROMPT = """Classify a Slay the Spire 2 screenshot.
Return only one compact JSON object with exactly these keys:
{"page_type":"unknown","confidence":0.0}
page_type must be one of: unknown, run_start, map, combat, event, shop, rest,
treasure, card_reward, relic_reward, potion_reward, card_select, boss_relic,
deck_view, relic_view, act_transition, game_over, victory.
Do not describe the screenshot and do not include markdown.
"""

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
    "required": ["name", "entity_id", "amount", "upgraded", "cost"],
    "properties": {
        "name": NULLABLE_STRING,
        "entity_id": NULLABLE_STRING,
        "amount": NULLABLE_INTEGER,
        "upgraded": {"anyOf": [{"type": "boolean"}, {"type": "null"}]},
        "cost": NULLABLE_INTEGER,
    },
}
ACTOR_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["name", "hp", "max_hp", "block", "energy", "gold", "intent"],
    "properties": {
        "name": NULLABLE_STRING,
        "hp": NULLABLE_INTEGER,
        "max_hp": NULLABLE_INTEGER,
        "block": NULLABLE_INTEGER,
        "energy": NULLABLE_INTEGER,
        "gold": NULLABLE_INTEGER,
        "intent": NULLABLE_STRING,
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

    def _image_data(self, keyframe: Keyframe, box: tuple[int, int, int, int] | None = None) -> tuple[str, str]:
        with Image.open(keyframe.path) as source:
            image = source.crop(box) if box else source.copy()
            buffer = BytesIO()
            image.save(buffer, format="PNG", optimize=True)
        return base64.b64encode(buffer.getvalue()).decode("ascii"), "image/png"

    def observe(self, keyframe: Keyframe) -> dict:
        full_image, content_type = self._image_data(keyframe)
        classification = self._ask(full_image, content_type, "Classify this screenshot only.", system_prompt=CLASSIFY_PROMPT, max_tokens=int(os.environ.get("STS_VLM_CLASSIFY_MAX_TOKENS", "1024")))
        page_type = classification.get("page_type", "unknown")
        if page_type == "map":
            return self._ask(full_image, content_type, "Extract the complete visible map using the required node objects and directed path relationships.", system_prompt=MAP_PROMPT)
        full = self._ask(full_image, content_type, f"The page type is {page_type}. Extract the visible non-HUD state. Leave precise top-left HUD numbers null.")
        full["page_type"] = page_type
        full["confidence"] = min(float(full.get("confidence", 0)), float(classification.get("confidence", 0)))
        with Image.open(keyframe.path) as source:
            width, height = source.size
        hud_box = (0, 0, max(1, int(width * 0.34)), max(1, int(height * 0.14)))
        hud_image, hud_type = self._image_data(keyframe, hud_box)
        hud = self._ask(hud_image, hud_type, "This is a crop of the top-left HUD, not the full screen. Read only visible HUD values: current/max HP, gold, energy, floor/act indicators, and visible potion/relic counters. Do not infer combat cards, enemies, map nodes, or values outside this crop.")
        state = full.setdefault("state", {})
        hud_state = hud.get("state", {})
        if isinstance(hud_state, dict):
            for key in ("floor", "player"):
                if key in hud_state and hud_state[key] not in (None, {}):
                    state[key] = hud_state[key]
            if isinstance(hud_state.get("player"), dict):
                state.setdefault("player", {}).update(hud_state["player"])
        full.setdefault("evidence", []).append("HUD 数值来自左上角独立 ROI 裁剪")
        full["confidence"] = min(float(full.get("confidence", 0)), float(hud.get("confidence", 0)))
        return full

def provider_from_environment(mode: str) -> Provider:
    if mode == "mock":
        return MockProvider()
    return OpenAICompatibleProvider(os.environ.get("STS_VLM_BASE_URL", "https://api.deepseek.com"), os.environ["STS_VLM_API_KEY"], os.environ.get("STS_VLM_MODEL", "deepseek-flash"))

