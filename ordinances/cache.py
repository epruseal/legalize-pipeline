"""File-based cache for raw ordinance API responses.

Historical ordinance detail responses are keyed by ``자치법규일련번호``.
Older cache files may still be keyed by ``자치법규ID``; callers decide which
cache key to use.
"""

import json
import os
import shutil
import threading
from pathlib import Path
from xml.etree import ElementTree

from core.atomic_io import atomic_write_bytes, atomic_write_text

from .config import ORDINANCE_CACHE_DIR

CACHE_DIR = Path(os.environ["LEGALIZE_ORDINANCE_CACHE_DIR"]) if os.environ.get("LEGALIZE_ORDINANCE_CACHE_DIR") else ORDINANCE_CACHE_DIR
HISTORY_DIR = CACHE_DIR / "history"
HISTORY_LIST_PATH = CACHE_DIR / "ordinance_history_entries.json"
_NO_RESULT_SERIALS_FILENAME = "_no_result_serials.txt"
_no_result_lock = threading.Lock()


def detail_path(cache_key: str, *, historical: bool = False) -> Path:
    if cache_key.startswith("history/"):
        return HISTORY_DIR / f"{cache_key.removeprefix('history/')}.xml"
    parent = HISTORY_DIR if historical else CACHE_DIR
    return parent / f"{cache_key}.xml"


def _serial_from_raw(raw: bytes) -> str:
    try:
        return (ElementTree.fromstring(raw).findtext(".//자치법규일련번호") or "").strip()
    except ElementTree.ParseError:
        return ""


def get_detail(cache_key: str, *, historical: bool = False) -> bytes | None:
    key = str(cache_key)
    path = detail_path(key, historical=historical)
    if path.exists():
        return path.read_bytes()
    if historical:
        legacy_path = detail_path(key)
        if legacy_path.exists():
            raw = legacy_path.read_bytes()
            if _serial_from_raw(raw) == key:
                return raw
    return None


def put_detail(cache_key: str, content: bytes, *, historical: bool = False) -> None:
    path = detail_path(str(cache_key), historical=historical)
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_bytes(path, content)


def list_cached_ids() -> list[str]:
    if not CACHE_DIR.exists():
        return []
    ids = [p.stem for p in CACHE_DIR.glob("*.xml")]
    ids.extend(f"history/{p.stem}" for p in HISTORY_DIR.glob("*.xml"))
    return sorted(ids)


def seed_history_from_current() -> dict[str, int]:
    """Preserve legacy ID-key files while seeding serial-key history files."""
    stats = {"seeded": 0, "cached": 0, "skipped": 0, "errors": 0}
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    for source in CACHE_DIR.glob("*.xml"):
        try:
            raw = source.read_bytes()
            serial = _serial_from_raw(raw)
            if not serial:
                stats["skipped"] += 1
                continue
            target = detail_path(serial, historical=True)
            if target.exists():
                stats["cached"] += 1
                continue
            try:
                os.link(source, target)
            except OSError:
                shutil.copy2(source, target)
            stats["seeded"] += 1
        except OSError:
            stats["errors"] += 1
    return stats


def get_history_entries() -> list[dict]:
    if not HISTORY_LIST_PATH.exists():
        return []
    try:
        data = json.loads(HISTORY_LIST_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    return data if isinstance(data, list) else []


def put_history_entries(entries: list[dict]) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    atomic_write_text(
        HISTORY_LIST_PATH,
        json.dumps(entries, ensure_ascii=False, separators=(",", ":")),
    )


def _no_result_serials_path() -> Path:
    return CACHE_DIR / _NO_RESULT_SERIALS_FILENAME


def load_no_result_serials() -> set[str]:
    """Load history serials that the detail API permanently returns as 404."""
    path = _no_result_serials_path()
    if not path.exists():
        return set()
    return {line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()}


def add_no_result_serial(serial: str) -> None:
    """Append a permanently missing history serial to the negative cache."""
    path = _no_result_serials_path()
    with _no_result_lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as file:
            file.write(f"{serial}\n")
