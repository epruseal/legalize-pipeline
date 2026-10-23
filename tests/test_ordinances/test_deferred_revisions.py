"""Previously deferred sources are published without changing their text."""

import subprocess
import sys
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from xml.etree import ElementTree

import pytest
import requests

from ordinances import api_client, cache, checkpoint, deferred_revisions, fetch_cache, update
from ordinances.converter import parse_ordinance_xml
from tests.test_ordinances.test_converter import SAMPLE_XML

FIXTURES = Path(__file__).parents[1] / "fixtures" / "ordinances"
REVIEWED_SOURCES = {
    "2175357": FIXTURES / "upstream-2175357.xml",
    "2169079": FIXTURES / "upstream-2169079.xml",
    "2169057": FIXTURES / "upstream-2169057.xml",
    "2170713": FIXTURES / "upstream-2170713.xml",
    "2178401": FIXTURES / "upstream-2178401.xml",
    "2178653": FIXTURES / "upstream-2178653-20261018.xml",
}


def prepare(tmp_path, monkeypatch):
    class ReviewDate(date):
        @classmethod
        def today(cls):
            return cls(2026, 10, 19)

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
    raws = {serial: path.read_bytes() for serial, path in REVIEWED_SOURCES.items()}
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
    subprocess.run(["git", "-C", str(repo), "add", *[str(path.relative_to(repo)) for path in old]], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", "previous publications"], check=True)
    monkeypatch.setattr(update, "fetch_all_current", lambda *args, **kwargs: rows)
    monkeypatch.setattr(update, "fetch_history_for_entries", lambda *args, **kwargs: rows)
    monkeypatch.setattr(update, "_date_range", lambda days: "20261001~20261017")
    requests = []

    def request(url, params, **kwargs):
        requests.append(params["MST"])
        raw = raws.get(params["MST"])
        if raw is None:
            raw = cache.get_detail(params["MST"], historical=True)
        assert raw is not None
        return SimpleNamespace(content=raw)

    monkeypatch.setattr(api_client, "_request", request)
    return repo, raws, rows, old, requests


def test_daily_update_preserves_source_defects_and_previous_history(tmp_path, monkeypatch):
    repo, raws, rows, old, requests = prepare(tmp_path, monkeypatch)
    before = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
    monkeypatch.setattr(sys, "argv", ["ordinances.update", "--repo", str(repo), "--workers", "1", "--commit"])
    update.main()
    assert all(cache.get_detail(serial, historical=True) == raw for serial, raw in raws.items())
    assert set(raws) | {"12345"} <= update._committed_metadata(repo)[0]
    for path, content in old.items():
        assert subprocess.check_output(["git", "-C", str(repo), "show", f"{before}:{path.relative_to(repo)}"]) == content
    documents = list(repo.rglob("본문.md"))
    assert sum("원문오류:" in path.read_text() for path in documents) == len(raws)
    head = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"])
    repeat = update.run(repo=repo, workers=1, commit=True)
    assert repeat["errors"] == repeat["missing"] == repeat["committed"] == repeat["deferred"] == 0
    assert subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"]) == head


@pytest.mark.parametrize("serial, original", [("2178401", "디자인클리닉"), ("2178653", "지급구분")])
def test_changed_defective_source_preserves_new_text(tmp_path, monkeypatch, serial, original):
    repo, raws, rows, old, requests = prepare(tmp_path, monkeypatch)
    raws[serial] = raws[serial].replace(original.encode(), "변경된 내용".encode())
    stats = update.run(repo=repo, workers=1, commit=True)
    assert stats["errors"] == stats["missing"] == stats["deferred"] == 0
    assert serial in update._committed_metadata(repo)[0]
    assert any("변경된 내용" in path.read_text() and "원문오류:" in path.read_text() for path in repo.rglob("본문.md"))


def test_daily_update_preserves_rotated_attachment_locators(tmp_path, monkeypatch):
    repo, raws, rows, old, requests = prepare(tmp_path, monkeypatch)
    raws["2178653"] = (FIXTURES / "upstream-2178653-20261023.xml").read_bytes()
    stats = update.run(repo=repo, workers=1, commit=True)
    assert stats["errors"] == stats["missing"] == stats["deferred"] == 0
    assert cache.get_detail("2178653", historical=True) == raws["2178653"]
    assert "2178653" in update._committed_metadata(repo)[0]


def test_corrected_source_is_imported_without_error_marker(tmp_path, monkeypatch):
    repo, raws, rows, old, requests = prepare(tmp_path, monkeypatch)
    root = ElementTree.fromstring(raws["2178401"])
    for parent in root.iter():
        for node in list(parent):
            if node.tag == "조" and node.findtext("조내용", "").startswith("제8조 삭제"):
                parent.remove(node)
    raws["2178401"] = ElementTree.tostring(root, encoding="utf-8")
    assert not parse_ordinance_xml(raws["2178401"])["source_errors"]
    rows.clear()
    stats = update.run(repo=repo, workers=1, commit=True)
    assert stats["errors"] == stats["missing"] == stats["deferred"] == 0
    assert "2178401" in update._committed_metadata(repo)[0]
    assert sum("원문오류:" in path.read_text() for path in repo.rglob("본문.md")) == len(raws) - 1


@pytest.mark.parametrize("serial", REVIEWED_SOURCES)
def test_review_requires_exact_source_error_and_unexpired_fingerprint(serial):
    raw = REVIEWED_SOURCES[serial].read_bytes()
    error = ValueError(parse_ordinance_xml(raw)["source_errors"][0])
    today = date(2026, 10, 18)
    assert deferred_revisions.accepted_entry(serial, raw, error, today) is not None
    assert deferred_revisions.accepted_entry("unknown", raw, error, today) is None
    if serial != "2178653":
        assert deferred_revisions.accepted_entry(serial, raw + b"\n", error, today) is None
    assert deferred_revisions.accepted_entry(serial, raw, ValueError("different defect"), today) is None
    assert deferred_revisions.accepted_entry(serial, raw, error, date(2026, 10, 31)) is None


def test_reviewed_attachment_locator_changes_keep_the_same_fingerprint():
    previous = (FIXTURES / "upstream-2178653.xml").read_bytes()
    current = REVIEWED_SOURCES["2178653"].read_bytes()
    previous_xml = ElementTree.fromstring(previous)
    current_xml = ElementTree.fromstring(current)
    restored = current
    for old, new in zip(previous_xml.findall(".//별표단위"), current_xml.findall(".//별표단위"), strict=True):
        for before, after in [(old.attrib["별표키"], new.attrib["별표키"]),
                              (old.findtext("별표첨부파일명"), new.findtext("별표첨부파일명"))]:
            assert before != after
            restored = restored.replace(after.encode(), before.encode())
    assert restored == previous
    latest = (FIXTURES / "upstream-2178653-20261023.xml").read_bytes()
    assert deferred_revisions.attachment_locator_fingerprint(current) == deferred_revisions.attachment_locator_fingerprint(latest)
    for raw in [current, previous, latest]:
        error = ValueError(parse_ordinance_xml(raw)["source_errors"][0])
        entry = deferred_revisions.accepted_entry("2178653", raw, error, date(2026, 10, 18))
        assert entry is not None
        assert deferred_revisions.accepted_entry("2178653", raw, error, date(2026, 10, 31)) is None
        assert deferred_revisions.accepted_entry("2178653", raw, ValueError("different defect"), date(2026, 10, 23)) is None


@pytest.mark.parametrize("change", [
    "article", "addendum", "identity", "serial", "date", "title", "attachment_title",
    "filename", "host", "scheme", "path", "query", "non_numeric_key", "non_numeric_sequence",
    "remove_attachment", "add_attachment", "reorder_attachments", "extra_attribute", "extra_element",
])
def test_locator_review_rejects_other_source_changes(change):
    root = ElementTree.fromstring((FIXTURES / "upstream-2178653-20261023.xml").read_bytes())
    attachments = root.find("별표")
    attachment = attachments.find("별표단위")
    link = attachment.find("별표첨부파일명")
    text_paths = {
        "article": ".//조내용", "addendum": ".//부칙내용", "identity": ".//자치법규ID",
        "serial": ".//자치법규일련번호", "date": ".//공포일자", "title": ".//자치법규명",
        "attachment_title": ".//별표제목",
    }
    if change in text_paths:
        node = root.find(text_paths[change])
        node.text = (node.text or "") + " changed"
    elif change == "filename":
        link.text += "changed"
    elif change == "host":
        link.text = link.text.replace("www.law.go.kr", "example.invalid")
    elif change == "scheme":
        link.text = link.text.replace("http://", "https://")
    elif change == "path":
        link.text = link.text.replace("flDownload.do", "other.do")
    elif change == "query":
        link.text = link.text.replace("gubun=ELIS", "gubun=OTHER")
    elif change == "non_numeric_key":
        attachment.set("별표키", "unexpected")
    elif change == "non_numeric_sequence":
        link.text = link.text.replace("flSeq=", "flSeq=unexpected")
    elif change == "remove_attachment":
        attachments.remove(attachment)
    elif change == "add_attachment":
        attachments.append(ElementTree.fromstring(ElementTree.tostring(attachment, encoding="utf-8")))
    elif change == "reorder_attachments":
        attachments.remove(attachment)
        attachments.append(attachment)
    elif change == "extra_attribute":
        attachment.set("new", "value")
    elif change == "extra_element":
        ElementTree.SubElement(attachment, "new").text = "value"
    raw = ElementTree.tostring(root, encoding="utf-8")
    assert deferred_revisions.accepted_entry(
        "2178653", raw, ValueError("duplicate ordinance article 1"), date(2026, 10, 23)
    ) is None


def test_locator_mask_does_not_change_article_text():
    raw = (FIXTURES / "upstream-2178653-20261023.xml").read_bytes()
    root = ElementTree.fromstring(raw)
    root.find(".//조내용").text += '\n별표키="123" flSeq=456'
    first = ElementTree.tostring(root, encoding="utf-8")
    second = first.replace(b'flSeq=456', b'flSeq=789')
    assert deferred_revisions.attachment_locator_fingerprint(first) != deferred_revisions.attachment_locator_fingerprint(second)


def test_refresh_error_does_not_use_previous_deferral_to_succeed(tmp_path, monkeypatch):
    repo, raws, rows, old, requests = prepare(tmp_path, monkeypatch)

    def unavailable(url, params, **kwargs):
        if params["MST"] == "12345":
            return SimpleNamespace(content=SAMPLE_XML.encode())
        raise RuntimeError("temporary upstream outage")

    monkeypatch.setattr(api_client, "_request", unavailable)
    monkeypatch.setattr(sys, "argv", ["ordinances.update", "--repo", str(repo), "--workers", "1", "--commit"])
    with pytest.raises(SystemExit, match=f"fetch_errors={len(raws)}"):
        update.main()
    assert all(path.read_bytes() == content for path, content in old.items())
    assert "12345" not in update._committed_metadata(repo)[0]


@pytest.mark.parametrize("response_kind", ["http_404", "no_result_xml"])
def test_missing_reviewed_source_does_not_use_previous_deferral(tmp_path, monkeypatch, response_kind):
    repo, raws, rows, old, requests_seen = prepare(tmp_path, monkeypatch)

    def unavailable(url, params, **kwargs):
        if params["MST"] == "12345":
            return SimpleNamespace(content=SAMPLE_XML.encode())
        if response_kind == "http_404":
            response = requests.Response()
            response.status_code = 404
            raise requests.HTTPError("404 Not Found", response=response)
        return SimpleNamespace(content="<Law>일치하는 자치법규가 없습니다.</Law>".encode())

    monkeypatch.setattr(api_client, "_request", unavailable)
    monkeypatch.setattr(sys, "argv", ["ordinances.update", "--repo", str(repo), "--workers", "1", "--commit"])
    with pytest.raises(SystemExit, match=f"fetch_errors={len(raws)}"):
        update.main()
    assert all(path.read_bytes() == content for path, content in old.items())
    assert all(cache.get_detail(serial, historical=True) == raw for serial, raw in raws.items())
    assert cache.load_no_result_serials() == set()
    assert "12345" not in update._committed_metadata(repo)[0]


def test_unreviewed_duplicate_is_not_deferred(tmp_path, monkeypatch):
    repo, raws, rows, old, requests = prepare(tmp_path, monkeypatch)
    unknown = raws["2178401"].replace(b"2178401", b"99999").replace(b"2023616", b"99999")
    cache.put_detail("99999", unknown, historical=True)
    rows.append({"자치법규ID": "99999", "자치법규일련번호": "99999", "공포일자": "20261017"})
    stats = update.run(repo=repo, workers=1, commit=True)
    assert stats["errors"] == stats["missing"] == stats["deferred"] == 0
    assert "99999" in update._committed_metadata(repo)[0]


def test_filtered_probe_does_not_fetch_unselected_reviewed_revisions(tmp_path, monkeypatch):
    repo, raws, rows, old, requests = prepare(tmp_path, monkeypatch)
    rows[:] = rows[:1]
    stats = update.run(repo=repo, workers=1, commit=True, org="11")
    assert stats["errors"] == stats["missing"] == stats["deferred"] == 0
    assert requests == ["12345"]


def test_reviewed_history_is_retried_even_when_present_outside_date_window(tmp_path, monkeypatch):
    repo, raws, rows, old, requests = prepare(tmp_path, monkeypatch)
    monkeypatch.setattr(update, "_date_range", lambda days: "20261027~20261030")
    stats = update.run(repo=repo, workers=1, commit=True)
    assert stats["deferred"] == 0
    assert set(requests) == set(raws) | {"12345"}


def test_expired_deferral_does_not_block_source_preservation(tmp_path, monkeypatch):
    repo, raws, rows, old, requests = prepare(tmp_path, monkeypatch)
    rows.clear()

    class ExpiredDate(date):
        @classmethod
        def today(cls):
            return cls(2026, 10, 31)

    monkeypatch.setattr(deferred_revisions, "date", ExpiredDate)
    stats = update.run(repo=repo, workers=1, commit=True)
    assert stats["deferred"] == stats["errors"] == stats["missing"] == 0
    assert stats["committed"] == len(raws)
    assert set(requests) == set(raws)


def test_preview_preserves_source_errors(tmp_path, monkeypatch):
    repo, raws, rows, old, requests = prepare(tmp_path, monkeypatch)
    stats = update.run(repo=repo, workers=1)
    assert stats["deferred"] == 0
    assert stats["errors"] == 0
    assert stats["written"] == len(raws) + 1


def test_corrected_reviewed_revision_must_keep_its_identity(tmp_path, monkeypatch):
    repo, raws, rows, old, requests = prepare(tmp_path, monkeypatch)
    raws["2178401"] = SAMPLE_XML.replace("12345", "2178401").encode()
    stats = update.run(repo=repo, workers=1, commit=True)
    assert stats["fetch_errors"] == 1
    assert stats["committed"] == 0
    assert cache.get_detail("2178401", historical=True) == REVIEWED_SOURCES["2178401"].read_bytes()
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


def test_all_known_source_defects_are_retried_after_the_search_window(tmp_path, monkeypatch):
    repo, raws, rows, old, requests_seen = prepare(tmp_path, monkeypatch)
    rows.clear()
    monkeypatch.setattr(update, "_date_range", lambda days: "20261019~20261030")
    before = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"])

    stats = update.run(repo=repo, workers=1, commit=True)

    assert set(requests_seen) == set(REVIEWED_SOURCES)
    assert stats["fetched"] == stats["committed"] == len(REVIEWED_SOURCES)
    assert stats["errors"] == stats["missing"] == stats["deferred"] == 0
    assert subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"]) != before
