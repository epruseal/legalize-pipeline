import logging
from pathlib import Path
from xml.etree import ElementTree

import pytest

from core.xml import parse_xml, repair_undefined_entities


def test_repair_undefined_entities_preserves_valid_entities():
    raw = b"<root>A & B &amp; C &#35; &#x23;</root>"
    repaired = repair_undefined_entities(raw)
    assert repaired == b"<root>A &amp; B &amp; C &#35; &#x23;</root>"


def test_parse_xml_returns_repaired_bytes():
    root, raw = parse_xml(b"<root>A & B</root>", context="test")
    assert root.text == "A & B"
    assert raw == b"<root>A &amp; B</root>"


def test_parse_xml_keeps_unrelated_parse_errors():
    try:
        parse_xml(b"<root>", context="test")
    except ElementTree.ParseError:
        pass
    else:
        raise AssertionError("expected malformed XML to remain an error")


NUL_FIXTURE = Path(__file__).parents[1] / "fixtures" / "ordinances" / "nul-in-cdata.xml"


def _xml_warnings(caplog):
    return [record.getMessage() for record in caplog.records if record.name == "core.xml" and record.levelno == logging.WARNING]


def test_parse_xml_strip_nul_keeps_response_bytes(caplog):
    raw = NUL_FIXTURE.read_bytes()
    with caplog.at_level(logging.WARNING, logger="core.xml"):
        root, returned = parse_xml(raw, context="fixture", strip_nul=True)
    assert "\x00" not in "".join(root.itertext())
    assert root.findtext(".//자치법규일련번호") == "480037"
    assert returned == raw
    assert _xml_warnings(caplog) == ["Removed 3 NUL character(s) from fixture before parsing"]


def test_parse_xml_default_still_rejects_nul_control(caplog):
    with pytest.raises(ElementTree.ParseError):
        parse_xml(NUL_FIXTURE.read_bytes(), context="fixture")
    raw = b"<root>A</root>"
    with caplog.at_level(logging.WARNING, logger="core.xml"):
        root, returned = parse_xml(raw, context="fixture")
    assert root.text == "A"
    assert returned == raw
    assert _xml_warnings(caplog) == []


def test_parse_xml_strip_nul_without_nul_has_no_warning(caplog):
    raw = b"<root>A</root>"
    with caplog.at_level(logging.WARNING, logger="core.xml"):
        root, returned = parse_xml(raw, context="fixture", strip_nul=True)
    assert root.text == "A"
    assert returned == raw
    assert _xml_warnings(caplog) == []


def test_parse_xml_strip_nul_removes_only_nul(caplog):
    with caplog.at_level(logging.WARNING, logger="core.xml"):
        with pytest.raises(ElementTree.ParseError):
            parse_xml(b"<root>A\x00\x05</root>", context="fixture", strip_nul=True)
    assert _xml_warnings(caplog) == []


def test_parse_xml_strip_nul_does_not_repair_cdata_entity_text(caplog):
    raw = b"<root><![CDATA[A&nbsp;B\x00]]></root>"
    with caplog.at_level(logging.WARNING, logger="core.xml"):
        root, returned = parse_xml(raw, context="fixture", strip_nul=True)
    assert root.text == "A&nbsp;B"
    assert returned == raw
    assert _xml_warnings(caplog) == ["Removed 1 NUL character(s) from fixture before parsing"]


def test_parse_xml_strip_nul_repairs_entity_and_keeps_nul(caplog):
    raw = b"<root>A & B<c><![CDATA[x\x00]]></c></root>"
    with caplog.at_level(logging.WARNING, logger="core.xml"):
        root, returned = parse_xml(raw, context="fixture", strip_nul=True)
    assert "".join(root.itertext()) == "A & Bx"
    assert returned == repair_undefined_entities(raw)
    assert returned != raw
    assert returned.count(b"\x00") == raw.count(b"\x00") == 1
    assert sorted(_xml_warnings(caplog)) == [
        "Removed 1 NUL character(s) from fixture before parsing",
        "Repaired undefined XML entity in fixture",
    ]


def test_parse_xml_strip_nul_keeps_other_defects(caplog):
    with caplog.at_level(logging.WARNING, logger="core.xml"):
        with pytest.raises(ElementTree.ParseError, match="mismatched tag"):
            parse_xml(b"<root>A\x00<a></root>", context="fixture", strip_nul=True)
    assert _xml_warnings(caplog) == []


def test_parse_xml_strip_nul_reports_first_error_when_repair_fails(caplog):
    raw = b"<root>A\x00 & B<a></root>"
    with pytest.raises(ElementTree.ParseError) as first:
        ElementTree.fromstring(raw.replace(b"\x00", b""))
    with caplog.at_level(logging.WARNING, logger="core.xml"):
        with pytest.raises(ElementTree.ParseError) as raised:
            parse_xml(raw, context="fixture", strip_nul=True)
    assert str(raised.value) == str(first.value)
    assert _xml_warnings(caplog) == []


def test_fromstring_without_nul(caplog):
    from core.xml import fromstring_without_nul

    with caplog.at_level(logging.WARNING, logger="core.xml"):
        root = fromstring_without_nul(NUL_FIXTURE.read_bytes(), context="fixture")
    assert root.findtext(".//자치법규일련번호") == "480037"
    assert "\x00" not in "".join(root.itertext())
    assert _xml_warnings(caplog) == ["Removed 3 NUL character(s) from fixture before parsing"]
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="core.xml"):
        with pytest.raises(ElementTree.ParseError):
            fromstring_without_nul(b"<root>A & B\x00</root>", context="fixture")
        with pytest.raises(ElementTree.ParseError):
            fromstring_without_nul("<root>A & B\x00</root>", context="fixture")
    assert _xml_warnings(caplog) == []
    with caplog.at_level(logging.WARNING, logger="core.xml"):
        root = fromstring_without_nul("<root>A\x00</root>", context="fixture")
    assert root.text == "A"
    assert _xml_warnings(caplog) == ["Removed 1 NUL character(s) from fixture before parsing"]
