"""Tests for ordinances/checkpoint.py."""

from ordinances import checkpoint


def test_checkpoint_round_trip(tmp_path, monkeypatch):
    monkeypatch.setattr(checkpoint, "CHECKPOINT_FILE", tmp_path / "checkpoint.json")

    checkpoint.mark_page_processed("조례", 1, "6110000", "3160000")
    checkpoint.mark_detail_processed("1013533")

    assert checkpoint.is_page_processed("조례", 1, "6110000", "3160000")
    assert checkpoint.get_processed_msts() == {"1013533"}
