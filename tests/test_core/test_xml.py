from xml.etree import ElementTree

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
