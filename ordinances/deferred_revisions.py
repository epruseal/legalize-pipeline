"""Exact, expiring source defects reviewed for incremental publication only."""

import hashlib
from datetime import date
from functools import lru_cache
from pathlib import Path

import yaml

_PATH = Path(__file__).parent / "data" / "deferred_revisions.yaml"


@lru_cache(maxsize=1)
def load_entries() -> dict[str, dict]:
    data = yaml.safe_load(_PATH.read_text(encoding="utf-8"))
    return {str(entry["자치법규일련번호"]): entry for entry in data["entries"]}


def accepted_entry(serial: str, raw: bytes, error: ValueError, today: date | None = None) -> dict | None:
    entry = load_entries().get(str(serial))
    if entry is None or date.fromisoformat(entry["expires_on"]) <= (today or date.today()):
        return None
    if str(error).strip() != entry["expected_error"]:
        return None
    return entry if hashlib.sha256(raw).hexdigest() == entry["sha256"] else None
