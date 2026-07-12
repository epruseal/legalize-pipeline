import json
from pathlib import Path

import pytest

from cache.baseline import SUBDIRS, validate_and_update


def _write_files(cache_dir: Path, subdir: str, count: int) -> None:
    directory = cache_dir / subdir
    directory.mkdir(parents=True, exist_ok=True)
    for index in range(count):
        (directory / f"{index}.data").write_text("x", encoding="utf-8")


def _write_baseline(cache_dir: Path, **counts: int) -> Path:
    baseline = {subdir: counts.get(subdir, 0) for subdir in SUBDIRS}
    path = cache_dir / ".cache-baseline.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(baseline), encoding="utf-8")
    return path


def test_validate_and_update_creates_initial_baseline(tmp_path: Path):
    cache_dir = tmp_path / "cache"
    output = tmp_path / "baseline.json"
    _write_files(cache_dir, "ordinance", 2)

    counts = validate_and_update(cache_dir, output)

    assert counts == {**{subdir: 0 for subdir in SUBDIRS}, "ordinance": 2}
    assert json.loads(output.read_text(encoding="utf-8")) == counts
    assert json.loads((cache_dir / ".cache-baseline.json").read_text(encoding="utf-8")) == counts


def test_validate_and_update_accepts_growth_and_updates_baseline(tmp_path: Path):
    cache_dir = tmp_path / "cache"
    output = tmp_path / "baseline.json"
    _write_baseline(cache_dir, ordinance=2)
    _write_files(cache_dir, "ordinance", 3)

    counts = validate_and_update(cache_dir, output)

    assert counts["ordinance"] == 3
    assert json.loads((cache_dir / ".cache-baseline.json").read_text(encoding="utf-8"))["ordinance"] == 3


def test_validate_and_update_accepts_drop_within_one_percent(tmp_path: Path):
    cache_dir = tmp_path / "cache"
    output = tmp_path / "baseline.json"
    _write_baseline(cache_dir, ordinance=100)
    _write_files(cache_dir, "ordinance", 99)

    counts = validate_and_update(cache_dir, output)

    assert counts["ordinance"] == 99


def test_validate_and_update_rejects_drop_over_one_percent_after_rounding(tmp_path: Path):
    cache_dir = tmp_path / "cache"
    output = tmp_path / "baseline.json"
    _write_baseline(cache_dir, ordinance=101)
    _write_files(cache_dir, "ordinance", 99)

    with pytest.raises(RuntimeError, match="cache file-count regressions: 1"):
        validate_and_update(cache_dir, output)


def test_regression_does_not_replace_last_good_baseline(tmp_path: Path):
    cache_dir = tmp_path / "cache"
    output = tmp_path / "baseline.json"
    baseline_path = _write_baseline(cache_dir, ordinance=100)
    original = baseline_path.read_bytes()
    output.write_text("previous artifact\n", encoding="utf-8")
    _write_files(cache_dir, "ordinance", 98)

    with pytest.raises(RuntimeError, match="cache file-count regressions: 1"):
        validate_and_update(cache_dir, output)

    assert baseline_path.read_bytes() == original
    assert output.read_text(encoding="utf-8") == "previous artifact\n"
