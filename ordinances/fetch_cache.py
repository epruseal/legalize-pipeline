"""Fetch and cache ordinance detail XML responses.

Two collection modes:

* History (default): crawl the search API with ``nw=2`` (연혁), which returns one
  entry per revision — each with its own 자치법규일련번호 (MST) — and fetch the
  detail XML for every MST. ``union_current`` additionally folds in ``nw=1`` so a
  brand-new current version that has not yet propagated to the 연혁 index is not
  missed. Detail is cached keyed by MST, so all revisions of one 자치법규ID
  coexist and the compiler can emit a commit per revision.
* Current-only (``--skip-history``): crawl ``nw=1`` and fetch the current MST of
  each ordinance only (the previous behaviour), still keyed by MST.
"""

import argparse
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

from core.counter import Counter
from core.quota_budget import ensure_headroom, record_requests

from . import cache, checkpoint
from .api_client import get_ordinance_detail, search_ordinances
from .config import API_TYPES, CONCURRENT_WORKERS
from .failures import append_failure

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
    ordinance_types: list[str] | None,
    *,
    nw: str,
    org: str,
    sborg: str,
    display: int,
    max_entries: int | None,
    date_range: str,
) -> list[dict]:
    """Crawl all search pages for a given ``nw`` and filter selected types client-side.

    The law.go.kr ordinance ``knd`` parameter has shown inconsistent behavior
    during probes. Fetching unfiltered pages once and classifying by
    ``자치법규종류`` avoids duplicate detail fetches and matches the plan's
    fallback policy.

    Results are persisted to an index file after a full crawl so subsequent
    runs (e.g. after a restart) can skip re-crawling when no date_range filter
    is applied.
    """
    # Skip re-crawling when we have a saved full index (no date_range means
    # the saved result covers everything).
    if not date_range and max_entries is None:
        cached = checkpoint.load_crawl_index(nw=nw, org=org, sborg=sborg)
        if cached is not None:
            wanted = set(ordinance_types or API_TYPES)
            filtered = [e for e in cached if e.get("자치법규종류", "") in wanted]
            logger.info("ordin nw=%s: loaded %d entries from index (skipping crawl)", nw, len(filtered))
            return filtered

    entries: list[dict] = []
    wanted = set(ordinance_types or API_TYPES)
    page = 1
    while True:
        result = search_ordinances(page=page, display=display, org=org, sborg=sborg, date_range=date_range, nw=nw)
        record_requests(1, corpus="ordinances")
        entries.extend(
            entry
            for entry in result["ordinances"]
            if entry.get("자치법규종류", "") in wanted and _within_date_range(entry, "공포일자", date_range)
        )
        total = result["totalCnt"]
        logger.info(
            "ordin nw=%s types=%s org=%s sborg=%s page=%s: %s/%s",
            nw,
            ",".join(sorted(wanted)),
            org or "*",
            sborg or "*",
            page,
            min(page * display, total),
            total,
        )
        if max_entries is not None and len(entries) >= max_entries:
            return entries[:max_entries]
        if page * display >= total:
            break
        page += 1

    if not date_range and max_entries is None:
        checkpoint.save_crawl_index(entries, nw=nw, org=org, sborg=sborg)

    return entries


def fetch_all_current(
    ordinance_types: list[str] | None = None,
    *,
    org: str = "",
    sborg: str = "",
    display: int = 100,
    max_entries: int | None = None,
    date_range: str = "",
) -> list[dict]:
    """Fetch current (nw=1) ordinance list pages, filtered by selected types."""
    return _crawl_search(
        ordinance_types,
        nw="1",
        org=org,
        sborg=sborg,
        display=display,
        max_entries=max_entries,
        date_range=date_range,
    )


def fetch_version_index(
    ordinance_types: list[str] | None = None,
    *,
    org: str = "",
    sborg: str = "",
    display: int = 100,
    max_entries: int | None = None,
    date_range: str = "",
    union_current: bool = True,
) -> list[dict]:
    """Collect one entry per ordinance revision via the 연혁 (nw=2) search index.

    Deduplicates by MST (자치법규일련번호). When ``union_current`` is set, also
    crawls nw=1 and adds any current MST missing from the 연혁 index.
    """
    seen: set[str] = set()
    entries: list[dict] = []

    def _add(crawled: list[dict]) -> None:
        for entry in crawled:
            mst = str(entry.get("자치법규일련번호", ""))
            if not mst or mst in seen:
                continue
            seen.add(mst)
            entries.append(entry)
            if max_entries is not None and len(entries) >= max_entries:
                return

    _add(
        _crawl_search(
            ordinance_types,
            nw="2",
            org=org,
            sborg=sborg,
            display=display,
            max_entries=None,
            date_range=date_range,
        )
    )
    if union_current and (max_entries is None or len(entries) < max_entries):
        _add(
            _crawl_search(
                ordinance_types,
                nw="1",
                org=org,
                sborg=sborg,
                display=display,
                max_entries=None,
                date_range=date_range,
            )
        )
    if max_entries is not None:
        return entries[:max_entries]
    return entries


def _fetch_detail_task(mst: str, ordinance_id: str, counter: Counter) -> None:
    if cache.get_detail(mst) is not None:
        counter.inc("cached")
        return
    try:
        get_ordinance_detail(ordinance_id, mst=mst)
        record_requests(1, corpus="ordinances")
        counter.inc("fetched")
    except Exception:
        logger.exception("Failed ordinance detail MST=%s ID=%s", mst, ordinance_id)
        append_failure({"자치법규ID": ordinance_id, "MST": mst, "reason": "detail_fetch_failed"})
        counter.inc("errors")


def fetch_details(entries: list[dict], workers: int = CONCURRENT_WORKERS, limit: int | None = None) -> Counter:
    pairs: list[tuple[str, str]] = []
    seen: set[str] = set()
    for entry in entries:
        mst = str(entry.get("자치법규일련번호", ""))
        ordinance_id = str(entry.get("자치법규ID", ""))
        # Fall back to ID when an entry carries no MST (defensive; nw search
        # results always include 자치법규일련번호).
        key = mst or ordinance_id
        if key and key not in seen:
            seen.add(key)
            pairs.append((mst, ordinance_id))
    if limit is not None:
        pairs = pairs[:limit]

    counter = Counter()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [
            pool.submit(_fetch_detail_task, mst or ordinance_id, ordinance_id, counter)
            for mst, ordinance_id in pairs
        ]
        for future in as_completed(futures):
            future.result()
    return counter


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch and cache ordinance detail XML")
    parser.add_argument("--type", dest="types", action="append", choices=API_TYPES, help="자치법규종류. Repeatable.")
    parser.add_argument("--org", default="", help="Optional law.go.kr 광역 org code")
    parser.add_argument("--sborg", default="", help="Optional law.go.kr 기초 sborg code")
    parser.add_argument("--display", type=int, default=100)
    parser.add_argument("--limit", type=int, help="Limit detail fetches for testing/probe runs")
    parser.add_argument("--workers", type=int, default=CONCURRENT_WORKERS)
    parser.add_argument(
        "--skip-history",
        action="store_true",
        help="Fetch current (nw=1) versions only; skip the 연혁 (nw=2) crawl.",
    )
    parser.add_argument(
        "--no-union-current",
        action="store_true",
        help="With history, do not also crawl nw=1 to backfill missing current MSTs.",
    )
    parser.add_argument("--skip-quota-check", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    if args.skip_history:
        entries = fetch_all_current(args.types, org=args.org, sborg=args.sborg, display=args.display, max_entries=args.limit)
    else:
        entries = fetch_version_index(
            args.types,
            org=args.org,
            sborg=args.sborg,
            display=args.display,
            max_entries=args.limit,
            union_current=not args.no_union_current,
        )

    if not args.skip_quota_check:
        cached = set(cache.list_cached_msts())
        uncached = {str(e.get("자치법규일련번호", "")) for e in entries} - cached - {""}
        ensure_headroom(expected_requests=len(uncached), corpus="ordinances")

    counter = fetch_details(entries, workers=args.workers, limit=args.limit)
    logger.info("ordinance fetch done: cached=%s fetched=%s errors=%s", *counter.snapshot())


if __name__ == "__main__":
    main()
