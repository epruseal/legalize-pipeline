"""Tests for ordinances/update.py."""

from ordinances import update


def test_run_fetches_then_imports(tmp_path, monkeypatch):
    class Counter:
        def snapshot(self):
            return (1, 2, 3)

    calls = []
    monkeypatch.setattr(
        update,
        "fetch_all_current",
        lambda types, **kwargs: calls.append(("fetch", types, kwargs))
        or [{"자치법규ID": "1", "자치법규일련번호": "current", "자치법규명": "현재 조례", "공포일자": "20260101"}],
    )
    monkeypatch.setattr(
        update,
        "fetch_history_for_entries",
        lambda entries, types: calls.append(("history", entries, types))
        or [
            {"자치법규ID": "1", "자치법규일련번호": "old", "자치법규명": "이전 조례", "공포일자": "20200101"},
            {"자치법규ID": "1", "자치법규일련번호": "current", "자치법규명": "현재 조례", "공포일자": "20260101"},
        ],
    )
    monkeypatch.setattr(update, "fetch_details", lambda entries, workers, limit=None: calls.append(("details", entries, workers, limit)) or Counter())
    monkeypatch.setattr(update, "_committed_serials", lambda repo: set())
    monkeypatch.setattr(update, "_committed_identities", lambda repo: set())
    monkeypatch.setattr(
        update,
        "import_from_cache",
        lambda repo, limit, commit, serials, skip_dedup: calls.append(("import", repo, limit, commit, serials, skip_dedup))
        or {"written": 4, "committed": 5, "skipped": 6, "errors": 7},
    )

    monkeypatch.setattr(update, "_date_range", lambda days: "20260101~20260115")
    stats = update.run(repo=tmp_path, limit=10, workers=2, commit=True, types=["조례"], org="11", sborg="110")

    assert stats == {
        "cached": 1,
        "fetched": 2,
        "fetch_errors": 3,
        "written": 4,
        "committed": 5,
        "skipped": 6,
        "errors": 7,
    }
    assert calls[0] == ("fetch", ["조례"], {"org": "11", "sborg": "110", "max_entries": 10, "date_range": "20260101~20260115"})
    assert calls[2][0] == "details"
    assert [entry["자치법규일련번호"] for entry in calls[2][1]] == ["old", "current"]
    assert calls[3] == ("import", tmp_path, None, True, ["old", "current"], False)


def test_run_imports_only_uncommitted_serials_for_existing_identity(tmp_path, monkeypatch):
    class Counter:
        def snapshot(self):
            return (2, 0, 0)

    imported = []
    monkeypatch.setattr(
        update,
        "fetch_all_current",
        lambda types, **kwargs: [
            {"자치법규ID": "1", "자치법규일련번호": "new", "자치법규명": "현재 조례", "공포일자": "20260102"},
        ],
    )
    monkeypatch.setattr(
        update,
        "fetch_history_for_entries",
        lambda entries, types: [
            {"자치법규ID": "1", "자치법규일련번호": "old-missing", "자치법규명": "이전 조례", "공포일자": "20200101"},
            {"자치법규ID": "1", "자치법규일련번호": "new", "자치법규명": "현재 조례", "공포일자": "20260102"},
        ],
    )
    monkeypatch.setattr(update, "fetch_details", lambda entries, workers, limit=None: Counter())
    monkeypatch.setattr(update, "_committed_serials", lambda repo: {"already"})
    monkeypatch.setattr(update, "_committed_identities", lambda repo: {"1"})
    monkeypatch.setattr(
        update,
        "import_from_cache",
        lambda repo, limit, commit, serials, skip_dedup: imported.extend(serials)
        or {"written": 1, "committed": 1, "skipped": 0, "errors": 0},
    )
    monkeypatch.setattr(update, "_date_range", lambda days: "20260101~20260115")

    update.run(repo=tmp_path, commit=True)

    assert imported == ["new"]
