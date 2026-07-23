import re
from pathlib import Path

from core.git_engine import _run_git as _core_run_git
from core.git_engine import commit_with_historical_date
from .config import BOT_AUTHOR, LAW_REPO


def _run_git(*args: str, env: dict | None = None) -> str:
    return _core_run_git(*args, cwd=LAW_REPO, env=env)


def head_law_version(file_path: str) -> tuple[str, str, str] | None:
    """(공포일자, 공포번호, 법령MST) of ``file_path`` at HEAD, or None.

    공포일자 comes back without separators (YYYYMMDD) so it orders directly
    against the raw API value. 공포번호 is the tie-breaker for same-day
    amendments, matching the canonical ingestion order.
    """
    try:
        blob = _run_git("show", f"HEAD:{file_path}")
    except RuntimeError:
        return None
    prom = re.search(r"^공포일자:\s*(\S+)", blob, re.M)
    mst = re.search(r"^법령MST:\s*(\S+)", blob, re.M)
    if not prom or not mst:
        return None
    num = re.search(r"^공포번호:\s*'?([^'\s]*)'?", blob, re.M)
    return (
        prom.group(1).replace("-", ""),
        num.group(1) if num else "",
        mst.group(1),
    )


def commit_law(
    file_path: str,
    message: str,
    date: str,
    mst: str,
    *,
    author: str | None = None,
    skip_dedup: bool = False,
    extra_paths: list[str] | None = None,
) -> bool:
    key = None if skip_dedup else f"법령MST: {mst}"
    paths = [Path(file_path), *[Path(path) for path in (extra_paths or [])]]
    return commit_with_historical_date(
        LAW_REPO,
        paths,
        message,
        date,
        author=author or BOT_AUTHOR,
        dedup_grep_key=key,
    )
