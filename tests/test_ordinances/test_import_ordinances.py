"""Tests for ordinances/import_ordinances.py."""

from ordinances import import_ordinances
from .test_converter import SAMPLE_XML


def test_import_from_cache_writes_markdown(tmp_path, monkeypatch):
    monkeypatch.setattr(import_ordinances.cache, "list_cached_ids", lambda: ["2000111"])
    monkeypatch.setattr(
        import_ordinances.cache,
        "get_detail",
        lambda ordinance_id, **kwargs: SAMPLE_XML.encode("utf-8"),
    )

    counters = import_ordinances.import_from_cache(tmp_path)

    assert counters["written"] == 1
    assert (tmp_path / "서울특별시/_본청/조례/서울특별시 테스트 조례/본문.md").exists()


def test_import_from_cache_skips_head_scan_when_no_serials_need_import(tmp_path, monkeypatch):
    monkeypatch.setattr(
        import_ordinances,
        "_current_paths_by_identity",
        lambda repo: (_ for _ in ()).throw(AssertionError("HEAD scan must not run")),
    )

    counters = import_ordinances.import_from_cache(tmp_path, commit=True, serials=[])

    assert counters == {"written": 0, "deleted": 0, "committed": 0, "skipped": 0, "errors": 0}


def test_import_from_cache_commits_in_date_order(tmp_path, monkeypatch):
    old_xml = SAMPLE_XML.replace("<자치법규ID>2000111</자치법규ID>", "<자치법규ID>200</자치법규ID>").replace(
        "<자치법규일련번호>12345</자치법규일련번호>",
        "<자치법규일련번호>2000</자치법규일련번호>",
    ).replace(
        "<공포일자>20210930</공포일자>",
        "<공포일자>20200101</공포일자>",
    )
    new_xml = SAMPLE_XML.replace("<자치법규ID>2000111</자치법규ID>", "<자치법규ID>100</자치법규ID>").replace(
        "<자치법규일련번호>12345</자치법규일련번호>",
        "<자치법규일련번호>1000</자치법규일련번호>",
    ).replace(
        "<공포일자>20210930</공포일자>",
        "<공포일자>20210101</공포일자>",
    )
    details = {"1000": new_xml.encode("utf-8"), "2000": old_xml.encode("utf-8")}
    commits = []
    monkeypatch.setattr(import_ordinances.cache, "list_cached_ids", lambda: ["1000", "2000"])
    monkeypatch.setattr(import_ordinances.cache, "get_detail", lambda serial, **kwargs: details[serial])
    monkeypatch.setattr(
        import_ordinances,
        "commit_ordinance",
        lambda repo, path, msg, date, ordinance_id, serial, **kwargs: commits.append(serial) or True,
    )

    counters = import_ordinances.import_from_cache(tmp_path, commit=True)

    assert counters["committed"] == 2
    assert commits == ["2000", "1000"]


def test_import_from_cache_removes_stale_path_when_ordinance_name_changes(tmp_path, monkeypatch):
    old_xml = SAMPLE_XML.replace("서울특별시 테스트 조례", "이전 조례").replace(
        "<자치법규일련번호>12345</자치법규일련번호>",
        "<자치법규일련번호>1</자치법규일련번호>",
    ).replace(
        "<공포일자>20210930</공포일자>",
        "<공포일자>20240101</공포일자>",
    )
    new_xml = SAMPLE_XML.replace("서울특별시 테스트 조례", "새 조례").replace(
        "<자치법규일련번호>12345</자치법규일련번호>",
        "<자치법규일련번호>2</자치법규일련번호>",
    ).replace(
        "<공포일자>20210930</공포일자>",
        "<공포일자>20240201</공포일자>",
    )
    details = {"1": old_xml.encode("utf-8"), "2": new_xml.encode("utf-8")}
    monkeypatch.setattr(import_ordinances.cache, "list_cached_ids", lambda: ["2", "1"])
    monkeypatch.setattr(import_ordinances.cache, "get_detail", lambda serial, **kwargs: details[serial])

    counters = import_ordinances.import_from_cache(tmp_path)

    assert counters["written"] == 2
    assert (tmp_path / "서울특별시/_본청/조례/새 조례/본문.md").exists()
    assert not (tmp_path / "서울특별시/_본청/조례/이전 조례/본문.md").exists()


def test_import_from_cache_commits_stale_path_deletion(tmp_path, monkeypatch):
    old_xml = SAMPLE_XML.replace("서울특별시 테스트 조례", "이전 조례").replace(
        "<자치법규일련번호>12345</자치법규일련번호>",
        "<자치법규일련번호>1</자치법규일련번호>",
    ).replace(
        "<공포일자>20210930</공포일자>",
        "<공포일자>20240101</공포일자>",
    )
    new_xml = SAMPLE_XML.replace("서울특별시 테스트 조례", "새 조례").replace(
        "<자치법규일련번호>12345</자치법규일련번호>",
        "<자치법규일련번호>2</자치법규일련번호>",
    ).replace(
        "<공포일자>20210930</공포일자>",
        "<공포일자>20240201</공포일자>",
    )
    details = {"1": old_xml.encode("utf-8"), "2": new_xml.encode("utf-8")}
    commits = []
    monkeypatch.setattr(import_ordinances.cache, "list_cached_ids", lambda: ["1", "2"])
    monkeypatch.setattr(import_ordinances.cache, "get_detail", lambda serial, **kwargs: details[serial])
    monkeypatch.setattr(
        import_ordinances,
        "commit_ordinance",
        lambda repo, path, msg, date, ordinance_id, serial, **kwargs: commits.append(
            (path, kwargs.get("stale_paths", []))
        )
        or True,
    )

    counters = import_ordinances.import_from_cache(tmp_path, commit=True)

    assert counters["committed"] == 2
    assert commits[-1] == (
        "서울특별시/_본청/조례/새 조례/본문.md",
        ["서울특별시/_본청/조례/이전 조례/본문.md"],
    )


def test_import_from_cache_deletes_repealed_ordinance_from_head(tmp_path, monkeypatch):
    active_xml = SAMPLE_XML.replace("서울특별시 테스트 조례", "폐지 대상 조례").replace(
        "<자치법규일련번호>12345</자치법규일련번호>",
        "<자치법규일련번호>1</자치법규일련번호>",
    ).replace(
        "<공포일자>20210930</공포일자>",
        "<공포일자>20200101</공포일자>",
    ).replace(
        "<제개정정보>일부개정</제개정정보>",
        "<제개정정보>제정</제개정정보>",
    )
    repeal_xml = SAMPLE_XML.replace("서울특별시 테스트 조례", "폐지 대상 조례").replace(
        "<자치법규일련번호>12345</자치법규일련번호>",
        "<자치법규일련번호>2</자치법규일련번호>",
    ).replace(
        "<공포일자>20210930</공포일자>",
        "<공포일자>20210101</공포일자>",
    ).replace(
        "<제개정정보>일부개정</제개정정보>",
        "<제개정정보>폐지</제개정정보>",
    )
    details = {"1": active_xml.encode("utf-8"), "2": repeal_xml.encode("utf-8")}
    monkeypatch.setattr(import_ordinances.cache, "list_cached_ids", lambda: ["1", "2"])
    monkeypatch.setattr(import_ordinances.cache, "get_detail", lambda serial, **kwargs: details[serial])

    counters = import_ordinances.import_from_cache(tmp_path)

    assert counters["written"] == 1
    assert counters["deleted"] == 1
    assert not (tmp_path / "서울특별시/_본청/조례/폐지 대상 조례/본문.md").exists()


def test_import_from_cache_commits_repeal_without_cached_predecessor(tmp_path, monkeypatch):
    repeal_xml = SAMPLE_XML.replace(
        "<제개정정보>일부개정</제개정정보>",
        "<제개정정보>폐지</제개정정보>",
    )
    commits = []
    monkeypatch.setattr(import_ordinances.cache, "list_cached_ids", lambda: ["12345"])
    monkeypatch.setattr(
        import_ordinances.cache,
        "get_detail",
        lambda serial, **kwargs: repeal_xml.encode("utf-8"),
    )
    monkeypatch.setattr(
        import_ordinances,
        "commit_ordinance_deletion",
        lambda repo, path, msg, date, serial, **kwargs: commits.append((path, serial)) or True,
    )

    counters = import_ordinances.import_from_cache(tmp_path, commit=True)

    assert counters["deleted"] == 0
    assert counters["committed"] == 1
    assert commits == [(None, "12345")]


def test_import_from_cache_deduplicates_legacy_id_and_history_serial(tmp_path, monkeypatch):
    raw = SAMPLE_XML.encode("utf-8")
    monkeypatch.setattr(
        import_ordinances.cache,
        "list_cached_ids",
        lambda: ["2000111", "history/12345"],
    )
    monkeypatch.setattr(import_ordinances.cache, "get_detail", lambda cache_key, **kwargs: raw)

    counters = import_ordinances.import_from_cache(tmp_path)

    assert counters["written"] == 1


def test_import_from_cache_assigns_collision_paths_in_serial_order(tmp_path, monkeypatch):
    first = SAMPLE_XML.replace(
        "<자치법규ID>2000111</자치법규ID>",
        "<자치법규ID>1</자치법규ID>",
    ).replace(
        "<자치법규일련번호>12345</자치법규일련번호>",
        "<자치법규일련번호>1</자치법규일련번호>",
    ).replace("<공포번호>7825</공포번호>", "<공포번호>101</공포번호>")
    second = SAMPLE_XML.replace(
        "<자치법규ID>2000111</자치법규ID>",
        "<자치법규ID>2</자치법규ID>",
    ).replace(
        "<자치법규일련번호>12345</자치법규일련번호>",
        "<자치법규일련번호>2</자치법규일련번호>",
    ).replace("<공포번호>7825</공포번호>", "<공포번호>102</공포번호>")
    details = {"1": first.encode(), "2": second.encode()}
    monkeypatch.setattr(import_ordinances.cache, "list_cached_ids", lambda: ["2", "1"])
    monkeypatch.setattr(import_ordinances.cache, "get_detail", lambda serial, **kwargs: details[serial])

    counters = import_ordinances.import_from_cache(tmp_path)

    clean_path = tmp_path / "서울특별시/_본청/조례/서울특별시 테스트 조례/본문.md"
    collision_path = tmp_path / "서울특별시/_본청/조례/서울특별시 테스트 조례_102/본문.md"
    assert counters["written"] == 2
    assert "자치법규ID: '1'" in clean_path.read_text(encoding="utf-8")
    assert "자치법규ID: '2'" in collision_path.read_text(encoding="utf-8")
