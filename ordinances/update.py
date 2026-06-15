"""Incremental ordinance update entrypoint."""

import argparse
import logging
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

from .config import CONCURRENT_WORKERS, ORDINANCE_REPO
from .fetch_cache import fetch_all_current, fetch_details
from .import_ordinances import import_from_cache

logger = logging.getLogger(__name__)


def _date_range(days: int) -> str:
    today = datetime.now()
    since = today - timedelta(days=days)
    return f"{since:%Y%m%d}~{today:%Y%m%d}"


def _current_msts(entries: list[dict], limit: int | None = None) -> list[str]:
    msts = []
    seen = set()
    for entry in entries:
        mst = str(entry.get("자치법규일련번호", ""))
        if mst and mst not in seen:
            seen.add(mst)
            msts.append(mst)
    return msts[:limit] if limit is not None else msts


def _committed_msts(repo: Path) -> set[str]:
    if not (repo / ".git").exists():
        return set()
    result = subprocess.run(
        ["git", "log", "--all", "--format=%B"],
        cwd=repo,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return set()
    prefix = "자치법규일련번호: "
    return {
        line[len(prefix):].strip()
        for line in result.stdout.splitlines()
        if line.startswith(prefix) and line[len(prefix):].strip()
    }


def run(
    *,
    repo: Path = ORDINANCE_REPO,
    limit: int | None = None,
    workers: int = CONCURRENT_WORKERS,
    commit: bool = False,
    types: list[str] | None = None,
    org: str = "",
    sborg: str = "",
    days: int = 14,
) -> dict[str, int]:
    date_range = _date_range(days)
    logger.info("searching ordinances in date range %s", date_range)
    entries = fetch_all_current(types, org=org, sborg=sborg, max_entries=limit, date_range=date_range)
    current_msts = _current_msts(entries, limit)
    committed_msts = _committed_msts(repo) if commit else set()
    import_msts = [mst for mst in current_msts if mst not in committed_msts] if commit else current_msts
    fetch_counter = fetch_details(entries, workers=workers, limit=limit)
    cached, fetched, fetch_errors = fetch_counter.snapshot()
    import_stats = import_from_cache(
        repo,
        limit=None,
        commit=commit,
        msts=import_msts,
        skip_dedup=commit,
    )
    stats = {
        "cached": cached,
        "fetched": fetched,
        "fetch_errors": fetch_errors,
        **import_stats,
    }
    logger.info("ordinance update done: %s", stats)
    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch and import ordinances")
    parser.add_argument("--repo", type=Path, default=ORDINANCE_REPO)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--workers", type=int, default=CONCURRENT_WORKERS)
    parser.add_argument("--commit", action="store_true")
    parser.add_argument("--type", dest="types", action="append", help="자치법규종류. Repeatable.")
    parser.add_argument("--org", default="", help="Optional law.go.kr 광역 org code")
    parser.add_argument("--sborg", default="", help="Optional law.go.kr 기초 sborg code")
    parser.add_argument("--days", type=int, default=14, help="Look back this many days for daily updates")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    run(
        repo=args.repo,
        limit=args.limit,
        workers=args.workers,
        commit=args.commit,
        types=args.types,
        org=args.org,
        sborg=args.sborg,
        days=args.days,
    )


if __name__ == "__main__":
    main()
