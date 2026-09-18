from __future__ import annotations

import difflib
import json
import re
import unicodedata
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

DEFAULT_BASE_URL = "https://spire-codex.com"


def normalize_name(value: str | None) -> str:
    if not value:
        return ""
    text = unicodedata.normalize("NFKC", str(value)).strip().casefold()
    text = re.sub(r"[+＋★☆*]", "", text)
    return re.sub(r"[\s\u3000]+", "", text)


def _items(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        for key in ("cards", "items", "data", "results"):
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
    return []


def _text(item: dict[str, Any], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


class CodexCatalog:
    def __init__(self, items: list[dict[str, Any]], *, lang: str, channel: str, requested_version: str | None, data_version: str | None, source: str):
        self.items = items
        self.lang = lang
        self.channel = channel
        self.requested_version = requested_version
        self.data_version = data_version
        self.source = source
        self.by_name: dict[str, list[dict[str, Any]]] = {}
        for item in items:
            names = [_text(item, ("name", "title", "display_name", "localized_name")), item.get("id")]
            names.extend(value for value in item.get("names", []) if isinstance(value, str))
            for name in names:
                key = normalize_name(name)
                if key:
                    self.by_name.setdefault(key, []).append(item)

    @classmethod
    def load(cls, cache_file: Path, *, base_url: str = DEFAULT_BASE_URL, lang: str = "zhs", channel: str = "stable", version: str | None = None, timeout: int = 30) -> "CodexCatalog":
        if cache_file.exists():
            payload = json.loads(cache_file.read_text(encoding="utf-8"))
            return cls(payload["items"], lang=payload["lang"], channel=payload["channel"], requested_version=payload.get("requested_version"), data_version=payload.get("data_version"), source=payload["source"])
        query_values = {"lang": lang, "channel": channel}
        if version:
            query_values["version"] = version
        source = base_url.rstrip("/") + "/api/cards?" + urllib.parse.urlencode(query_values)
        request = urllib.request.Request(source, headers={"Accept": "application/json"})
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
        items = _items(payload)
        if not items:
            raise RuntimeError("Spire Codex returned no card records")
        data_version = version
        if not data_version and channel == "beta":
            urls = [item.get("image_url") for item in items if isinstance(item.get("image_url"), str)]
            match = next((re.search(r"v\d+(?:\.\d+)+", url) for url in urls), None)
            data_version = match.group(0) if match else None
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(json.dumps({"items": items, "lang": lang, "channel": channel, "requested_version": version, "data_version": data_version, "source": source}, ensure_ascii=False, indent=2), encoding="utf-8")
        return cls(items, lang=lang, channel=channel, requested_version=version, data_version=data_version, source=source)

    def version_status(self, game_patch: str | None) -> str:
        if not game_patch or game_patch == "unknown":
            return "unknown"
        if not self.data_version:
            return "unverified"
        left = game_patch.lower().lstrip("v")
        right = self.data_version.lower().lstrip("v")
        return "verified" if left == right else "mismatch"

    def resolve(self, raw_name: str | None, *, game_patch: str | None) -> dict[str, Any]:
        normalized = normalize_name(raw_name)
        result: dict[str, Any] = {"raw_name": raw_name, "normalized_name": normalized, "match_status": "not_found", "match_method": None, "match_confidence": 0.0, "database": "spire-codex", "database_channel": self.channel, "database_version": self.data_version, "version_status": self.version_status(game_patch)}
        if not normalized:
            return result
        matches = self.by_name.get(normalized, [])
        method = "localized_name"
        confidence = 1.0
        if not matches:
            keys = difflib.get_close_matches(normalized, self.by_name, n=2, cutoff=0.92)
            matches = [item for key in keys for item in self.by_name[key]]
            method = "fuzzy_name"
            confidence = 0.92 if len(matches) == 1 else 0.0
        if len(matches) != 1:
            result["match_status"] = "ambiguous" if matches else "not_found"
            return result
        item = matches[0]
        entity_id = _text(item, ("id", "card_id", "entity_id", "key"))
        if not entity_id:
            return result
        result.update({"entity_id": entity_id, "canonical_name": entity_id, "display_name": _text(item, ("name", "title", "display_name", "localized_name")) or raw_name, "match_status": "matched", "match_method": method, "match_confidence": confidence})
        for key in ("cost", "type", "type_key", "rarity", "rarity_key", "description", "description_raw", "upgrade_description"):
            if key in item:
                result[key] = item[key]
        return result


def enrich_entity(entity: dict[str, Any], catalog: CodexCatalog | None, *, game_patch: str | None) -> dict[str, Any]:
    if catalog is None:
        return entity
    raw_name = entity.get("raw_name", entity.get("name"))
    result = dict(entity)
    match = catalog.resolve(raw_name, game_patch=game_patch)
    result.update(match)
    result["name"] = entity.get("name")
    return result


def enrich_state(state: dict[str, Any], catalog: CodexCatalog | None, *, game_patch: str | None) -> dict[str, Any]:
    if catalog is None:
        return state
    result = dict(state)
    for field in ("hand", "options"):
        values = result.get(field)
        if isinstance(values, list):
            result[field] = [enrich_entity(value, catalog, game_patch=game_patch) if isinstance(value, dict) else value for value in values]
    return result
