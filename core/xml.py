"""상류 XML 응답을 위한 작은 복구 도우미."""

import logging
import re
from xml.etree import ElementTree

logger = logging.getLogger(__name__)

_VALID_ENTITY_PREFIXES = ("amp;", "lt;", "gt;", "apos;", "quot;")
_XML_DECLARATION = re.compile(r"\A(﻿?<\?xml\s+[^>]*?\bencoding\s*=\s*[\"'])[^\"']+([\"'][^>]*\?>)", re.IGNORECASE)


def _find_protected_end(text: str, start: int, prefix: str, suffix: str) -> int | None:
    end = text.find(suffix, start + len(prefix))
    if end < 0:
        return None
    return end + len(suffix)


def _escape_entities(text: str) -> str:
    result: list[str] = []
    text_start = 0
    index = 0
    while index < len(text):
        if text[index] != "&":
            index += 1
            continue
        result.append(text[text_start:index])
        entity_start = index
        index += 1
        if any(text.startswith(prefix, index) for prefix in _VALID_ENTITY_PREFIXES):
            result.append("&")
        elif index < len(text) and text[index] == "#":
            index += 1
            hexadecimal = index < len(text) and text[index] == "x"
            if hexadecimal:
                index += 1
            digits_start = index
            while index < len(text) and (
                text[index].isascii() and (text[index].isdigit() if not hexadecimal else text[index] in "0123456789abcdefABCDEF")
            ):
                index += 1
            if index > digits_start and index < len(text) and text[index] == ";":
                result.append(text[entity_start:index + 1])
                index += 1
                text_start = index
                continue
            result.append(text[entity_start:index])
        else:
            result.append("&amp;")
        text_start = index
    result.append(text[text_start:])
    return "".join(result)


def _normalize_string_bytes(text: str) -> bytes:
    match = _XML_DECLARATION.match(text)
    if match is None:
        return text.encode("utf-8")
    declaration = match.group(0)
    ElementTree.fromstring(f"{declaration}<root />")
    return f"{match.group(1)}UTF-8{match.group(2)}{text[match.end():]}".encode("utf-8")


def repair_undefined_entities(raw: bytes | str) -> bytes:
    """보호 구간을 보존하고 일반 XML 구간의 미정의 엔티티를 이스케이프한다."""
    if isinstance(raw, str):
        raw = _normalize_string_bytes(raw)
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw

    result: list[str] = []
    text_start = 0
    index = 0
    while index < len(text):
        protected: tuple[str, str] | None = None
        if text.startswith("<![CDATA[", index):
            protected = ("<![CDATA[", "]]>")
        elif text.startswith("<!--", index):
            protected = ("<!--", "-->")
        elif text.startswith("<?", index):
            protected = ("<?", "?>")
        elif text.startswith("<!DOCTYPE", index):
            return raw
        if protected is None:
            index += 1
            continue
        end = _find_protected_end(text, index, *protected)
        if end is None:
            return raw
        result.append(_escape_entities(text[text_start:index]))
        result.append(text[index:end])
        index = end
        text_start = end
    result.append(_escape_entities(text[text_start:]))
    repaired = "".join(result)
    return repaired.encode("utf-8") if repaired != text else raw


def parse_xml(raw: bytes | str, *, context: str = "XML") -> tuple[ElementTree.Element, bytes]:
    """XML을 읽고 미정의 엔티티를 복구한 바이트를 함께 반환한다."""
    if isinstance(raw, str):
        try:
            root = ElementTree.fromstring(raw)
        except ElementTree.ParseError as error:
            try:
                repaired = repair_undefined_entities(raw)
            except ElementTree.ParseError:
                raise error
            try:
                root = ElementTree.fromstring(repaired)
            except ElementTree.ParseError:
                raise error
            logger.warning("Repaired undefined XML entity in %s", context)
            return root, repaired
        return root, _normalize_string_bytes(raw)
    try:
        return ElementTree.fromstring(raw), raw
    except ElementTree.ParseError as error:
        repaired = repair_undefined_entities(raw)
        if repaired == raw:
            raise
        try:
            root = ElementTree.fromstring(repaired)
        except ElementTree.ParseError:
            raise error
        logger.warning("Repaired undefined XML entity in %s", context)
        return root, repaired
