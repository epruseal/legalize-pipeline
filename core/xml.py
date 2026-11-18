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


def _without_nul(raw: bytes) -> tuple[bytes, int]:
    """Return the bytes without NUL and the number of removed NUL bytes."""
    count = raw.count(b"\x00")
    return (raw.replace(b"\x00", b""), count) if count else (raw, 0)


def _warn_removed_nul(count: int, context: str) -> None:
    if count:
        logger.warning("Removed %d NUL character(s) from %s before parsing", count, context)


def fromstring_without_nul(raw: bytes | str, *, context: str) -> ElementTree.Element:
    """Remove NUL from a copy of the XML and parse the copy.

    This function does not repair entities. The caller keeps ``raw``
    unchanged. The function logs a warning only when the parse succeeds
    and the copy had at least one NUL.
    """
    if isinstance(raw, str):
        raw = raw.encode("utf-8")
    cleaned, count = _without_nul(raw)
    root = ElementTree.fromstring(cleaned)
    _warn_removed_nul(count, context)
    return root


def parse_xml(
    raw: bytes | str, *, context: str = "XML", strip_nul: bool = False
) -> tuple[ElementTree.Element, bytes]:
    """Parse XML and repair law.go.kr's occasional undefined entities.

    You can store the returned bytes. They are the input, or the input with
    only the undefined entities repaired. With ``strip_nul=True``, the
    function removes NUL only from the bytes that it gives to the parser.
    The returned bytes can still hold NUL. Read them again with
    ``strip_nul=True`` or ``fromstring_without_nul``. Each successful parse
    that removes NUL logs a warning.
    """
    if isinstance(raw, str):
        raw = raw.encode("utf-8")
    prepare = _without_nul if strip_nul else (lambda data: (data, 0))
    cleaned, count = prepare(raw)
    try:
        root = ElementTree.fromstring(cleaned)
    except ElementTree.ParseError as exc:
        repaired = repair_undefined_entities(raw)
        if repaired == raw:
            raise
        try:
            root = ElementTree.fromstring(prepare(repaired)[0])
        except ElementTree.ParseError:
            raise exc
        logger.warning("Repaired undefined XML entity in %s", context)
        _warn_removed_nul(count, context)
        return root, repaired
    _warn_removed_nul(count, context)
    return root, raw
