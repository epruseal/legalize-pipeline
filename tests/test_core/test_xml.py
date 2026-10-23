from xml.etree import ElementTree

import pytest

from core.xml import parse_xml, repair_undefined_entities


def test_repair_undefined_entities_preserves_protected_regions_and_valid_entities():
    raw = (
        b'<root attr="A & B &amp; C"><![CDATA[A & B]]><!-- A & B -->'
        b'<?source A & B?><value>C & D &#35; &#x23;</value></root>'
    )

    repaired = repair_undefined_entities(raw)

    assert repaired == (
        b'<root attr="A &amp; B &amp; C"><![CDATA[A & B]]><!-- A & B -->'
        b'<?source A & B?><value>C &amp; D &#35; &#x23;</value></root>'
    )
    root, parsed = parse_xml(raw, context="test")
    assert root.get("attr") == "A & B & C"
    assert root.findtext("value") == "C & D # #"
    assert parsed == repaired


def test_parse_xml_returns_valid_xml_without_byte_changes():
    raw = b"<root>A &amp; B &#35; &#x23;</root>"

    root, parsed = parse_xml(raw, context="test")

    assert root.text == "A & B # #"
    assert parsed is raw


@pytest.mark.parametrize(
    "raw",
    [
        b"<root>&#12</root>",
        b"<root>&#12x</root>",
        b"<root>&#x1G;</root>",
        b"<root>&#X12;</root>",
        b"<root>&#&#&#;</root>",
        b"<root>&#&#;&#</root>",
    ],
)
def test_parse_xml_preserves_malformed_numeric_entities(raw):
    assert repair_undefined_entities(raw) is raw

    with pytest.raises(ElementTree.ParseError):
        parse_xml(raw, context="test")


@pytest.mark.parametrize(
    "raw",
    [
        b"<root><![CDATA[A & B</root>",
        b"<root><!-- A & B</root>",
        b"<root><?source A & B</root>",
        b'<!DOCTYPE root SYSTEM "example.dtd"><root>A & B</root>',
    ],
)
def test_parse_xml_preserves_errors_for_incomplete_protected_regions_and_dtd(raw):
    assert repair_undefined_entities(raw) is raw

    with pytest.raises(ElementTree.ParseError):
        parse_xml(raw, context="test")
