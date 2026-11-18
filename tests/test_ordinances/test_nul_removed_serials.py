from datetime import date
from unittest.mock import Mock
from xml.etree.ElementTree import ParseError

from core.counter import Counter
from ordinances import detail_failure_allowlist, fetch_cache
from tests.test_ordinances.nul_removed_serials import REMOVED_NUL_SERIALS

TODAY = date(2026, 11, 19)
NUL_ERROR = "not well-formed (invalid token): line 1, column 1"


class FixedDate(date):
    @classmethod
    def today(cls):
        return cls(2026, 11, 19)


def _fix_allowlist_date(monkeypatch):
    detail_failure_allowlist.load_allowlist.cache_clear()
    monkeypatch.setattr(detail_failure_allowlist, "date", FixedDate)


def test_removed_serials_are_unique():
    assert len(REMOVED_NUL_SERIALS) == 109
    assert len(set(REMOVED_NUL_SERIALS)) == len(REMOVED_NUL_SERIALS)


def test_removed_serials_are_not_listed():
    detail_failure_allowlist.load_allowlist.cache_clear()
    for serial in REMOVED_NUL_SERIALS:
        assert not detail_failure_allowlist.is_listed(serial, today=TODAY), serial
        assert detail_failure_allowlist.accepted_entry(
            serial, ParseError(NUL_ERROR), today=TODAY
        ) is None, serial


def test_history_fetch_selects_removed_serials(monkeypatch):
    _fix_allowlist_date(monkeypatch)
    monkeypatch.setattr(fetch_cache.cache, "get_detail", lambda cache_key, **kwargs: None)
    monkeypatch.setattr(fetch_cache.cache, "load_no_result_serials", lambda: set())
    entries = [
        {"자치법규ID": str(index), "자치법규일련번호": serial}
        for index, serial in enumerate(REMOVED_NUL_SERIALS)
    ]

    assert fetch_cache.missing_detail_entries(entries) == entries


def test_removed_serial_failure_is_an_error(monkeypatch):
    _fix_allowlist_date(monkeypatch)
    monkeypatch.setattr(fetch_cache.cache, "get_detail", lambda cache_key, **kwargs: None)
    monkeypatch.setattr(fetch_cache.deferred_revisions, "load_entries", lambda: {})
    monkeypatch.setattr(fetch_cache, "get_ordinance_detail", Mock(side_effect=ParseError(NUL_ERROR)))
    failures = Mock()
    monkeypatch.setattr(fetch_cache, "append_failure", failures)
    counter = Counter()

    fetch_cache._fetch_detail_task("1", REMOVED_NUL_SERIALS[0], counter, Mock())

    assert counter.snapshot_all().get("errors", 0) == 1
    assert counter.snapshot_all().get("known_failures", 0) == 0
    failures.assert_called_once()


def test_mismatched_tag_entry_remains():
    detail_failure_allowlist.load_allowlist.cache_clear()
    entry = detail_failure_allowlist.accepted_entry(
        "2000603", ParseError("mismatched tag: line 1, column 1"), today=TODAY
    )

    assert entry is not None
    assert entry["reason"] == "upstream_malformed_xml"
