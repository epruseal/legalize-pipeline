"""JSON checkpoint for resumable ordinance fetching."""

import json
import logging
import threading

from core.atomic_io import atomic_write_text

from .config import CACHE_ROOT

logger = logging.getLogger(__name__)

CHECKPOINT_FILE = CACHE_ROOT / ".ordinance-checkpoint.json"
_LOCK = threading.Lock()


def load() -> dict:
    if not CHECKPOINT_FILE.exists():
        return {}
    try:
        return json.loads(CHECKPOINT_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("Failed to load ordinance checkpoint: %s", e)
        return {}


def _write(data: dict) -> None:
    data.setdefault("schema_version", 2)
    CHECKPOINT_FILE.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(CHECKPOINT_FILE, json.dumps(data, ensure_ascii=False, indent=2))


def _page_key(ordinance_type: str, page: int, org: str = "", sborg: str = "") -> str:
    return f"{org or '*'}:{sborg or '*'}:{ordinance_type}:{page}"


def mark_page_processed(ordinance_type: str, page: int, org: str = "", sborg: str = "") -> None:
    with _LOCK:
        data = load()
        processed = set(data.get("processed_pages", []))
        processed.add(_page_key(str(ordinance_type), int(page), str(org), str(sborg)))
        data["processed_pages"] = sorted(processed)
        _write(data)


def is_page_processed(ordinance_type: str, page: int, org: str = "", sborg: str = "") -> bool:
    return _page_key(str(ordinance_type), int(page), str(org), str(sborg)) in set(load().get("processed_pages", []))


def mark_detail_processed(mst: str) -> None:
    with _LOCK:
        data = load()
        processed = set(data.get("processed_msts", []))
        processed.add(str(mst))
        data["processed_msts"] = sorted(processed, key=lambda value: int(value) if value.isdigit() else value)
        # Drop the legacy ID-keyed set; it no longer reflects per-version progress.
        data.pop("processed_ids", None)
        _write(data)


def get_processed_msts() -> set[str]:
    return set(load().get("processed_msts", []))


INDEX_FILE = CACHE_ROOT / ".ordinance-index.jsonl"


def save_crawl_index(entries: list[dict], *, nw: str, org: str = "", sborg: str = "") -> None:
    """Persist crawl entries to disk so restarts skip re-crawling."""
    INDEX_FILE.parent.mkdir(parents=True, exist_ok=True)
    key = f"{nw}:{org or '*'}:{sborg or '*'}"
    lines = []
    if INDEX_FILE.exists():
        for line in INDEX_FILE.read_text(encoding="utf-8").splitlines():
            try:
                rec = json.loads(line)
                if rec.get("_crawl_key") != key:
                    lines.append(line)
            except (json.JSONDecodeError, ValueError):
                pass
    lines.append(json.dumps({"_crawl_key": key, "entries": entries}, ensure_ascii=False))
    atomic_write_text(INDEX_FILE, "\n".join(lines) + "\n")


def load_crawl_index(*, nw: str, org: str = "", sborg: str = "") -> list[dict] | None:
    """Return previously saved crawl entries, or None if not cached."""
    if not INDEX_FILE.exists():
        return None
    key = f"{nw}:{org or '*'}:{sborg or '*'}"
    for line in INDEX_FILE.read_text(encoding="utf-8").splitlines():
        try:
            rec = json.loads(line)
            if rec.get("_crawl_key") == key:
                return rec["entries"]
        except (json.JSONDecodeError, ValueError, KeyError):
            pass
    return None
