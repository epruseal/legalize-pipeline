"""Incremental precedent update: fetch recent, convert, commit.

Searches for precedents with 선고일자 in the last N days, fetches
detail XML for any not already cached, probes a bounded 판례일련번호
window for late-published older judgments, converts to Markdown, and
commits each with 선고일자 as git date.

Usage:
    python -m precedents.update                  # Last 30 days
    python -m precedents.update --days 7         # Last 7 days
    python -m precedents.update --dry-run        # Report without writing
"""

import argparse
import logging
import re
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

from core.atomic_io import atomic_write_text

from . import cache
from .api_client import NoResultError, get_precedent_detail, search_precedents
from .config import PRECEDENT_KR_DIR
from .converter import (
    get_precedent_path,
    parse_precedent_xml,
    precedent_to_markdown,
    reset_path_registry,
)
from .git_engine import commit_precedent

logger = logging.getLogger(__name__)

_KST = timezone(timedelta(hours=9))
_SERIAL_RE = re.compile(r"^판례일련번호:\s*'?(?P<serial>\d+)'?\s*$")


def _date_range(days: int) -> str:
    """Return prncYd parameter for the last N days (YYYYMMDD~YYYYMMDD)."""
    end = datetime.now(_KST)
    start = end - timedelta(days=days)
    return f"{start.strftime('%Y%m%d')}~{end.strftime('%Y%m%d')}"


def _precedent_sort_key(prec: dict) -> tuple[str, str]:
    return (prec.get("선고일자", "") or "99999999", str(prec.get("판례일련번호", "") or ""))


def _frontmatter_serial(path: Path) -> str | None:
    try:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines()[:12]:
            match = _SERIAL_RE.match(line)
            if match:
                return match.group("serial")
    except OSError:
        return None
    return None


def _iter_repo_serials(output_dir: Path) -> list[int]:
    """Return current repository 판례일련번호 values without scanning .cache."""
    try:
        result = subprocess.run(
            ["git", "grep", "-h", "^판례일련번호:", "--", "*.md"],
            cwd=output_dir,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        result = None

    serials: list[int] = []
    if result is not None and result.returncode in (0, 1):
        lines = result.stdout.splitlines()
    else:
        lines = []
        for path in output_dir.rglob("*.md"):
            serial = _frontmatter_serial(path)
            if serial:
                lines.append(f"판례일련번호: '{serial}'")

    for line in lines:
        match = _SERIAL_RE.match(line)
        if match:
            serials.append(int(match.group("serial")))
    return serials


def _max_committed_precedent_id(output_dir: Path) -> int | None:
    serials = _iter_repo_serials(output_dir)
    return max(serials) if serials else None


def _collect_id_window_ids(
    output_dir: Path,
    *,
    overlap: int,
    probe_horizon: int,
) -> list[dict]:
    """Build a bounded 판례일련번호 candidate window around the repo high-watermark."""
    if overlap < 0 or probe_horizon < 0:
        raise ValueError("overlap and probe_horizon must be non-negative")
    if overlap == 0 and probe_horizon == 0:
        return []

    max_id = _max_committed_precedent_id(output_dir)
    if max_id is None:
        logger.info("Skipping ID window probe: no committed precedent IDs found")
        return []

    start = max(1, max_id - overlap)
    end = max_id + probe_horizon
    logger.info(f"Probing precedent ID window: {start}..{end} (max_seen={max_id})")
    return [
        {"판례일련번호": str(prec_id), "_source": "id_window"}
        for prec_id in range(start, end + 1)
    ]


def _merge_candidates(*groups: list[dict]) -> list[dict]:
    merged: dict[str, dict] = {}
    for group in groups:
        for item in group:
            prec_id = str(item.get("판례일련번호", "") or "")
            if not prec_id:
                continue
            source = item.get("_source", "date")
            if prec_id in merged:
                sources = set(str(merged[prec_id].get("_source", "")).split(","))
                sources.add(source)
                merged[prec_id]["_source"] = ",".join(sorted(s for s in sources if s))
                for key, value in item.items():
                    if key != "_source" and value and not merged[prec_id].get(key):
                        merged[prec_id][key] = value
            else:
                candidate = dict(item)
                candidate["_source"] = source
                merged[prec_id] = candidate
    return sorted(merged.values(), key=_precedent_sort_key)


def _resolve_output_path(path: str, parsed: dict, output_dir: Path) -> str:
    """Avoid overwriting an existing different serial when an incremental path collides."""
    abs_path = output_dir / path
    serial = parsed.get("판례정보일련번호", "")
    existing_serial = _frontmatter_serial(abs_path)
    if existing_serial is None or existing_serial == serial:
        return path

    base = Path(path)
    return str(base.with_name(f"{base.stem}_{serial}{base.suffix}"))


def _collect_recent_ids(days: int) -> list[dict]:
    """Search API for precedents with 선고일자 in the last N days."""
    date_range = _date_range(days)
    logger.info(f"Searching precedents in date range: {date_range}")

    all_precs: list[dict] = []
    seen: set[str] = set()
    page = 1

    while True:
        result = search_precedents(
            query="", page=page, display=100, sort="ddes",
            date_range=date_range,
        )
        total = result["totalCnt"]

        for prec in result["precedents"]:
            prec_id = prec.get("판례일련번호", "")
            if prec_id and prec_id not in seen:
                seen.add(prec_id)
                item = dict(prec)
                item["_source"] = "date"
                all_precs.append(item)

        logger.info(f"Search page {page}: {len(all_precs)}/{total}")

        if page * 100 >= total or not result["precedents"]:
            break
        page += 1

    all_precs.sort(key=_precedent_sort_key)
    return all_precs


def run(
    days: int = 180,
    dry_run: bool = False,
    output_dir: Path = PRECEDENT_KR_DIR,
    id_overlap: int = 0,
    id_probe_horizon: int = 0,
    refresh_recent: bool = False,
) -> dict:
    """Run incremental update. Returns stats dict."""
    reset_path_registry()

    # Step 1: find recent and high-ID-window precedents.
    recent = _collect_recent_ids(days)
    logger.info(f"Found {len(recent)} precedents in last {days} days")
    id_window = _collect_id_window_ids(
        output_dir,
        overlap=id_overlap,
        probe_horizon=id_probe_horizon,
    )
    logger.info(f"Found {len(id_window)} precedent ID-window candidates")

    candidates = _merge_candidates(recent, id_window)
    if not candidates:
        return {
            "found": 0,
            "date_found": 0,
            "id_window_found": 0,
            "committed": 0,
            "errors": 0,
            "no_result": 0,
        }

    # Known upstream no-result IDs (search lists them, detail cannot resolve).
    no_result_ids = cache.load_no_result_ids()

    # Step 2: fetch detail for each and write/commit (git detects zero-diff)
    committed = 0
    errors = 0
    no_result = 0

    for i, prec_meta in enumerate(candidates, 1):
        prec_id = prec_meta["판례일련번호"]
        source = str(prec_meta.get("_source", "date"))
        from_date_search = "date" in source.split(",")

        if prec_id in no_result_ids:
            no_result += 1
            continue

        try:
            # Fetch detail (cache-aware: skips if already cached)
            raw = get_precedent_detail(
                prec_id,
                refresh=refresh_recent and from_date_search,
            )

            parsed = parse_precedent_xml(raw)
            if parsed is None:
                logger.debug(f"Skipping error response: {prec_id}")
                continue

            path = get_precedent_path(parsed)
            path = _resolve_output_path(path, parsed, output_dir)
            abs_path = output_dir / path

            if dry_run:
                logger.info(f"[dry-run] Would write: {path}")
                continue

            md = precedent_to_markdown(parsed)
            abs_path.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_text(abs_path, md)

            result = commit_precedent(path, parsed, cwd=output_dir, skip_dedup=True)
            if result:
                committed += 1

        except NoResultError:
            if from_date_search:
                cache.add_no_result_id(prec_id)
                no_result_ids.add(prec_id)
                logger.debug(f"No-result prec_id {prec_id} recorded")
            else:
                logger.debug(f"No-result prec_id {prec_id} skipped for ID-window cache")
            no_result += 1

        except Exception as e:
            logger.error(f"Failed prec_id {prec_id}: {e}")
            errors += 1

        if i % 50 == 0:
            logger.info(
                f"Progress: {i}/{len(candidates)} "
                f"(committed={committed}, no_result={no_result}, errors={errors})"
            )

    stats = {
        "found": len(candidates),
        "date_found": len(recent),
        "id_window_found": len(id_window),
        "committed": committed,
        "errors": errors,
        "no_result": no_result,
    }
    logger.info(f"Update done: {stats}")
    return stats


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    parser = argparse.ArgumentParser(description="Incremental precedent update")
    parser.add_argument("--days", type=int, default=180, help="Lookback days (default: 180)")
    parser.add_argument("--dry-run", action="store_true", help="Report without writing")
    parser.add_argument("--output-dir", type=Path, default=PRECEDENT_KR_DIR)
    parser.add_argument(
        "--id-overlap",
        type=int,
        default=0,
        help="Probe this many IDs below the current repository max 판례일련번호",
    )
    parser.add_argument(
        "--id-probe-horizon",
        type=int,
        default=0,
        help="Probe this many IDs above the current repository max 판례일련번호",
    )
    parser.add_argument(
        "--refresh-recent",
        action="store_true",
        help="Bypass cache for date-search candidates to detect upstream edits",
    )
    args = parser.parse_args()

    stats = run(
        days=args.days,
        dry_run=args.dry_run,
        output_dir=args.output_dir,
        id_overlap=args.id_overlap,
        id_probe_horizon=args.id_probe_horizon,
        refresh_recent=args.refresh_recent,
    )
    print(
        f"found={stats['found']} date_found={stats['date_found']} "
        f"id_window_found={stats['id_window_found']} committed={stats['committed']} "
        f"no_result={stats['no_result']} errors={stats['errors']}"
    )
