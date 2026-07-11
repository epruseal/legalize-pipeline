"""Known, expiring upstream ordinance detail failures."""

from datetime import date
from functools import lru_cache
from pathlib import Path

import yaml

_DEFAULT_PATH = Path(__file__).parent / "data" / "known_detail_failures.yaml"


@lru_cache(maxsize=1)
def load_allowlist() -> dict[str, dict]:
    if not _DEFAULT_PATH.exists():
        return {}
    data = yaml.safe_load(_DEFAULT_PATH.read_text(encoding="utf-8")) or {}
    return {
        str(entry["serial"]): entry
        for entry in data.get("entries", [])
        if isinstance(entry, dict) and entry.get("serial")
    }


def is_listed(serial: str, today: date | None = None) -> bool:
    entry = load_allowlist().get(str(serial))
    if entry is None:
        return False
    return date.fromisoformat(str(entry["expires_on"])) > (today or date.today())


def accepted_entry(serial: str, error: BaseException, today: date | None = None) -> dict | None:
    entry = load_allowlist().get(str(serial))
    if entry is None or not is_listed(serial, today=today):
        return None
    return entry if str(entry["expected_error"]) in str(error) else None
