from xml.etree import ElementTree

import pytest

from core.xml import parse_xml, repair_undefined_entities


def _tree_state(root):
    return [
        (node.tag, tuple(sorted(node.attrib.items())), node.text, node.tail)
        for node in root.iter()
    ]


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


def test_parse_xml_returns_valid_bytes_without_byte_changes():
    raw = b"<root>A &amp; B &#35; &#x23;</root>"

    root, parsed = parse_xml(raw, context="test")

    assert root.text == "A & B # #"
    assert parsed is raw


@pytest.mark.parametrize(
    "declaration",
    [
        '<?xml version="1.0" encoding="ISO-8859-1"?>',
        '<?xml version="1.0" encoding="UTF-16"?>',
        '<?xml version="1.0" encoding="UTF-8"?>',
        '﻿<?xml version="1.0" encoding="ISO-8859-1"?>',
    ],
)
def test_parse_xml_preserves_valid_string_tree_and_normalizes_declaration(declaration):
    raw = f'{declaration}<root attr="값"><child>가</child>뒤<tail />끝</root>'

    expected = ElementTree.fromstring(raw)
    root, parsed = parse_xml(raw, context="test")

    assert _tree_state(root) == _tree_state(expected)
    assert b'encoding="UTF-8"' in parsed
    reparsed = ElementTree.fromstring(parsed)
    assert _tree_state(reparsed) == _tree_state(expected)


@pytest.mark.parametrize("bom", ["", "\ufeff"])
def test_parse_xml_repairs_string_entities_without_changing_protected_regions(bom):
    protected = '<?xml version="1.0" encoding="ISO-8859-1"?>'
    pi_like = 'xml version="1.0" encoding="ISO-8859-1" A & B'
    raw = (
        f'{bom}<?xml version="1.0" encoding="ISO-8859-1"?>'
        f'<root attr="A & B"><![CDATA[{protected} A & B]]><!-- {protected} A & B -->'
        f'<?source {pi_like}?><child>C & D</child>tail & E</root>'
    )

    root, parsed = parse_xml(raw, context="test")

    assert root.get("attr") == "A & B"
    assert root.findtext("child") == "C & D"
    assert protected.encode() in parsed
    assert parsed == (
        f'{bom}<?xml version="1.0" encoding="UTF-8"?>'
        f'<root attr="A &amp; B"><![CDATA[{protected} A & B]]><!-- {protected} A & B -->'
        f'<?source {pi_like}?><child>C &amp; D</child>tail &amp; E</root>'
    ).encode()


@pytest.mark.parametrize("bom", ["", "\ufeff"])
def test_parse_xml_does_not_normalize_declaration_like_text_in_valid_string(bom):
    protected = '<?xml version="1.0" encoding="ISO-8859-1"?>'
    raw = (
        f'{bom}<root><![CDATA[{protected}]]><!-- {protected} -->'
        f'<?source xml version="1.0" encoding="ISO-8859-1"?></root>'
    )

    _root, parsed = parse_xml(raw, context="test")

    assert parsed == raw.encode()


@pytest.mark.parametrize(
    "declaration",
    [
        '<?xml version="1.0" encoding="UTF 8"?>',
        '<?xml version="1.0" encoding="1UTF8"?>',
        '<?xml version="1.0" encoding="UTF@8"?>',
        '<?xml version="1.0" standalone="maybe"?>',
        '<?xml version="1.0" encoding="UTF-8"',
    ],
)
def test_parse_xml_preserves_invalid_string_declaration_error(declaration):
    raw = f"{declaration}<root>A & B</root>"
    with pytest.raises(ElementTree.ParseError) as expected:
        ElementTree.fromstring(raw)

    with pytest.raises(ElementTree.ParseError) as actual:
        parse_xml(raw, context="test")

    assert str(actual.value) == str(expected.value)
    assert actual.value.code == expected.value.code
    assert actual.value.position == expected.value.position


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


_NUL_BYTES = [
    "<r>A & B</r>".encode("utf-16-le"),
    '<?xml version="1.0" encoding="UTF-16"?><r>A & B</r>'.encode("utf-16-le"),
    "<r>A & B</r>".encode("utf-16-be"),
    "<r>A & B</r>".encode("utf-16"),
    "<판례>A & B</판례>".encode("utf-16-le"),
]


@pytest.mark.parametrize("raw", _NUL_BYTES)
def test_parse_xml_preserves_error_for_non_utf8_bytes_with_nul(raw):
    assert repair_undefined_entities(raw) is raw
    with pytest.raises(ElementTree.ParseError) as expected:
        ElementTree.fromstring(raw)

    with pytest.raises(ElementTree.ParseError) as actual:
        parse_xml(raw, context="test")

    assert str(actual.value) == str(expected.value)
    assert actual.value.code == expected.value.code
    assert actual.value.position == expected.value.position


def test_parse_xml_preserves_error_for_string_with_nul():
    raw = "<r>A & B\0</r>"
    with pytest.raises(ElementTree.ParseError) as expected:
        ElementTree.fromstring(raw)

    with pytest.raises(ElementTree.ParseError) as actual:
        parse_xml(raw, context="test")

    assert str(actual.value) == str(expected.value)
    assert actual.value.position == expected.value.position
