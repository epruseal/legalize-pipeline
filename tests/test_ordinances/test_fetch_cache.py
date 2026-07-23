"""Tests for ordinances/fetch_cache.py."""

import pytest

from ordinances import fetch_cache


@pytest.fixture(autouse=True)
def _no_saved_crawl_index(monkeypatch):
    """Force the crawl path.

    ``_crawl_search`` short-circuits on a saved crawl index when no date_range
    is given. Without this the tests read whatever ``.ordinance-index.jsonl``
    the real CACHE_ROOT holds (860k live entries) — or, in a clean cache, the
    one an earlier test in the same session just wrote.
    """
    monkeypatch.setattr(fetch_cache.checkpoint, "load_crawl_index", lambda *a, **kw: None)
    monkeypatch.setattr(fetch_cache.checkpoint, "save_crawl_index", lambda *a, **kw: None)


def test_fetch_all_current_pages_until_total(monkeypatch):
    calls = []

    def fake_search_ordinances(page, display, org, sborg, date_range, nw):
        calls.append((page, display, org, sborg, date_range, nw))
        return {"totalCnt": 101, "ordinances": [{"자치법규ID": str(page), "자치법규종류": "조례"}]}

    monkeypatch.setattr(fetch_cache, "search_ordinances", fake_search_ordinances)
    monkeypatch.setattr(fetch_cache, "record_requests", lambda count, corpus: None)

    entries = fetch_cache.fetch_all_current(["조례"], org="6110000", display=100)
    assert entries == [{"자치법규ID": "1", "자치법규종류": "조례"}, {"자치법규ID": "2", "자치법규종류": "조례"}]
    assert calls == [(1, 100, "6110000", "", "", "1"), (2, 100, "6110000", "", "", "1")]


def test_fetch_version_index_collects_revisions_and_unions_current(monkeypatch):
    pages = {
        "2": {"totalCnt": 1, "ordinances": [
            {"자치법규ID": "10", "자치법규일련번호": "100", "자치법규종류": "조례"},
            {"자치법규ID": "10", "자치법규일련번호": "101", "자치법규종류": "조례"},
        ]},
        "1": {"totalCnt": 1, "ordinances": [
            {"자치법규ID": "10", "자치법규일련번호": "101", "자치법규종류": "조례"},  # already seen via nw=2
            {"자치법규ID": "10", "자치법규일련번호": "102", "자치법규종류": "조례"},  # current-only MST
        ]},
    }

    def fake_search_ordinances(page, display, org, sborg, date_range, nw):
        return pages[nw]

    monkeypatch.setattr(fetch_cache, "search_ordinances", fake_search_ordinances)
    monkeypatch.setattr(fetch_cache, "record_requests", lambda count, corpus: None)

    entries = fetch_cache.fetch_version_index(["조례"])
    msts = [e["자치법규일련번호"] for e in entries]
    assert msts == ["100", "101", "102"]


def test_fetch_all_current_ignores_stale_page_checkpoint(monkeypatch):
    calls = []

    def fake_search_ordinances(page, display, org, sborg, date_range, nw):
        calls.append(page)
        return {"totalCnt": 1, "ordinances": [{"자치법규ID": "fresh", "자치법규종류": "조례"}]}

    monkeypatch.setattr(fetch_cache.checkpoint, "is_page_processed", lambda ordinance_type, page, org, sborg: True)
    monkeypatch.setattr(fetch_cache, "search_ordinances", fake_search_ordinances)
    monkeypatch.setattr(fetch_cache, "record_requests", lambda count, corpus: None)

    assert fetch_cache.fetch_all_current(["조례"]) == [{"자치법규ID": "fresh", "자치법규종류": "조례"}]
    assert calls == [1]


def test_fetch_all_current_filters_date_range(monkeypatch):
    def fake_search_ordinances(page, display, org, sborg, date_range, nw):
        return {
            "totalCnt": 1,
            "ordinances": [
                {"자치법규ID": "old", "자치법규종류": "조례", "공포일자": "20260430"},
                {"자치법규ID": "new", "자치법규종류": "조례", "공포일자": "2026-05-01"},
            ],
        }

    monkeypatch.setattr(fetch_cache, "search_ordinances", fake_search_ordinances)
    monkeypatch.setattr(fetch_cache, "record_requests", lambda count, corpus: None)

    assert fetch_cache.fetch_all_current(["조례"], date_range="20260501~20260511") == [
        {"자치법규ID": "new", "자치법규종류": "조례", "공포일자": "2026-05-01"}
    ]


def test_fetch_details_deduplicates_by_mst(monkeypatch):
    fetched = []

    monkeypatch.setattr(fetch_cache.cache, "get_detail", lambda key: None)
    monkeypatch.setattr(
        fetch_cache,
        "get_ordinance_detail",
        lambda ordinance_id, mst="": fetched.append((ordinance_id, mst)),
    )
    monkeypatch.setattr(fetch_cache.checkpoint, "mark_detail_processed", lambda mst: None)
    monkeypatch.setattr(fetch_cache, "record_requests", lambda count, corpus: None)

    counter = fetch_cache.fetch_details(
        [
            {"자치법규ID": "1", "자치법규일련번호": "mst-1"},
            {"자치법규ID": "1", "자치법규일련번호": "mst-1"},  # same MST → deduped
            {"자치법규ID": "1", "자치법규일련번호": "mst-2"},  # same ID, new revision → kept
        ],
        workers=1,
    )
    assert sorted(fetched) == [("1", "mst-1"), ("1", "mst-2")]
    assert counter.snapshot() == (0, 2, 0)


def test_fetch_details_records_detail_failures(monkeypatch):
    failures = []

    def raise_detail(ordinance_id, mst=""):
        raise RuntimeError(f"boom {ordinance_id}")

    monkeypatch.setattr(fetch_cache.cache, "get_detail", lambda key: None)
    monkeypatch.setattr(fetch_cache, "get_ordinance_detail", raise_detail)
    monkeypatch.setattr(fetch_cache, "append_failure", lambda row: failures.append(row))

    counter = fetch_cache.fetch_details([{"자치법규ID": "bad", "자치법규일련번호": "mst-bad"}], workers=1)

    assert counter.snapshot() == (0, 0, 1)
    assert failures == [{"자치법규ID": "bad", "MST": "mst-bad", "reason": "detail_fetch_failed"}]
