from keyframe_to_log.codex import CodexCatalog, enrich_state, normalize_name


def test_normalize_name_removes_upgrade_markers():
    assert normalize_name(" 防御+ ") == "防御"


def test_codex_matches_localized_name_and_records_version():
    catalog = CodexCatalog(
        [{"id": "DEFEND", "name": "防御", "cost": 1, "type": "技能", "rarity": "基础", "description": "获得格挡。"}],
        lang="zhs", channel="beta", requested_version="v0.111.0", data_version="v0.111.0", source="test",
    )
    result = catalog.resolve("防御+", game_patch="0.111.0")
    assert result["entity_id"] == "DEFEND"
    assert result["match_status"] == "matched"
    assert result["version_status"] == "verified"
    assert result["description"] == "获得格挡。"


def test_codex_marks_version_mismatch_without_hiding_match():
    catalog = CodexCatalog(
        [{"id": "DEFEND", "name": "防御"}],
        lang="zhs", channel="stable", requested_version=None, data_version=None, source="test",
    )
    result = catalog.resolve("防御", game_patch="0.111.0")
    assert result["entity_id"] == "DEFEND"
    assert result["version_status"] == "unverified"


def test_codex_resolves_monsters_relics_and_potions_with_separate_catalogs():
    catalogs = {
        "monsters": CodexCatalog(
            [{"monster_id": "PETRIFIED_CULTIST", "name": "\u9499\u5316\u90aa\u6559\u5f92"}],
            lang="zhs", channel="stable", requested_version=None, data_version=None, source="test", entity_type="monsters",
        ),
        "relics": CodexCatalog(
            [{"relic_id": "OLD_COIN", "name": "\u53e4\u94b1\u5e01", "rarity": "\u7279\u6b8a"}],
            lang="zhs", channel="stable", requested_version=None, data_version=None, source="test", entity_type="relics",
        ),
        "potions": CodexCatalog(
            [{"potion_id": "FIRE_POTION", "name": "\u706b\u7130\u836f\u6c34", "description": "\u5bf9\u654c\u4eba\u9020\u6210\u4f24\u5bb3"}],
            lang="zhs", channel="stable", requested_version=None, data_version=None, source="test", entity_type="potions",
        ),
    }

    state = enrich_state(
        {
            "enemies": [{"name": "\u9499\u5316\u90aa\u6559\u5f92", "hp": 39}],
            "relics": [{"name": "\u53e4\u94b1\u5e01"}],
            "potions": [{"name": "\u706b\u7130\u836f\u6c34"}],
        },
        game_patch="0.111.0",
        catalogs=catalogs,
        page_type="combat",
    )

    assert state["enemies"][0]["entity_id"] == "PETRIFIED_CULTIST"
    assert state["enemies"][0]["catalog_type"] == "monsters"
    assert state["relics"][0]["entity_id"] == "OLD_COIN"
    assert state["potions"][0]["entity_id"] == "FIRE_POTION"
    assert state["potions"][0]["description"] == "\u5bf9\u654c\u4eba\u9020\u6210\u4f24\u5bb3"


def test_codex_load_uses_entity_specific_api_endpoint(tmp_path, monkeypatch):
    import io
    import json
    from keyframe_to_log.codex import CodexCatalog

    requested_urls = []

    def fake_urlopen(request, timeout):
        requested_urls.append(request.full_url)
        return io.BytesIO(json.dumps({"monsters": [{"id": "CULTIST", "name": "Cultist"}]}).encode("utf-8"))

    monkeypatch.setattr("keyframe_to_log.codex.urllib.request.urlopen", fake_urlopen)
    catalog = CodexCatalog.load(tmp_path / "monsters.json", base_url="https://example.invalid", entity_type="monsters")

    assert "/api/monsters?" in requested_urls[0]
    assert catalog.entity_type == "monsters"
    assert catalog.resolve("Cultist", game_patch="0.111.0")["entity_id"] == "CULTIST"


def test_enrich_state_never_keeps_model_generated_entity_ids():
    state = enrich_state(
        {
            "enemies": [{"name": "Cultist", "entity_id": "UNTRUSTED_ID"}],
            "relics": [{"name": "Old Coin", "entity_id": "UNTRUSTED_ID"}],
            "potions": [{"name": None, "entity_id": "UNTRUSTED_ID"}],
        },
        game_patch=None,
        catalogs={},
        page_type="combat",
    )

    assert state["enemies"][0]["entity_id"] is None
    assert state["enemies"][0]["raw_name"] == "Cultist"
    assert state["relics"][0]["entity_id"] is None
    assert state["relics"][0]["match_status"] == "catalog_unavailable"
    assert state["potions"][0]["entity_id"] is None
    assert state["potions"][0]["match_status"] == "unidentified"
