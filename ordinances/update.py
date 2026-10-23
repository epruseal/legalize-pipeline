"""Incremental ordinance update entrypoint."""

import argparse
import logging
import os
from datetime import datetime, timedelta
from pathlib import Path

from core.github_actions import report_partial_fetch

from . import cache, deferred_revisions
from .config import CONCURRENT_WORKERS, ORDINANCE_REPO
from .converter import parse_ordinance_xml
from .fetch_cache import fetch_all_current, fetch_details, fetch_history_for_entries
from .import_ordinances import import_from_cache
from .git_engine import committed_metadata as _committed_metadata

logger = logging.getLogger(__name__)


def _date_range(days: int) -> str:
    today = datetime.now()
    since = today - timedelta(days=days)
    return f"{since:%Y%m%d}~{today:%Y%m%d}"


def _current_serials(entries: list[dict], limit: int | None = None) -> list[str]:
    serials = []
    seen = set()
    for entry in entries:
        serial = str(entry.get("자치법규일련번호", "")) or str(entry.get("자치법규ID", ""))
        if serial and serial not in seen:
            seen.add(serial)
            serials.append(serial)
    return serials[:limit] if limit is not None else serials


def _compact_date(value: str) -> str:
    return "".join(ch for ch in str(value) if ch.isdigit())


def _within_date_range(entry: dict, date_range: str) -> bool:
    try:
        start, end = date_range.split("~", 1)
    except ValueError:
        return True
    value = _compact_date(entry.get("공포일자", ""))
    return bool(value) and start <= value <= end


def _import_serials(entries: list[dict], repo: Path, date_range: str, *, commit: bool) -> list[str]:
    current_serials = _current_serials(entries)
    if not commit:
        return current_serials

    committed_serials, committed_identities = _committed_metadata(repo)
    serials = []
    for entry in entries:
        serial = str(entry.get("자치법규일련번호", "")) or str(entry.get("자치법규ID", ""))
        identity = str(entry.get("자치법규ID", ""))
        if not serial or serial in committed_serials or serial in serials:
            continue
        if identity not in committed_identities or _within_date_range(entry, date_range):
            serials.append(serial)
    return serials


def _deferred_serials(serials: list[str]) -> set[str]:
    deferred = set()
    for serial in serials:
        if serial not in deferred_revisions.load_entries():
            continue
        raw = cache.get_detail(serial, historical=True)
        if not raw:
            continue
        try:
            detail = parse_ordinance_xml(raw)
        except ValueError as error:
            entry = deferred_revisions.accepted_entry(serial, raw, error)
            if entry is None:
                continue
            deferred.add(serial)
            message = f"MST={serial}: {entry['reason']} Review expires {entry['expires_on']}. Revision not published."
            logger.warning("Deferred ordinance revision %s", message)
            print(f"::warning title=Deferred ordinance revision::{message}")
            summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
            if summary_path:
                with Path(summary_path).open("a", encoding="utf-8") as summary:
                    summary.write(f"\nDeferred ordinance revision {message}\n")
                    for url in entry["sources"]:
                        summary.write(f"\nSource: {url}\n")
        else:
            entry = deferred_revisions.load_entries()[serial]
            if any(str(detail["metadata"].get(key, "")) != entry[key]
                   for key in ("자치법규ID", "자치법규일련번호")):
                raise ValueError(f"Reviewed ordinance revision {serial} returned a different identity")
            if not any(article["조문내용"].strip() for article in detail["articles"]):
                raise ValueError(f"Reviewed ordinance revision {serial} lost its article text")
    return deferred


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
    current_entries = fetch_all_current(types, org=org, sborg=sborg, max_entries=limit, date_range=date_range)
    entries = fetch_history_for_entries(current_entries, types) if current_entries else []
    if not entries:
        entries = current_entries
    pending = []
    if commit and limit is None and not (types or org or sborg):
        committed_serials, _ = _committed_metadata(repo)
        selected = set(_current_serials(entries))
        pending = [entry for serial, entry in deferred_revisions.load_entries().items()
                   if serial not in committed_serials]
        entries = entries + [entry for entry in pending if entry["자치법규일련번호"] not in selected]
    import_serials = _import_serials(entries, repo, date_range, commit=commit)
    import_serials.extend(serial for serial in _current_serials(pending) if serial not in import_serials)
    import_serial_set = set(import_serials)
    fetch_entries = [
        entry
        for entry in entries
        if (str(entry.get("자치법규일련번호", "")) or str(entry.get("자치법규ID", ""))) in import_serial_set
    ]
    fetch_counter = fetch_details(fetch_entries, workers=workers, refresh_cached=commit)
    cached, fetched, fetch_errors = fetch_counter.snapshot()
    deferred = _deferred_serials(import_serials) if commit and not fetch_errors else set()
    import_stats = import_from_cache(
        repo,
        limit=None,
        commit=commit,
        serials=[serial for serial in import_serials if serial not in deferred] if not fetch_errors else [],
        skip_dedup=False,
    )
    stats = {
        "cached": cached,
        "fetched": fetched,
        "fetch_errors": fetch_errors,
        "deferred": len(deferred),
        **import_stats,
    }
    if commit:
        committed_serials, _ = _committed_metadata(repo)
        unavailable = {serial for serial in import_serial_set & cache.load_no_result_serials()
                       if cache.get_detail(serial, historical=True) is None}
        missing = import_serial_set - committed_serials - unavailable - deferred
        stats["missing"] = len(missing)
        if missing:
            logger.error("Selected ordinance revisions are missing from HEAD: %s", ", ".join(sorted(missing)))
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
    stats = run(
        repo=args.repo,
        limit=args.limit,
        workers=args.workers,
        commit=args.commit,
        types=args.types,
        org=args.org,
        sborg=args.sborg,
        days=args.days,
    )
    report_partial_fetch("Ordinances", stats)
    if stats["errors"] or stats["fetch_errors"] or stats.get("missing", 0):
        raise SystemExit(f"Ordinance update failed: errors={stats['errors']}, missing={stats.get('missing', 0)}, fetch_errors={stats['fetch_errors']}")


if __name__ == "__main__":
    main()
