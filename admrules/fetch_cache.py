"""Fetch and cache administrative rule detail XML responses.

Two collection modes:

* History (default): crawl the search API with ``nw=2`` (연혁), which returns one
  entry per revision — each with its own 행정규칙일련번호 (serial) — and fetch the
  detail XML for every serial. ``union_current`` additionally folds in ``nw=1`` so a
  brand-new current version that has not yet propagated to the 연혁 index is not
  missed. Detail is cached keyed by serial, so all revisions of one 행정규칙ID
  coexist and the compiler can emit a commit per revision.
* Current-only (``--skip-history``): crawl ``nw=1`` and fetch the current serial of
  each rule only (the previous behaviour), still keyed by serial.
"""

import argparse
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

from core.counter import Counter
from core.quota_budget import ensure_headroom, record_requests

from . import cache, checkpoint
from .api_client import get_admrule_detail, search_admrules
from .config import ADMRULE_TYPES, CONCURRENT_WORKERS

logger = logging.getLogger(__name__)


def _compact_date(value: str) -> str:
    return "".join(ch for ch in str(value) if ch.isdigit())


def _within_date_range(entry: dict, field: str, date_range: str) -> bool:
    if not date_range:
        return True
    try:
        start, end = date_range.split("~", 1)
    except ValueError:
        return True
    value = _compact_date(entry.get(field, ""))
    return bool(value) and start <= value <= end


def _crawl_search(
    knd_values: list[str] | None,
    *,
    nw: str,
    org: str,
    max_entries: int | None,
    date_range: str,
) -> list[dict]:
    """Crawl all search pages for a given ``nw`` across all requested knd values.

    Results are persisted to an index file after a full crawl so subsequent
    runs (e.g. after a restart) can skip re-crawling when no date_range filter
    is applied.
    """
    # Skip re-crawling when we have a saved full index (no date_range means
    # the saved result covers everything). Use org-level key (knd="") because
    # we crawl all kinds together and save the combined result.
    if not date_range and max_entries is None:
        cached = checkpoint.load_crawl_index(nw=nw, org=org)
        if cached is not None:
            wanted = set(knd_values or list(ADMRULE_TYPES))
            filtered = [e for e in cached if e.get("행정규칙종류코드", e.get("행정규칙종류", "")) in wanted or not knd_values]
            logger.info("admrul nw=%s: loaded %d entries from index (skipping crawl)", nw, len(filtered))
            return filtered

    entries: list[dict] = []
    history = nw == "2"
    for knd in knd_values or list(ADMRULE_TYPES):
        page = 1
        while True:
            result = search_admrules(page=page, display=100, knd=knd, org=org, date_range=date_range, history=history)
            record_requests(1, corpus="admrules")
            entries.extend(entry for entry in result["admrules"] if _within_date_range(entry, "발령일자", date_range))
            total = result["totalCnt"]
            logger.info(
                "admrul nw=%s knd=%s org=%s page=%s: %s/%s",
                nw,
                knd,
                org or "*",
                page,
                min(page * 100, total),
                total,
            )
            if max_entries is not None and len(entries) >= max_entries:
                return entries[:max_entries]
            if page * 100 >= total:
                break
            page += 1

    if not date_range and max_entries is None:
        checkpoint.save_crawl_index(entries, nw=nw, org=org)

    return entries


def fetch_all_current(
    knd_values: list[str] | None = None,
    org: str = "",
    max_entries: int | None = None,
    date_range: str = "",
) -> list[dict]:
    """Fetch current administrative rule list pages for the selected kinds."""
    return _crawl_search(knd_values, nw="1", org=org, max_entries=max_entries, date_range=date_range)


def fetch_version_index(
    knd_values: list[str] | None = None,
    *,
    org: str = "",
    max_entries: int | None = None,
    date_range: str = "",
    union_current: bool = True,
) -> list[dict]:
    """Collect one entry per rule revision via the 연혁 (nw=2) search index.

    Deduplicates by serial (행정규칙일련번호). When ``union_current`` is set, also
    crawls nw=1 and adds any current serial missing from the 연혁 index.
    """
    seen: set[str] = set()
    entries: list[dict] = []

    def _add(crawled: list[dict]) -> None:
        for entry in crawled:
            serial = str(entry.get("행정규칙일련번호", ""))
            if not serial or serial in seen:
                continue
            seen.add(serial)
            entries.append(entry)
            if max_entries is not None and len(entries) >= max_entries:
                return

    _add(
        _crawl_search(
            knd_values,
            nw="2",
            org=org,
            max_entries=None,
            date_range=date_range,
        )
    )
    if union_current and (max_entries is None or len(entries) < max_entries):
        _add(
            _crawl_search(
                knd_values,
                nw="1",
                org=org,
                max_entries=None,
                date_range=date_range,
            )
        )
    if max_entries is not None:
        return entries[:max_entries]
    return entries


def _fetch_detail_task(serial_no: str, counter: Counter) -> None:
    if cache.get_detail(serial_no) is not None:
        counter.inc("cached")
        return
    try:
        get_admrule_detail(serial_no)
        record_requests(1, corpus="admrules")
        checkpoint.mark_detail_processed(serial_no)
        counter.inc("fetched")
    except Exception:
        logger.exception("Failed admrule detail ID=%s", serial_no)
        counter.inc("errors")


def fetch_details(entries: list[dict], workers: int = CONCURRENT_WORKERS, limit: int | None = None) -> Counter:
    serials = []
    seen = set()
    for entry in entries:
        serial = str(entry.get("행정규칙일련번호", ""))
        if serial and serial not in seen:
            seen.add(serial)
            serials.append(serial)
    if limit is not None:
        serials = serials[:limit]

    counter = Counter()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(_fetch_detail_task, serial, counter) for serial in serials]
        for future in as_completed(futures):
            future.result()
    return counter


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch and cache admrule detail XML")
    parser.add_argument("--knd", action="append", choices=sorted(ADMRULE_TYPES), help="행정규칙종류 code 1..8. Repeatable.")
    parser.add_argument("--org", default="", help="Optional law.go.kr org code filter")
    parser.add_argument("--limit", type=int, help="Limit detail fetches for testing")
    parser.add_argument("--workers", type=int, default=CONCURRENT_WORKERS)
    parser.add_argument(
        "--skip-history",
        action="store_true",
        help="Fetch current (nw=1) versions only; skip the 연혁 (nw=2) crawl.",
    )
    parser.add_argument(
        "--no-union-current",
        action="store_true",
        help="With history, do not also crawl nw=1 to backfill missing current serials.",
    )
    parser.add_argument("--skip-quota-check", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    if args.skip_history:
        entries = fetch_all_current(knd_values=args.knd, org=args.org, max_entries=args.limit)
    else:
        entries = fetch_version_index(
            knd_values=args.knd,
            org=args.org,
            max_entries=args.limit,
            union_current=not args.no_union_current,
        )

    if not args.skip_quota_check:
        cached = set(cache.list_cached_serials())
        uncached = {str(e.get("행정규칙일련번호", "")) for e in entries} - cached - {""}
        ensure_headroom(expected_requests=len(uncached), corpus="admrules")

    counter = fetch_details(entries, workers=args.workers, limit=args.limit)
    logger.info("admrule fetch done: cached=%s fetched=%s errors=%s", *counter.snapshot())


if __name__ == "__main__":
    main()
