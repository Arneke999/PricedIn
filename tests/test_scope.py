import json

import pytest

from pricedin.normalize import scope


def submissions(sic="7370", filings=(), cik=1) -> bytes:
    """filings: (form, filing date) pairs."""
    recent = {"form": [f for f, _ in filings], "filingDate": [d for _, d in filings]}
    return json.dumps(
        {"cik": str(cik), "sic": sic, "sicDescription": "Test", "filings": {"recent": recent}}
    ).encode()


def test_bank_sic_is_excluded_with_a_message():
    result = scope.classify(submissions(sic="6022"))
    assert (result.status, result.category) == ("excluded", "bank")
    assert "banks" in result.message


@pytest.mark.parametrize("sic", ["6324", "6411", "7370"])
def test_health_plans_brokers_and_operating_companies_are_covered(sic):
    result = scope.classify(submissions(sic=sic))
    assert (result.status, result.category, result.message) == ("covered", None, None)


def test_missing_sic_is_covered():
    result = scope.classify(submissions(sic=""))
    assert result.sic is None
    assert result.status == "covered"


def test_include_override_beats_sic(monkeypatch):
    monkeypatch.setitem(scope.OVERRIDES, 1, ("include", "reports normal operating income"))
    assert scope.classify(submissions(sic="6798")).status == "covered"


def test_exclude_override_beats_sic(monkeypatch):
    monkeypatch.setitem(scope.OVERRIDES, 1, ("exclude", "holdco"))
    result = scope.classify(submissions(sic="7370"))
    assert (result.status, result.category) == ("excluded", "holdco")


def test_overrides_are_well_formed():
    for action, reason in scope.OVERRIDES.values():
        assert action in ("exclude", "include")
        assert action == "include" or reason in scope.MESSAGES


def test_20f_filer_is_foreign():
    body = submissions(filings=[("6-K", "2026-09-01"), ("20-F", "2026-04-15")])
    result = scope.classify(body)
    assert (result.status, result.category) == ("excluded", "foreign filer")


def test_40f_amendment_counts_as_foreign():
    assert scope.classify(submissions(filings=[("40-F/A", "2026-05-01")])).status == "excluded"


def test_10k_in_window_means_not_foreign():
    body = submissions(filings=[("10-K", "2026-02-01"), ("20-F", "2025-04-15")])
    assert scope.classify(body).status == "covered"


def test_20f_outside_window_is_ignored():
    # Switched to 10-Q/8-K reporting long ago; the old 20-F is outside the 3-year window.
    body = submissions(filings=[("10-Q", "2026-08-01"), ("20-F", "2019-04-15")])
    assert scope.classify(body).status == "covered"
