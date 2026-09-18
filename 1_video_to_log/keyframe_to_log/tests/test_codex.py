from keyframe_to_log.codex import CodexCatalog, normalize_name


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
