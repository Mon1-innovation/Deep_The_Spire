from __future__ import annotations
import hashlib
import json
from pathlib import Path
from typing import Any
from .frames import discover_keyframes
from .models import Keyframe, Observation
from .provider import Provider
from .codex import CodexCatalog, enrich_state
from .validate import validate_observation

LOG_SCHEMA_VERSION = "2.0"
OBSERVATION_SCHEMA_VERSION = "7"
MAP_SCHEMA_VERSION = "2"
OBSERVATION_CACHE_VERSION = "observation-v8"

def _cache_key(frame: Keyframe, prompt_version: str, model_version: str) -> str:
    digest = hashlib.sha256(Path(frame.path).read_bytes()).hexdigest()
    return hashlib.sha256(f"{digest}:{prompt_version}:{model_version}".encode()).hexdigest()

def _event(event_id: int, timestamp: float, event_type: str, **fields: Any) -> dict[str, Any]:
    return {"id": event_id, "t": timestamp, "type": event_type, **fields}

def _normalize_map_state(state: dict[str, Any]) -> dict[str, Any]:
    map_state = state.get("map")
    if not isinstance(map_state, dict):
        return state
    raw_nodes = map_state.get("nodes", [])
    raw_paths = map_state.get("paths", map_state.get("edges", []))
    nodes_by_id: dict[str, dict[str, Any]] = {}
    for raw_node in raw_nodes if isinstance(raw_nodes, list) else []:
        if not isinstance(raw_node, dict):
            continue
        node_id = raw_node.get("id") or raw_node.get("node_id")
        if node_id is None:
            continue
        node_id = str(node_id)
        position = raw_node.get("position")
        if not isinstance(position, dict):
            position = {"x": raw_node.get("x"), "y": raw_node.get("y")}
        status = raw_node.get("status")
        if status is None:
            if raw_node.get("current") is True:
                status = "current"
            elif raw_node.get("visited") is True:
                status = "visited"
            else:
                status = "unvisited"
        nodes_by_id[node_id] = {
            "id": node_id,
            "level": raw_node.get("level", raw_node.get("row")),
            "type": raw_node.get("type", "unknown"),
            "status": status,
            "position": {"x": position.get("x"), "y": position.get("y")},
            "next_nodes": list(raw_node.get("next_nodes", [])) if isinstance(raw_node.get("next_nodes", []), list) else [],
            "previous_nodes": list(raw_node.get("previous_nodes", [])) if isinstance(raw_node.get("previous_nodes", []), list) else [],
        }
    paths: list[dict[str, Any]] = []
    for raw_path in raw_paths if isinstance(raw_paths, list) else []:
        if not isinstance(raw_path, dict):
            continue
        source = raw_path.get("from", raw_path.get("source"))
        target = raw_path.get("to", raw_path.get("target"))
        if source is None or target is None:
            continue
        source, target = str(source), str(target)
        paths.append({"from": source, "to": target, "relation": raw_path.get("relation", "next_room")})
        if source in nodes_by_id and target not in nodes_by_id[source]["next_nodes"]:
            nodes_by_id[source]["next_nodes"].append(target)
        if target in nodes_by_id and source not in nodes_by_id[target]["previous_nodes"]:
            nodes_by_id[target]["previous_nodes"].append(source)
    current_ids = [node_id for node_id, node in nodes_by_id.items() if node["status"] == "current"]
    map_state["current_node_id"] = map_state.get("current_node_id") or (current_ids[0] if len(current_ids) == 1 else None)
    map_state["nodes"] = list(nodes_by_id.values())
    map_state["paths"] = paths
    map_state.pop("edges", None)
    return state

def _build_events(observations: list[Observation]) -> list[dict[str, Any]]:
    events = [{"id": 0, "by": "world", "type": "info", "message": "Run started."}]
    previous_page = None
    for observation in observations:
        if observation.page_type != previous_page:
            events.append({"id": len(events), "by": "world", "type": "response", "t": observation.keyframe.timestamp, "info": {"page_type": observation.page_type, "confidence": observation.confidence, "frame": observation.keyframe.path}})
            previous_page = observation.page_type
        if observation.action:
            events.append({"id": len(events), "by": "player", "type": "action", "t": observation.keyframe.timestamp, "action": observation.action})
        events.append({"id": len(events), "by": "world", "type": "response", "t": observation.keyframe.timestamp, "info": {"page_type": observation.page_type, "state": observation.state, "confidence": observation.confidence, "evidence": observation.evidence, "frame": observation.keyframe.path}})
    return events

def _catalog_provenance(catalog: CodexCatalog) -> dict[str, Any]:
    return {"source": catalog.source, "channel": catalog.channel, "language": catalog.lang, "requested_version": catalog.requested_version, "data_version": catalog.data_version, "entity_type": catalog.entity_type}


def _build_result(run_id: str, patch: str | None, provider: Provider, frames: list[Keyframe], observations: list[Observation], status: str, catalog: CodexCatalog | None = None, catalogs: dict[str, CodexCatalog] | None = None) -> dict[str, Any]:
    active_catalogs = dict(catalogs or {})
    if catalog is not None:
        active_catalogs.setdefault("cards", catalog)
    for observation in observations:
        observation.state = _normalize_map_state(enrich_state(observation.state, catalog, game_patch=patch, catalogs=active_catalogs, page_type=observation.page_type))
    return {
        "run_id": run_id,
        "game": "sts2",
        "patch": patch,
        "status": status,
        "events": _build_events(observations),
        "observations": [dict(observation.as_dict(), state=_normalize_map_state(observation.state)) for observation in observations],
        "provenance": {
            "extractor": provider.cache_identity,
            "codex": (_catalog_provenance(active_catalogs["cards"]) if "cards" in active_catalogs else {"enabled": False}),
            "codex_catalogs": {entity_type: _catalog_provenance(value) for entity_type, value in active_catalogs.items()},
            "keyframe_count": len(frames),
            "processed_keyframe_count": len(observations),
            "schema_version": LOG_SCHEMA_VERSION,
            "observation_schema_version": OBSERVATION_SCHEMA_VERSION,
            "map_schema_version": MAP_SCHEMA_VERSION,
            "game_patch": patch or "unknown",
        },
    }

def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=4), encoding="utf-8")

def _write_jsonl(path: Path, result: dict[str, Any]) -> None:
    jsonl_path = path if path.suffix.lower() == ".jsonl" else path.with_suffix(".jsonl")
    jsonl_path.parent.mkdir(parents=True, exist_ok=True)
    with jsonl_path.open("w", encoding="utf-8", newline="\n") as stream:
        for event in result["events"]:
            stream.write(json.dumps(event, ensure_ascii=False) + "\n")

def _write_markdown(path: Path, result: dict[str, Any]) -> None:
    lines = [
        f"# 对局日志：{result['run_id']}",
        "",
        f"- 处理状态：{result['status']}",
        f"- 游戏版本：{result['patch'] or 'unknown'}",
        f"- 识别模型：{result['provenance']['extractor']}",
        f"- 关键帧：{result['provenance']['processed_keyframe_count']} / {result['provenance']['keyframe_count']}",
        "",
        "## 关键帧观测",
    ]
    if result.get("error"):
        lines.extend(["", "## 处理错误", "", f"- 出错关键帧：`{result['error']['frame']}`", f"- 错误信息：`{result['error']['message']}`"])
    for index, observation in enumerate(result["observations"], start=1):
        lines.extend(["", f"### {index}. {Path(observation['path']).name}", "", f"- 时间：`{observation['t']}` 秒", f"- 页面：`{observation['page_type']}`", f"- 置信度：`{observation['confidence']}`", f"- 动作：`{json.dumps(observation['action'], ensure_ascii=False)}`", "", "#### 可见状态", "", "```json", json.dumps(observation["state"], ensure_ascii=False, indent=2), "```"])
        if observation["evidence"]:
            lines.extend(["", "#### 识别依据", ""])
            lines.extend(f"- {item}" for item in observation["evidence"])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
def convert_keyframes(input_dir: str | Path, output_path: str | Path, provider: Provider, run_id: str = "run-unknown", patch: str | None = None, cache_dir: str | Path | None = None, catalog: CodexCatalog | None = None, catalogs: dict[str, CodexCatalog] | None = None) -> dict[str, Any]:
    frames = discover_keyframes(input_dir)
    if not frames:
        raise ValueError(f"no supported keyframe images found in {input_dir}")
    cache = Path(cache_dir) if cache_dir else Path(output_path).with_suffix(".cache")
    cache.mkdir(parents=True, exist_ok=True)
    output = Path(output_path)
    observations: list[Observation] = []
    for frame in frames:
        try:
            cache_file = cache / f"{_cache_key(frame, OBSERVATION_CACHE_VERSION, provider.cache_identity)}.json"
            value = json.loads(cache_file.read_text(encoding="utf-8")) if cache_file.exists() else provider.observe(frame)
            if not cache_file.exists():
                cache_file.write_text(json.dumps(value, ensure_ascii=False, indent=4), encoding="utf-8")
            value["keyframe"] = frame
            observations.append(validate_observation(value))
            processing = _build_result(run_id, patch, provider, frames, observations, "processing", catalog, catalogs)
            _write_json(output, processing)
            _write_jsonl(output, processing)
        except Exception as error:
            result = _build_result(run_id, patch, provider, frames, observations, "failed", catalog, catalogs)
            result["error"] = {"frame": frame.path, "message": str(error)}
            _write_json(output, result)
            _write_jsonl(output, result)
            _write_markdown(output.with_suffix(".md"), result)
            raise
    result = _build_result(run_id, patch, provider, frames, observations, "complete", catalog, catalogs)
    _write_json(output, result)
    _write_jsonl(output, result)
    _write_markdown(output.with_suffix(".md"), result)
    return result


