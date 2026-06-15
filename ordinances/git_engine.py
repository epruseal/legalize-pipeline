"""Ordinance-specific shim for shared historical-date commits."""

from pathlib import Path

from core.config import BOT_AUTHOR
from core.git_engine import commit_with_historical_date


def commit_ordinance(
    repo_dir: Path,
    file_path: str,
    message: str,
    date: str,
    mst: str,
    *,
    skip_dedup: bool = False,
    stale_paths: list[str] | None = None,
) -> bool:
    # Dedup on MST (자치법규일련번호) so distinct revisions of one 자치법규ID are
    # each committed; the key must match the line emitted in build_commit_msg.
    key = None if skip_dedup else f"자치법규일련번호: {mst}"
    paths = [Path(file_path), *[Path(path) for path in stale_paths or []]]
    return commit_with_historical_date(repo_dir, paths, message, date, author=BOT_AUTHOR, dedup_grep_key=key)
