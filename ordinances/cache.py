"""File-based cache for raw ordinance API responses.

Detail XML is keyed by 자치법규일련번호 (MST), not 자치법규ID, so that every
revision of an ordinance can coexist on disk. The compiler reads identity
(자치법규ID) from the XML content, so the MST filename is purely a cache key.
"""

import os
from pathlib import Path

from core.atomic_io import atomic_write_bytes

from .config import ORDINANCE_CACHE_DIR

CACHE_DIR = Path(os.environ["LEGALIZE_ORDINANCE_CACHE_DIR"]) if os.environ.get("LEGALIZE_ORDINANCE_CACHE_DIR") else ORDINANCE_CACHE_DIR


def detail_path(mst: str) -> Path:
    return CACHE_DIR / f"{mst}.xml"


def get_detail(mst: str) -> bytes | None:
    path = detail_path(str(mst))
    return path.read_bytes() if path.exists() else None


def put_detail(mst: str, content: bytes) -> None:
    path = detail_path(str(mst))
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_bytes(path, content)


def list_cached_msts() -> list[str]:
    if not CACHE_DIR.exists():
        return []
    return sorted(p.stem for p in CACHE_DIR.glob("*.xml"))
