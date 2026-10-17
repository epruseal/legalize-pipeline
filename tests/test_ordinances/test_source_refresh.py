"""First publication must use a fresh response rather than an older valid cache."""

import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import requests

from ordinances import api_client, cache, checkpoint, deferred_revisions, fetch_cache, update
from ordinances.converter import parse_ordinance_xml, xml_to_markdown

FIXTURE = Path(__file__).parents[1] / "fixtures/ordinances/upstream-2178831.xml"


def git(repo, *args):
    return subprocess.check_output(["git", "-C", str(repo), *args]).strip()


def prepare(tmp_path, monkeypatch):
    fresh = FIXTURE.read_bytes()
    # Simulate the valid earlier payload that omitted the published annotations.
    stale = fresh.replace("<개정 2026.10.14.>".encode(), b"")
    stale = stale.replace("3.<삭제 2026.10.14.>".encode(), b"")
    stale = stale.replace("다음 각 호의 사항을 논의".encode(), "다  음 각 호의 사항을 논의".encode())
    assert stale != fresh
    parse_ordinance_xml(stale)
    relative, previous = xml_to_markdown(stale.replace(b"2178831", b"2138081"))
    repo = tmp_path / "repo"
    subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True)
    for key, value in [("user.name", "Test"), ("user.email", "test@example.invalid")]:
        subprocess.run(["git", "-C", str(repo), "config", key, value], check=True)
    target = repo / relative
    target.parent.mkdir(parents=True)
    target.write_text(previous)
    git(repo, "add", relative)
    git(repo, "commit", "-q", "-m", "Previous publication\n\n자치법규ID: 2263618\n자치법규일련번호: 2138081")
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(cache, "HISTORY_DIR", tmp_path / "cache/history")
    monkeypatch.setattr(checkpoint, "CHECKPOINT_FILE", tmp_path / "checkpoint.json")
    monkeypatch.setattr(fetch_cache, "record_requests", lambda *args, **kwargs: None)
    monkeypatch.setattr(fetch_cache, "append_failure", lambda *args, **kwargs: None)
    monkeypatch.setattr(deferred_revisions, "load_entries", lambda: {})
    cache.put_detail("2178831", stale, historical=True)
    rows = [parse_ordinance_xml(fresh)["metadata"]]
    monkeypatch.setattr(update, "fetch_all_current", lambda *args, **kwargs: rows)
    monkeypatch.setattr(update, "fetch_history_for_entries", lambda *args, **kwargs: rows)
    monkeypatch.setattr(update, "_date_range", lambda days: "20261003~20261017")
    requests_seen = []
    response = {"kind": "success"}

    def request(url, params, **kwargs):
        requests_seen.append(params["MST"])
        if response["kind"] == "error":
            raise RuntimeError("temporary upstream outage")
        if response["kind"] == "404":
            missing = requests.Response()
            missing.status_code = 404
            raise requests.HTTPError("404 Not Found", response=missing)
        if response["kind"] == "no_result":
            return SimpleNamespace(content="<Law>일치하는 자치법규가 없습니다.</Law>".encode())
        return SimpleNamespace(content=fresh)

    monkeypatch.setattr(api_client, "_request", request)
    monkeypatch.setattr(sys, "argv", ["ordinances.update", "--repo", str(repo), "--workers", "1", "--commit"])
    return repo, target, fresh, stale, response, requests_seen


def test_first_publication_refreshes_valid_cache_and_preserves_source_annotations(tmp_path, monkeypatch):
    repo, target, fresh, stale, response, requests_seen = prepare(tmp_path, monkeypatch)

    update.main()

    assert requests_seen == ["2178831"]
    assert cache.get_detail("2178831", historical=True) == fresh
    assert target.read_text() == xml_to_markdown(fresh)[1]
    assert target.read_text().count("<개정 2026.10.14.>") == 10
    assert "3.<삭제 2026.10.14.>" in target.read_text()
    assert {"2138081", "2178831"} <= update._committed_metadata(repo)[0]
    head = git(repo, "rev-parse", "HEAD")
    requests_seen.clear()
    update.main()
    assert requests_seen == []
    assert git(repo, "rev-parse", "HEAD") == head


@pytest.mark.parametrize("failure", ["error", "404", "no_result"])
def test_failed_refresh_preserves_previous_publication_and_retries(tmp_path, monkeypatch, failure):
    repo, target, fresh, stale, response, requests_seen = prepare(tmp_path, monkeypatch)
    head = git(repo, "rev-parse", "HEAD")
    previous = target.read_bytes()
    response["kind"] = failure

    with pytest.raises(SystemExit, match="fetch_errors=1"):
        update.main()

    assert git(repo, "rev-parse", "HEAD") == head
    assert target.read_bytes() == previous
    assert cache.get_detail("2178831", historical=True) == stale
    assert cache.load_no_result_serials() == set()
    response["kind"] = "success"
    requests_seen.clear()
    update.main()
    assert requests_seen == ["2178831"]
    assert target.read_text() == xml_to_markdown(fresh)[1]
    assert "2178831" in update._committed_metadata(repo)[0]
