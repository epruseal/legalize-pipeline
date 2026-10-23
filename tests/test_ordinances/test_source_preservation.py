"""Source defects retain text and order through the public converter."""

from pathlib import Path
from xml.etree import ElementTree

import pytest
import yaml
import subprocess

from ordinances.converter import xml_to_markdown
from ordinances.validate import validate_markdown_file

FIXTURES = Path(__file__).parents[1] / "fixtures" / "ordinances"


@pytest.mark.parametrize("fixture", [
    "upstream-2175357.xml", "upstream-2169079.xml", "upstream-2169057.xml",
    "upstream-2170713.xml", "upstream-2178401.xml", "upstream-2178653-20261023.xml",
])
def test_source_fields_are_preserved_in_order(tmp_path, fixture):
    raw = (FIXTURES / fixture).read_bytes()
    path, markdown = xml_to_markdown(raw)
    frontmatter = yaml.safe_load(markdown.split("---\n")[1])
    assert frontmatter["원문오류"]
    assert "원천 XML의 조문 구조에 오류가 있습니다." in markdown
    offset = markdown.index("원천 XML의 조문 구조에 오류가 있습니다.")
    for node in ElementTree.fromstring(raw).iter():
        if node.tag in {
            "조문번호", "조문가지번호", "조문여부", "조문제목", "조제목",
            "조문내용", "조내용", "부칙공포일자", "부칙공포번호", "부칙내용",
        }:
            text = "".join(node.itertext())
            block = f"{node.tag}\n\n```text\n{text}\n```"
            offset = markdown.index(block, offset) + len(block)
    output = tmp_path / path
    output.parent.mkdir(parents=True)
    output.write_text(markdown)
    assert validate_markdown_file(output, repo_root=tmp_path) == []
    output.write_text(markdown.replace("원천 XML의 조문 구조에 오류가 있습니다.", ""))
    assert any("missing source preservation" in error for error in validate_markdown_file(output, repo_root=tmp_path))


def test_fenced_source_preserves_whitespace_entities_and_markdown():
    from tests.test_ordinances.test_converter import SAMPLE_XML

    content = "  제1조 · &amp; &lt;개정&gt;\n```\n# 제목\n[참조](주소)  \n"
    duplicate = f"<조><조문번호>000100</조문번호><조문여부>Y</조문여부><조내용>{content}</조내용></조>"
    raw = SAMPLE_XML.replace("</자치법규>", duplicate + "</자치법규>")
    _, markdown = xml_to_markdown(raw)
    assert "````text\n  제1조 · & <개정>\n```\n# 제목\n[참조](주소)  \n\n````" in markdown


def test_repeal_preserves_source_in_deletion_commit(tmp_path, monkeypatch):
    from ordinances import cache
    from ordinances.import_ordinances import import_from_cache
    from ordinances.converter import SOURCE_WARNING

    root = ElementTree.fromstring((FIXTURES / "upstream-2178653-20261023.xml").read_bytes())
    root.find(".//제개정정보").text = "폐지"
    raw = ElementTree.tostring(root, encoding="utf-8")
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(cache, "HISTORY_DIR", tmp_path / "cache/history")
    cache.put_detail("2178653", raw, historical=True)
    repo = tmp_path / "repo"
    subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True)
    for key, value in [("user.name", "Test"), ("user.email", "test@example.invalid")]:
        subprocess.run(["git", "-C", str(repo), "config", key, value], check=True)
    stats = import_from_cache(repo, commit=True)
    assert stats["errors"] == 0 and stats["committed"] == 1
    assert not list(repo.rglob("본문.md"))
    message = subprocess.check_output(["git", "-C", str(repo), "log", "-1", "--format=%B"], text=True)
    _, markdown = xml_to_markdown(raw)
    assert message.rstrip().endswith(markdown[markdown.index("> " + SOURCE_WARNING):].rstrip())
    assert cache.get_detail("2178653", historical=True) == raw


@pytest.mark.parametrize("raw_date", ["2000011 ", "9999999 ", "20261301", ""])
def test_incomplete_dates_preserve_source_and_match_compiler_order(tmp_path, monkeypatch, raw_date):
    from ordinances import cache
    from ordinances.import_ordinances import import_from_cache
    from tests.test_ordinances.test_converter import SAMPLE_XML

    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(cache, "HISTORY_DIR", tmp_path / "cache/history")
    root = ElementTree.fromstring(SAMPLE_XML)
    root.find(".//공포일자").text = "20210930"
    valid = ElementTree.tostring(root, encoding="utf-8")
    cache.put_detail("12345", valid, historical=True)
    root.find(".//공포일자").text = raw_date
    root.find(".//자치법규일련번호").text = "12346"
    invalid = ElementTree.tostring(root, encoding="utf-8")
    cache.put_detail("12346", invalid, historical=True)
    repo = tmp_path / "repo"
    subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True)
    for key, value in [("user.name", "Test"), ("user.email", "test@example.invalid")]:
        subprocess.run(["git", "-C", str(repo), "config", key, value], check=True)
    stats = import_from_cache(repo, commit=True)
    assert stats["errors"] == 0 and stats["committed"] == 2
    dates = subprocess.check_output(["git", "-C", str(repo), "log", "--reverse", "--format=%aI"], text=True).splitlines()
    assert dates == ["1970-01-01T12:00:00+09:00", "2021-09-30T12:00:00+09:00"]
    path, expected = xml_to_markdown(invalid)
    actual = subprocess.check_output(["git", "-C", str(repo), "show", f"HEAD~1:{path}"], text=True)
    assert actual == expected
    assert (repo / path).read_text() == xml_to_markdown(valid)[1]
    assert cache.get_detail("12346", historical=True) == invalid
