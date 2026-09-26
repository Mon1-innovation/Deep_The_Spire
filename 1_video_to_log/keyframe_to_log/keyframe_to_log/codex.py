from __future__ import annotations

import difflib
import json
import re
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

DEFAULT_BASE_URL = "https://spire-codex.com"
CATALOG_TYPES = ("cards", "monsters", "relics", "potions")
DEFAULT_USER_AGENT = "sts2-keyframe-to-log/0.1 (+https://github.com/ptrlrd/spire-codex)"


def normalize_name(value: str | None) -> str:
    if not value:
        return ""
    text = unicodedata.normalize("NFKC", str(value)).strip().casefold()
    text = re.sub(r"[+＋★☆*]", "", text)
    return re.sub(r"[\s\u3000]+", "", text)


def _items(payload: Any, entity_type: str = "cards") -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        collection_keys = {
            "cards": ("cards",),
            "monsters": ("monsters", "enemies"),
            "relics": ("relics",),
            "potions": ("potions",),
        }
        for key in (*collection_keys.get(entity_type, ()), "items", "data", "results"):
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
            if isinstance(value, dict):
                nested_items = _items(value, entity_type)
                if nested_items:
                    return nested_items
    return []


def _text(item: dict[str, Any], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


class CodexCatalog:
    def __init__(self, items: list[dict[str, Any]], *, lang: str, channel: str, requested_version: str | None, data_version: str | None, source: str, entity_type: str = "cards"):
        if entity_type not in CATALOG_TYPES:
            raise ValueError(f"unsupported Spire Codex entity type: {entity_type}")
        self.items = items
        self.entity_type = entity_type
        self.lang = lang
        self.channel = channel
        self.requested_version = requested_version
        self.data_version = data_version
        self.source = source
        self.by_name: dict[str, list[dict[str, Any]]] = {}
        for item in items:
            names = [_text(item, ("name", "title", "display_name", "localized_name")), _text(item, ("id", "monster_id", "relic_id", "potion_id", "card_id", "entity_id", "key"))]
            names.extend(value for value in item.get("names", []) if isinstance(value, str))
            for name in names:
                key = normalize_name(name)
                if key:
                    self.by_name.setdefault(key, []).append(item)

    @classmethod
    def load(cls, cache_file: Path, *, base_url: str = DEFAULT_BASE_URL, lang: str = "zhs", channel: str = "stable", version: str | None = None, timeout: int = 30, entity_type: str = "cards") -> "CodexCatalog":
        if entity_type not in CATALOG_TYPES:
            raise ValueError(f"unsupported Spire Codex entity type: {entity_type}")
        if cache_file.exists():
            payload = json.loads(cache_file.read_text(encoding="utf-8"))
            cached_entity_type = payload.get("entity_type", "cards")
            if cached_entity_type != entity_type:
                raise RuntimeError(f"Spire Codex cache contains {cached_entity_type}, expected {entity_type}")
            return cls(payload["items"], lang=payload["lang"], channel=payload["channel"], requested_version=payload.get("requested_version"), data_version=payload.get("data_version"), source=payload["source"], entity_type=entity_type)
        query_values = {"lang": lang, "channel": channel}
        if version:
            query_values["version"] = version
        source = base_url.rstrip("/") + f"/api/{entity_type}?" + urllib.parse.urlencode(query_values)
        headers = {
            "Accept": "application/json",
            "Accept-Encoding": "identity",
            "User-Agent": DEFAULT_USER_AGENT,
        }
        request = urllib.request.Request(source, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (urllib.error.HTTPError, urllib.error.URLError):
            if entity_type != "cards" or channel != "stable" or version is not None or base_url.rstrip("/") != DEFAULT_BASE_URL:
                raise
            fallback_source = f"https://raw.githubusercontent.com/ptrlrd/spire-codex/main/data/{lang}/cards.json"
            fallback_request = urllib.request.Request(fallback_source, headers=headers)
            with urllib.request.urlopen(fallback_request, timeout=timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
            source = fallback_source
        items = _items(payload, entity_type)
        if not items:
            raise RuntimeError(f"Spire Codex returned no {entity_type} records")
        data_version = version
        if not data_version and channel == "beta":
            urls = [item.get("image_url") for item in items if isinstance(item.get("image_url"), str)]
            match = next((re.search(r"v\d+(?:\.\d+)+", url) for url in urls), None)
            data_version = match.group(0) if match else None
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(json.dumps({"items": items, "entity_type": entity_type, "lang": lang, "channel": channel, "requested_version": version, "data_version": data_version, "source": source}, ensure_ascii=False, indent=2), encoding="utf-8")
        return cls(items, lang=lang, channel=channel, requested_version=version, data_version=data_version, source=source, entity_type=entity_type)

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
        result: dict[str, Any] = {"raw_name": raw_name, "normalized_name": normalized, "entity_id": None, "canonical_name": None, "display_name": None, "catalog_type": self.entity_type, "match_status": "not_found", "match_method": None, "match_confidence": 0.0, "database": "spire-codex", "database_channel": self.channel, "database_version": self.data_version, "version_status": self.version_status(game_patch)}
        if not normalized:
            result["match_status"] = "unidentified"
            return result
        matches = self.by_name.get(normalized, [])
        method = "localized_name"
        confidence = 1.0
        if not matches:
            keys = difflib.get_close_matches(normalized, self.by_name, n=2, cutoff=0.92)
            matches = [item for key in keys for item in self.by_name[key]]
            method = "fuzzy_name"
        matches_by_id = {_text(item, ("id", "monster_id", "relic_id", "potion_id", "card_id", "entity_id", "key")) or str(index): item for index, item in enumerate(matches)}
        matches = list(matches_by_id.values())
        if len(matches) != 1:
            result["match_status"] = "ambiguous" if matches else "not_found"
            return result
        confidence = 0.92 if method == "fuzzy_name" else 1.0
        item = matches[0]
        entity_id = _text(item, ("id", "monster_id", "relic_id", "potion_id", "card_id", "entity_id", "key"))
        if not entity_id:
            return result
        result.update({"entity_id": entity_id, "canonical_name": entity_id, "display_name": _text(item, ("name", "title", "display_name", "localized_name")) or raw_name, "match_status": "matched", "match_method": method, "match_confidence": confidence})
        for key in ("cost", "type", "type_key", "rarity", "rarity_key", "description", "description_raw", "upgrade_description", "pool", "pool_key"):
            if key in item:
                result[key] = item[key]
        return result


def enrich_entity(entity: dict[str, Any], catalog: CodexCatalog | None, *, game_patch: str | None, catalog_type: str | None = None) -> dict[str, Any]:
    raw_name = entity.get("raw_name", entity.get("name"))
    result = dict(entity)
    result["raw_name"] = raw_name
    if catalog is None:
        result["entity_id"] = None
        result["catalog_type"] = catalog_type
        result["match_status"] = "unidentified" if not raw_name else "catalog_unavailable"
        result["match_method"] = None
        result["match_confidence"] = 0.0
        return result
    match = catalog.resolve(raw_name, game_patch=game_patch)
    result.update(match)
    result["name"] = entity.get("name")
    result["entity_id"] = match.get("entity_id")
    return result


def enrich_state(state: dict[str, Any], catalog: CodexCatalog | None = None, *, game_patch: str | None, catalogs: dict[str, CodexCatalog] | None = None, page_type: str | None = None) -> dict[str, Any]:
    active_catalogs = dict(catalogs or {})
    if catalog is not None:
        active_catalogs.setdefault("cards", catalog)
    result = dict(state)
    field_catalogs = {"hand": "cards", "enemies": "monsters", "relics": "relics", "potions": "potions"}
    for field, catalog_type in field_catalogs.items():
        values = result.get(field)
        if isinstance(values, list):
            result[field] = [enrich_entity(value, active_catalogs.get(catalog_type), game_patch=game_patch, catalog_type=catalog_type) if isinstance(value, dict) else value for value in values]
    option_catalog = {
        "card_reward": "cards",
        "card_select": "cards",
        "relic_reward": "relics",
        "boss_relic": "relics",
        "potion_reward": "potions",
    }.get(page_type, "cards")
    values = result.get("options")
    if isinstance(values, list) and option_catalog:
        result["options"] = [enrich_entity(value, active_catalogs.get(option_catalog), game_patch=game_patch, catalog_type=option_catalog) if isinstance(value, dict) else value for value in values]
    elif isinstance(values, list) and page_type == "shop":
        result["options"] = [_enrich_shop_option(value, active_catalogs, game_patch=game_patch) if isinstance(value, dict) else value for value in values]
    return result


def _enrich_shop_option(entity: dict[str, Any], catalogs: dict[str, CodexCatalog], *, game_patch: str | None) -> dict[str, Any]:
    requested_type = entity.get("entity_type")
    if requested_type in catalogs:
        return enrich_entity(entity, catalogs[requested_type], game_patch=game_patch, catalog_type=requested_type)
    raw_name = entity.get("raw_name", entity.get("name"))
    matches = [(catalog_type, catalog.resolve(raw_name, game_patch=game_patch)) for catalog_type, catalog in catalogs.items() if catalog_type in {"cards", "relics", "potions"}]
    found = [(catalog_type, match) for catalog_type, match in matches if match["match_status"] == "matched"]
    if len(found) == 1:
        catalog_type, _ = found[0]
        return enrich_entity(entity, catalogs[catalog_type], game_patch=game_patch, catalog_type=catalog_type)
    if len(found) > 1:
        result = dict(entity)
        result["raw_name"] = raw_name
        result["entity_id"] = None
        result["match_status"] = "ambiguous"
        result["catalog_candidates"] = [{"catalog_type": catalog_type, "entity_id": match["entity_id"]} for catalog_type, match in found]
        return result
    return enrich_entity(entity, None, game_patch=game_patch, catalog_type=requested_type)
