"""Ordinance-specific shim for shared historical-date commits."""

import subprocess
from pathlib import Path

from core.config import BOT_AUTHOR
from core.git_engine import commit_with_historical_date


def commit_ordinance(
    repo_dir: Path,
    file_path: str,
    message: str,
    date: str,
    ordinance_id: str,
    serial_no: str,
    *,
    skip_dedup: bool = False,
    stale_paths: list[str] | None = None,
) -> bool:
    del ordinance_id
    key = None if skip_dedup else f"자치법규일련번호: {serial_no}"
    paths = [Path(file_path), *[Path(path) for path in stale_paths or []]]
    return commit_with_historical_date(repo_dir, paths, message, date, author=BOT_AUTHOR, dedup_grep_key=key)


def commit_ordinance_deletion(
    repo_dir: Path,
    file_path: str | None,
    message: str,
    date: str,
    serial_no: str,
    *,
    skip_dedup: bool = False,
) -> bool:
    key = None if skip_dedup else f"자치법규일련번호: {serial_no}"
    return commit_with_historical_date(
        repo_dir,
        [Path(file_path)] if file_path else [],
        message,
        date,
        author=BOT_AUTHOR,
        dedup_grep_key=key,
        allow_empty=file_path is None,
    )


def committed_metadata(repo: Path) -> tuple[set[str], set[str]]:
    if not (repo / ".git").exists():
        return set(), set()
    result = subprocess.run(
        ["git", "log", "HEAD", "--format=%B"],
        cwd=repo,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return set(), set()
    serial_prefix = "자치법규일련번호: "
    identity_prefix = "자치법규ID: "
    serials = set()
    identities = set()
    for line in result.stdout.splitlines():
        if line.startswith(serial_prefix) and line[len(serial_prefix):].strip():
            serials.add(line[len(serial_prefix):].strip())
        elif line.startswith(identity_prefix) and line[len(identity_prefix):].strip():
            identities.add(line[len(identity_prefix):].strip())
    return serials, identities
