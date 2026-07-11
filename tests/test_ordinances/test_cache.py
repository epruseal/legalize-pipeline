"""Tests for the mixed legacy-ID and serial-key ordinance cache layout."""

from ordinances import cache
from .test_converter import SAMPLE_XML


def test_seed_history_from_current_preserves_legacy_file(tmp_path, monkeypatch):
    history_dir = tmp_path / "history"
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(cache, "HISTORY_DIR", history_dir)
    source = tmp_path / "2000111.xml"
    source.write_text(SAMPLE_XML, encoding="utf-8")

    stats = cache.seed_history_from_current()

    assert stats == {"seeded": 1, "cached": 0, "skipped": 0, "errors": 0}
    assert source.exists()
    assert (history_dir / "12345.xml").read_bytes() == source.read_bytes()


def test_historical_lookup_does_not_return_colliding_legacy_id(tmp_path, monkeypatch):
    history_dir = tmp_path / "history"
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(cache, "HISTORY_DIR", history_dir)
    (tmp_path / "12345.xml").write_text(
        SAMPLE_XML.replace("<자치법규일련번호>12345</자치법규일련번호>", "<자치법규일련번호>99999</자치법규일련번호>"),
        encoding="utf-8",
    )

    assert cache.get_detail("12345", historical=True) is None


def test_history_entry_list_round_trip(tmp_path, monkeypatch):
    path = tmp_path / "ordinance_history_entries.json"
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(cache, "HISTORY_LIST_PATH", path)
    entries = [{"자치법규ID": "1", "자치법규일련번호": "2"}]

    cache.put_history_entries(entries)

    assert cache.get_history_entries() == entries


def test_no_result_serials_round_trip(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path)

    cache.add_no_result_serial("111")
    cache.add_no_result_serial("222")
    cache.add_no_result_serial("111")

    assert cache.load_no_result_serials() == {"111", "222"}
