from datetime import date

import pytest

from synapse.domain import inventory as inv

D0 = date(2026, 10, 31)


def test_z_for_service_level():
    assert inv.z_for_service_level(0.95) == pytest.approx(1.6449, abs=1e-4)
    assert inv.z_for_service_level(0.5) == pytest.approx(0.0)
    for bad in (0.4, 1.0, 1.2):
        with pytest.raises(ValueError):
            inv.z_for_service_level(bad)


def test_safety_stock_combines_demand_and_lead_time_uncertainty():
    # z * sqrt(L*sd_D^2 + D^2*sd_L^2) = 1.645 * sqrt(4*100^2 + 1000^2*0.5^2) = 1.645 * sqrt(290000)
    assert inv.safety_stock(1.645, 4, 100, 1000, 0.5) == pytest.approx(885.85, abs=0.01)


def test_safety_stock_without_uncertainty_is_zero():
    assert inv.safety_stock(1.645, 3, 0, 1000, 0) == 0


def test_safety_stock_rejects_negative_inputs():
    with pytest.raises(ValueError, match="lead_time_sd"):
        inv.safety_stock(1.645, 3, 10, 100, -1)


def test_eoq():
    assert inv.eoq(10_000, 50, 2) == pytest.approx(707.11, abs=0.01)
    with pytest.raises(ValueError):
        inv.eoq(10_000, 50, 0)


def test_reorder_point():
    assert inv.reorder_point(100, 3, 50) == 350


def test_series_stats():
    s = inv.series_stats([2, 4, 4, 4, 5, 5, 7, 9])
    assert (s.mean, s.n) == (5, 8)
    assert s.sd == pytest.approx(2.138, abs=1e-3)
    with pytest.raises(ValueError):
        inv.series_stats([1])


def test_daily_series_fills_missing_days_and_sums_duplicates():
    postings = [(date(2026, 10, 1), 5), (date(2026, 10, 1), 2), (date(2026, 10, 3), 4), (date(2026, 9, 1), 99)]
    assert inv.daily_series(postings, date(2026, 10, 1), date(2026, 10, 3)) == [7, 0, 4]
    with pytest.raises(ValueError):
        inv.daily_series([], date(2026, 10, 3), date(2026, 10, 1))


def test_projection_and_breach():
    receipts = {date(2026, 11, 2): 300}
    proj = inv.project_stock(250, receipts, 100, D0, 4)
    assert [p.closing for p in proj] == [150, 350, 250, 150]
    assert proj[1].receipts == 300
    assert inv.first_breach(proj, 200).day == date(2026, 11, 1)
    assert inv.first_breach(proj, 100) is None
    assert inv.shortfall(proj, 200) == 50
    assert inv.shortfall(proj, 100) == 0
    assert inv.shortfall([], 100) == 0
