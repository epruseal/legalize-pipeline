"""Small XML helpers for malformed upstream responses."""

import logging
import re
from xml.etree import ElementTree

logger = logging.getLogger(__name__)

_UNDEFINED_ENTITY = re.compile(
    r"&(?!(?:amp|lt|gt|apos|quot|#[0-9]+|#x[0-9a-fA-F]+);)"
)


def repair_undefined_entities(raw: bytes | str) -> bytes:
    """Escape bare/unknown ampersands without changing valid XML entities."""
    if isinstance(raw, str):
        raw = raw.encode("utf-8")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw
    repaired = _UNDEFINED_ENTITY.sub("&amp;", text)
    return repaired.encode("utf-8") if repaired != text else raw


def parse_xml(raw: bytes | str, *, context: str = "XML") -> tuple[ElementTree.Element, bytes]:
    """Parse XML and repair law.go.kr's occasional undefined entities."""
    if isinstance(raw, str):
        raw = raw.encode("utf-8")
    try:
        return ElementTree.fromstring(raw), raw
    except ElementTree.ParseError as exc:
        repaired = repair_undefined_entities(raw)
        if repaired == raw:
            raise
        try:
            root = ElementTree.fromstring(repaired)
        except ElementTree.ParseError:
            raise exc
        logger.warning("Repaired undefined XML entity in %s", context)
        return root, repaired
