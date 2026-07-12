"""Validate persistent cache file counts without accepting regressions."""

from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path


SUBDIRS = ("detail", "history", "precedent", "images", "admrule", "ordinance")


def count_files(cache_dir: Path) -> dict[str, int]:
    return {
        subdir: sum(len(files) for _, _, files in os.walk(cache_dir / subdir))
        for subdir in SUBDIRS
    }


def regressions(
    counts: dict[str, int], baseline: dict[str, int], tolerance: float = 0.01
) -> list[tuple[str, int, int, int]]:
    failures = []
    for subdir in SUBDIRS:
        previous = int(baseline.get(subdir, 0))
        threshold = math.ceil(previous * (1 - tolerance))
        current = counts[subdir]
        if current < threshold:
            failures.append((subdir, current, threshold, previous))
    return failures


def write_json(path: Path, payload: dict[str, int]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def validate_and_update(cache_dir: Path, output: Path) -> dict[str, int]:
    baseline_path = cache_dir / ".cache-baseline.json"
    counts = count_files(cache_dir)
    baseline = json.loads(baseline_path.read_text(encoding="utf-8")) if baseline_path.exists() else {}

    for subdir, current in counts.items():
        print(f"Cache {subdir}: {current} files")
        previous = int(baseline.get(subdir, 0))
        if current < previous:
            print(f"::warning::Cache count dropped in {subdir}: {current} < baseline {previous}")

    failures = regressions(counts, baseline)
    if failures:
        for subdir, current, threshold, previous in failures:
            print(
                f"::error::Cache regression in {subdir}: {current} < threshold "
                f"{threshold} (baseline {previous})"
            )
        raise RuntimeError(f"cache file-count regressions: {len(failures)}")

    write_json(output, counts)
    write_json(baseline_path, counts)
    print(f"Wrote {output}: {counts}")
    return counts


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cache-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("cache-baseline.json"))
    args = parser.parse_args()
    validate_and_update(args.cache_dir, args.output)


if __name__ == "__main__":
    main()
