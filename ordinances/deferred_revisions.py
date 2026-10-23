"""Exact, expiring source defects reviewed for incremental publication only."""

import hashlib
import re
from datetime import date
from functools import lru_cache
from pathlib import Path
from xml.etree import ElementTree

import yaml

from core.xml import parse_xml

_PATH = Path(__file__).parent / "data" / "deferred_revisions.yaml"


@lru_cache(maxsize=1)
def load_entries() -> dict[str, dict]:
    data = yaml.safe_load(_PATH.read_text(encoding="utf-8"))
    return {str(entry["자치법규일련번호"]): entry for entry in data["entries"]}


def attachment_locator_fingerprint(raw: bytes) -> str:
    """Hash the XML with only numeric attachment locators masked."""
    root, _raw = parse_xml(raw, context="deferred ordinance revision")
    for attachment in root.findall("./별표/별표단위"):
        if re.fullmatch(r"[0-9]+", attachment.get("별표키", "")):
            attachment.set("별표키", "<locator>")
        for link in attachment.findall("별표첨부파일명"):
            if link.text:
                link.text = re.sub(
                    r"\A(http://www\.law\.go\.kr/flDownload\.do\?gubun=ELIS&flSeq=)[0-9]+(?=&flNm=)",
                    r"\1<locator>",
                    link.text,
                )
    return hashlib.sha256(ElementTree.tostring(root, encoding="utf-8")).hexdigest()


def accepted_entry(serial: str, raw: bytes, error: ValueError, today: date | None = None) -> dict | None:
    entry = load_entries().get(str(serial))
    if entry is None or date.fromisoformat(entry["expires_on"]) <= (today or date.today()):
        return None
    if str(error).strip() != entry["expected_error"]:
        return None
    if hashlib.sha256(raw).hexdigest() == entry["sha256"]:
        return entry
    fingerprint = entry.get("attachment_locator_sha256")
    if fingerprint and attachment_locator_fingerprint(raw) == fingerprint:
        return entry
    return None
