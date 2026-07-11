from datetime import date

from ordinances import detail_failure_allowlist


def test_known_detail_failure_is_expiring_and_error_specific():
    detail_failure_allowlist.load_allowlist.cache_clear()
    error = RuntimeError("invalid 자치법규일련번호=<missing>")

    assert detail_failure_allowlist.is_listed("1164395", today=date(2026, 7, 11))
    assert detail_failure_allowlist.accepted_entry("1164395", error, today=date(2026, 7, 11))
    assert detail_failure_allowlist.is_listed("886588", today=date(2026, 7, 12))
    assert detail_failure_allowlist.accepted_entry("886588", error, today=date(2026, 7, 12))
    assert not detail_failure_allowlist.is_listed("1164395", today=date(2026, 10, 31))
