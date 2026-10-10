"""Plotly figures: they should draw exactly the numbers the engine produced, and say nothing when there is nothing to draw."""
import pytest

pytest.importorskip("plotly")

from f2f_kpi import analyse, config_from_dict
from f2f_kpi.io import read_bytes

import figures

# weeks: 01-08 PPH 2.0 (8/4), 01-15 PPH 1.0 (10/10), 01-22 quiet, 01-29 2.0 (6/3), 02-05 2.0 (12/6)
CSV = (b"date,region,doors_knocked,conversations,pledges,active_hours\n"
       b"2024-01-08,North,100,40,8,4\n2024-01-15,South,200,50,10,10\n"
       b"2024-01-29,North,100,20,6,3\n2024-02-05,South,100,30,12,6\n")


@pytest.fixture
def result():
    return analyse(config_from_dict({}, require_activity=False), {"activity": read_bytes(CSV, "a.csv")})


def test_pph_by_region_bars_match_the_engine(result):
    fig = figures.pph_by_region(result.by_region)
    bar = fig.data[0]
    # North: 14 pledges / 7 h = 2.0 ; South: 22 / 16 = 1.375 ; bars are sorted so the best region is on top
    assert dict(zip(bar.y, bar.x)) == pytest.approx({"North": 2.0, "South": 1.375})
    assert list(bar.y)[-1] == "North" and bar.orientation == "h"
    assert fig.layout.title.text == "Pledges per hour by region"


def test_rates_by_region_has_one_series_per_rate(result):
    fig = figures.rates_by_region(result.by_region)
    assert [t.name for t in fig.data] == ["Conversation rate", "Pledge rate"]
    north = list(fig.data[0].x).index("North")
    assert fig.data[0].y[north] == pytest.approx(60 / 200)  # North conversations 40 + 20 over doors 100 + 100
    assert fig.data[1].y[north] == pytest.approx(14 / 60)  # pledges 14 over conversations 60


def test_trend_figures_use_the_trend_table(result):
    pph = figures.trend_pph(result.trends, "week")
    assert [t.name for t in pph.data] == ["Each week", "Last 4 weeks"]
    assert list(pph.data[0].y)[:2] == pytest.approx([2.0, 1.0])
    # rolling needs four weeks: the first four weeks are 8+10+0+6 = 24 pledges over 4+10+0+3 = 17 hours
    assert pph.data[1].y[3] == pytest.approx(24 / 17)
    pledges = figures.trend_pledges(result.trends, "week")
    assert list(pledges.data[0].y)[:2] == [8, 10] and "week" in pledges.layout.title.text


def test_month_wording_follows_the_period():
    cfg = config_from_dict({"report": {"trend_period": "month"}}, require_activity=False)
    r = analyse(cfg, {"activity": read_bytes(CSV, "a.csv")})
    assert figures.trend_pph(r.trends, "month").layout.title.text == "Pledges per hour, by month"


def test_figures_return_nothing_when_the_data_is_not_there():
    r = analyse(config_from_dict({}, require_activity=False),
                {"activity": read_bytes(b"region,pledges,active_hours\nA,4,2\n", "a.csv")})
    assert figures.pph_by_region(r.by_region) is not None
    assert figures.rates_by_region(r.by_region) is None  # no doors / conversations columns
    assert figures.trend_pph(r.trends) is None and figures.trend_pledges(r.trends) is None  # no dates
    assert figures.pph_by_region(None) is None and figures.trend_pph(None) is None


def test_single_period_has_no_rolling_line():
    r = analyse(config_from_dict({}, require_activity=False),
                {"activity": read_bytes(b"date,region,pledges,active_hours\n2024-01-08,A,4,2\n", "a.csv")})
    assert [t.name for t in figures.trend_pph(r.trends).data] == ["Each week"]


def test_figures_survive_a_json_round_trip(result):
    import plotly.io as pio
    for fig in (figures.pph_by_region(result.by_region), figures.rates_by_region(result.by_region),
                figures.trend_pph(result.trends), figures.trend_pledges(result.trends)):
        assert pio.from_json(pio.to_json(fig)).layout.title.text == fig.layout.title.text


def test_a_single_period_is_labelled_by_its_date_not_in_milliseconds():
    """Found in a real browser: one week of data gave ticks like '23:59:59.999 Jan 7, 2024'."""
    import pandas as pd
    r = analyse(config_from_dict({}, require_activity=False),
                {"activity": read_bytes(b"date,region,pledges,active_hours\n2024-01-09,A,5,4.5\n", "a.csv")})
    start = pd.Timestamp("2024-01-08")  # the Monday of that week
    for fig in (figures.trend_pph(r.trends), figures.trend_pledges(r.trends)):
        assert list(fig.layout.xaxis.tickvals) == [start] and fig.layout.xaxis.tickformat == "%d %b %Y"
        lo, hi = fig.layout.xaxis.range
        assert pd.Timestamp(lo) < start < pd.Timestamp(hi)
        assert (pd.Timestamp(hi) - pd.Timestamp(lo)).days >= 7  # a visible stretch of time, not a sliver
    assert figures.trend_pledges(r.trends).data[0].width == int(7 * 0.8 * 24 * 3600 * 1000)


def test_many_periods_keep_plotly_s_own_ticks(result):
    # five weeks in the fixture's date range is more than FEW_PERIODS: no hand-made tick list
    many = result.trends.copy()
    assert len(many) > figures.FEW_PERIODS
    assert figures.trend_pph(many).layout.xaxis.tickvals is None


def test_region_names_from_the_file_cannot_become_chart_markup():
    """Found in a real browser: a region named '<a href=...>' turned into a clickable link inside the chart."""
    hostile = '<a href="https://evil.example/login">Metro</a>'
    csv = ("region,pledges,active_hours,doors_knocked,conversations\n"
           + '"' + hostile.replace('"', '""') + '",8,4,100,40\nSouth,6,3,100,20\n').encode()
    r = analyse(config_from_dict({}, require_activity=False), {"activity": read_bytes(csv, "a.csv")})
    for labels in (list(figures.pph_by_region(r.by_region).data[0].y), list(figures.rates_by_region(r.by_region).data[0].x)):
        assert not any("<" in label or ">" in label for label in labels)
        assert any(label.startswith("&lt;a href=") for label in labels)  # Plotly shows this as the literal text
