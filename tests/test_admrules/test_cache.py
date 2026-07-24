"""Tests for admrules/cache.py."""

import importlib

import pytest


@pytest.fixture
def admrule_cache(tmp_path, monkeypatch):
    """Reload admrules.cache against a tmp CACHE_DIR, then restore it.

    CACHE_DIR is bound at import time from the environment, so exercising the
    real cache dir requires a reload. Without undoing it the module keeps
    pointing at this test's tmp_path for the rest of the session — every later
    test (and any prune_details call) then operates on a dead directory.
    """
    monkeypatch.setenv("LEGALIZE_ADMRULE_CACHE_DIR", str(tmp_path))
    import admrules.cache as cache

    cache = importlib.reload(cache)
    try:
        yield cache
    finally:
        monkeypatch.delenv("LEGALIZE_ADMRULE_CACHE_DIR", raising=False)
        importlib.reload(cache)


def test_cache_round_trip(admrule_cache):
    admrule_cache.put_detail("123", b"<xml />")

    assert admrule_cache.get_detail("123") == b"<xml />"
    assert admrule_cache.list_cached_serials() == ["123"]


def test_reload_fixture_restores_real_cache_dir():
    """test_cache_round_trip must not leave CACHE_DIR pointing at a dead tmp.

    A leaked reload is what let a later test's prune_details wipe the real
    admrule cache in one session; this guards that the fixture undoes it.
    """
    import admrules.cache as cache
    from admrules.config import ADMRULE_CACHE_DIR

    assert cache.CACHE_DIR == ADMRULE_CACHE_DIR
