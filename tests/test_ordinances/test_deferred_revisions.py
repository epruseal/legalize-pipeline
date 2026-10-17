"""Reviewed source defects must not block unrelated daily revisions."""

import subprocess
import sys
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from xml.etree import ElementTree

import pytest

from ordinances import api_client, cache, checkpoint, deferred_revisions, fetch_cache, update
from ordinances.converter import parse_ordinance_xml
from tests.test_ordinances.test_converter import SAMPLE_XML

FIXTURES = Path(__file__).parents[1] / "fixtures" / "ordinances"


def prepare(tmp_path, monkeypatch):
    class ReviewDate(date):
        @classmethod
        def today(cls):
            return cls(2026, 10, 17)

    monkeypatch.setattr(deferred_revisions, "date", ReviewDate)
    repo = tmp_path / "repo"
    subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True)
    for key, value in [("user.name", "Test"), ("user.email", "test@example.invalid")]:
        subprocess.run(["git", "-C", str(repo), "config", key, value], check=True)
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(cache, "HISTORY_DIR", tmp_path / "cache/history")
    monkeypatch.setattr(checkpoint, "CHECKPOINT_FILE", tmp_path / "checkpoint.json")
    monkeypatch.setattr(fetch_cache, "record_requests", lambda *args, **kwargs: None)
    monkeypatch.setattr(fetch_cache, "append_failure", lambda *args, **kwargs: None)
    raws = {serial: (FIXTURES / f"upstream-{serial}.xml").read_bytes()
            for serial in ("2178401", "2178653")}
    rows = [{"자치법규ID": "2000111", "자치법규일련번호": "12345", "공포일자": "20261017"}]
    old = {}
    for serial, raw in raws.items():
        root = ElementTree.fromstring(raw)
        identity = root.findtext(".//자치법규ID")
        rows.append({key: root.findtext(f".//{key}")
                     for key in ("자치법규ID", "자치법규일련번호", "공포일자")})
        path = repo / identity / "본문.md"
        path.parent.mkdir()
        old[path] = f"---\n자치법규ID: '{identity}'\n자치법규일련번호: 'old-{serial}'\n공포일자: '2020-01-01'\n---\nPreserved publication.\n".encode()
        path.write_bytes(old[path])
        cache.put_detail(serial, raw, historical=True)
    cache.put_detail("12345", SAMPLE_XML.encode(), historical=True)
    subprocess.run(["git", "-C", str(repo), "add", "2023616/본문.md", "2092891/본문.md"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", "previous publications"], check=True)
    monkeypatch.setattr(update, "fetch_all_current", lambda *args, **kwargs: rows)
    monkeypatch.setattr(update, "fetch_history_for_entries", lambda *args, **kwargs: rows)
    monkeypatch.setattr(update, "_date_range", lambda days: "20261001~20261017")
    requests = []

    def request(url, params, **kwargs):
        requests.append(params["MST"])
        return SimpleNamespace(content=raws[params["MST"]])

    monkeypatch.setattr(api_client, "_request", request)
    return repo, raws, rows, old, requests


def test_daily_update_defers_reviewed_sources_and_preserves_publications(tmp_path, monkeypatch):
    repo, raws, rows, old, requests = prepare(tmp_path, monkeypatch)
    monkeypatch.setattr(sys, "argv", ["ordinances.update", "--repo", str(repo), "--workers", "1", "--commit"])
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))

    update.main()

    assert all(path.read_bytes() == content for path, content in old.items())
    assert all(cache.get_detail(serial, historical=True) == raw for serial, raw in raws.items())
    committed = update._committed_metadata(repo)[0]
    assert "12345" in committed
    assert not committed.intersection(raws)
    assert set(requests) == set(raws)
    assert all(serial in summary.read_text() for serial in raws)
    head = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"])
    repeat = update.run(repo=repo, workers=1, commit=True)
    assert repeat["errors"] == repeat["missing"] == repeat["committed"] == 0
    assert repeat["deferred"] == 2
    assert subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"]) == head


def test_changed_invalid_source_still_blocks_publication(tmp_path, monkeypatch):
    repo, raws, rows, old, requests = prepare(tmp_path, monkeypatch)
    raws["2178401"] = raws["2178401"].replace("디자인클리닉".encode(), "변경된 내용".encode())
    monkeypatch.setattr(sys, "argv", ["ordinances.update", "--repo", str(repo), "--workers", "1", "--commit"])

    with pytest.raises(SystemExit, match="errors=1, missing=1"):
        update.main()

    assert all(path.read_bytes() == content for path, content in old.items())


def test_corrected_source_is_retried_outside_lookback_and_imported(tmp_path, monkeypatch):
    repo, raws, rows, old, requests = prepare(tmp_path, monkeypatch)
    assert update.run(repo=repo, workers=1, commit=True)["deferred"] == 2
    root = ElementTree.fromstring(raws["2178401"])
    # Simulate an upstream correction. Production code does not edit the XML.
    for parent in root.iter():
        for node in list(parent):
            if node.tag == "조" and node.findtext("조내용", "").startswith("제8조 삭제"):
                parent.remove(node)
    raws["2178401"] = ElementTree.tostring(root, encoding="utf-8")
    parse_ordinance_xml(raws["2178401"])
    rows.clear()
    monkeypatch.setattr(update, "_date_range", lambda days: "20261027~20261030")
    before = len(requests)

    recovered = update.run(repo=repo, workers=1, commit=True)

    assert recovered["errors"] == recovered["missing"] == 0
    assert recovered["committed"] == recovered["deferred"] == 1
    assert set(requests[before:]) == set(raws)
    assert "2178401" in update._committed_metadata(repo)[0]
    before = len(requests)
    assert update.run(repo=repo, workers=1, commit=True)["committed"] == 0
    assert requests[before:] == ["2178653"]


@pytest.mark.parametrize("serial", ["2178401", "2178653"])
def test_review_requires_exact_source_error_and_unexpired_fingerprint(serial):
    raw = (FIXTURES / f"upstream-{serial}.xml").read_bytes()
    with pytest.raises(ValueError) as caught:
        parse_ordinance_xml(raw)
    today = date(2026, 10, 17)
    assert deferred_revisions.accepted_entry(serial, raw, caught.value, today) is not None
    assert deferred_revisions.accepted_entry("unknown", raw, caught.value, today) is None
    assert deferred_revisions.accepted_entry(serial, raw + b"\n", caught.value, today) is None
    assert deferred_revisions.accepted_entry(serial, raw, ValueError("different defect"), today) is None
    assert deferred_revisions.accepted_entry(serial, raw, caught.value, date(2026, 10, 31)) is None


def test_refresh_error_does_not_use_previous_deferral_to_succeed(tmp_path, monkeypatch):
    repo, raws, rows, old, requests = prepare(tmp_path, monkeypatch)

    def unavailable(*args, **kwargs):
        raise RuntimeError("temporary upstream outage")

    monkeypatch.setattr(api_client, "_request", unavailable)
    monkeypatch.setattr(sys, "argv", ["ordinances.update", "--repo", str(repo), "--workers", "1", "--commit"])
    with pytest.raises(SystemExit, match="fetch_errors=2"):
        update.main()
    assert all(path.read_bytes() == content for path, content in old.items())


def test_unreviewed_duplicate_is_not_deferred(tmp_path, monkeypatch):
    repo, raws, rows, old, requests = prepare(tmp_path, monkeypatch)
    unknown = raws["2178401"].replace(b"2178401", b"99999").replace(b"2023616", b"99999")
    cache.put_detail("99999", unknown, historical=True)
    rows.append({"자치법규ID": "99999", "자치법규일련번호": "99999", "공포일자": "20261017"})
    stats = update.run(repo=repo, workers=1, commit=True)
    assert stats["errors"] == stats["missing"] == 1
    assert stats["deferred"] == 2


def test_filtered_probe_does_not_fetch_unselected_reviewed_revisions(tmp_path, monkeypatch):
    repo, raws, rows, old, requests = prepare(tmp_path, monkeypatch)
    rows[:] = rows[:1]
    stats = update.run(repo=repo, workers=1, commit=True, org="11")
    assert stats["errors"] == stats["missing"] == stats["deferred"] == 0
    assert requests == []


def test_reviewed_history_is_retried_even_when_present_outside_date_window(tmp_path, monkeypatch):
    repo, raws, rows, old, requests = prepare(tmp_path, monkeypatch)
    monkeypatch.setattr(update, "_date_range", lambda days: "20261027~20261030")
    stats = update.run(repo=repo, workers=1, commit=True)
    assert stats["deferred"] == 2
    assert set(requests) == set(raws)


def test_expired_review_still_blocks_even_without_new_search_results(tmp_path, monkeypatch):
    repo, raws, rows, old, requests = prepare(tmp_path, monkeypatch)
    rows.clear()

    class ExpiredDate(date):
        @classmethod
        def today(cls):
            return cls(2026, 10, 31)

    monkeypatch.setattr(deferred_revisions, "date", ExpiredDate)
    stats = update.run(repo=repo, workers=1, commit=True)
    assert stats["deferred"] == stats["committed"] == 0
    assert stats["errors"] == stats["missing"] == 2
    assert set(requests) == set(raws)


def test_preview_keeps_strict_validation(tmp_path, monkeypatch):
    repo, raws, rows, old, requests = prepare(tmp_path, monkeypatch)
    stats = update.run(repo=repo, workers=1)
    assert stats["deferred"] == 0
    assert stats["errors"] == 2


def test_corrected_reviewed_revision_must_keep_its_identity(tmp_path, monkeypatch):
    repo, raws, rows, old, requests = prepare(tmp_path, monkeypatch)
    raws["2178401"] = SAMPLE_XML.replace("12345", "2178401").encode()
    with pytest.raises(ValueError, match="different identity"):
        update.run(repo=repo, workers=1, commit=True)
    assert all(path.read_bytes() == content for path, content in old.items())


def test_removing_all_article_text_is_not_a_source_correction(tmp_path, monkeypatch):
    repo, raws, rows, old, requests = prepare(tmp_path, monkeypatch)
    root = ElementTree.fromstring(raws["2178401"])
    for parent in root.iter():
        for node in list(parent):
            if node.tag == "조문":
                parent.remove(node)
    raws["2178401"] = ElementTree.tostring(root, encoding="utf-8")
    with pytest.raises(ValueError, match="lost its article text"):
        update.run(repo=repo, workers=1, commit=True)
    assert all(path.read_bytes() == content for path, content in old.items())
