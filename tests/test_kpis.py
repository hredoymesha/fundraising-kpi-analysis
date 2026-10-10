"""KPI tests. Every expected value below was worked out by hand (arithmetic shown in comments)."""
import math

import pandas as pd
import pytest

from f2f_kpi import (avg_monthly_donation, compute_activity_kpis, compute_location_kpis, conversation_rate,
                     pledge_rate, pledges_per_hour, target_attainment)
from f2f_kpi.kpis import attach_location_targets


# ---- the five KPIs on plain numbers --------------------------------------------------------------

def test_conversation_rate():
    assert conversation_rate(30, 100) == pytest.approx(0.30)  # 30 / 100


def test_pledge_rate():
    assert pledge_rate(15, 60) == pytest.approx(0.25)  # 15 / 60


def test_pledges_per_hour():
    assert pledges_per_hour(18, 6) == pytest.approx(3.0)  # 18 / 6


def test_target_attainment():
    assert target_attainment(1.5, 2.0) == pytest.approx(0.75)  # 1.5 / 2.0
    assert target_attainment(2.5, 2.0) == pytest.approx(1.25)


def test_avg_monthly_donation():
    assert avg_monthly_donation(540, 18) == pytest.approx(30.0)  # 540 / 18


@pytest.mark.parametrize("fn", [conversation_rate, pledge_rate, pledges_per_hour, target_attainment,
                                avg_monthly_donation])
def test_zero_denominator_is_nan_not_zero(fn):
    assert math.isnan(fn(5, 0))


def test_series_input_and_zero_denominator_inside_series():
    got = pledge_rate(pd.Series([10.0, 5.0]), pd.Series([40.0, 0.0]))
    assert got[0] == pytest.approx(0.25)  # 10 / 40
    assert math.isnan(got[1])


# ---- grouped KPIs are ratios of sums -------------------------------------------------------------

@pytest.fixture
def activity():
    return pd.DataFrame({
        "region": ["A", "A", "B"],
        "doors_knocked": [100, 300, 200],
        "conversations": [30, 60, 40],
        "pledges": [6, 12, 4],
        "total_monthly_value_eur": [90, 180, 80],
        "active_hours": [4, 8, 5],
    })


def test_region_kpis_by_hand(activity):
    out = compute_activity_kpis(activity, ["region"]).set_index("region")
    # Region A: doors 400, conversations 90, pledges 18, value 270, hours 12
    a = out.loc["A"]
    assert a["doors_knocked"] == 400 and a["pledges"] == 18 and a["active_hours"] == 12
    assert a["conversation_rate"] == pytest.approx(90 / 400)  # 0.225  (NOT the mean of 0.30 and 0.20 = 0.25)
    assert a["pledge_rate"] == pytest.approx(18 / 90)  # 0.20
    assert a["pledges_per_hour"] == pytest.approx(18 / 12)  # 1.5
    assert a["avg_monthly_donation_eur"] == pytest.approx(270 / 18)  # 15.0
    # Region B: 40/200 = 0.2, 4/40 = 0.1, 4/5 = 0.8, 80/4 = 20
    b = out.loc["B"]
    assert (b["conversation_rate"], b["pledge_rate"], b["pledges_per_hour"], b["avg_monthly_donation_eur"]) == \
        pytest.approx((0.2, 0.1, 0.8, 20.0))


def test_overall_kpis_by_hand(activity):
    out = compute_activity_kpis(activity).iloc[0]
    # doors 600, conversations 130, pledges 22, value 350, hours 17
    assert out["conversation_rate"] == pytest.approx(130 / 600)  # 0.216667
    assert out["pledge_rate"] == pytest.approx(22 / 130)  # 0.169231
    assert out["pledges_per_hour"] == pytest.approx(22 / 17)  # 1.294118
    assert out["avg_monthly_donation_eur"] == pytest.approx(350 / 22)  # 15.909091


def test_regions_sorted_by_pledges_desc(activity):
    assert list(compute_activity_kpis(activity, ["region"])["region"]) == ["A", "B"]  # 18 pledges, then 4


def test_group_with_no_doors_gives_nan_conversation_rate():
    df = pd.DataFrame({"region": ["A"], "doors_knocked": [0], "conversations": [0], "pledges": [0],
                       "total_monthly_value_eur": [0], "active_hours": [3]})
    out = compute_activity_kpis(df, ["region"]).iloc[0]
    assert math.isnan(out["conversation_rate"]) and math.isnan(out["pledge_rate"])
    assert out["pledges_per_hour"] == 0  # 0 / 3 is a real zero, not missing


def test_kpis_without_their_input_columns_are_skipped_and_reported():
    df = pd.DataFrame({"region": ["A"], "pledges": [10], "active_hours": [5]})
    out = compute_activity_kpis(df, ["region"])
    assert out.loc[0, "pledges_per_hour"] == pytest.approx(2.0)  # 10 / 5
    assert "conversation_rate" not in out and "avg_monthly_donation_eur" not in out
    assert "conversation_rate" in out.attrs["skipped_kpis"]
    assert "avg_monthly_donation_eur" in out.attrs["skipped_kpis"]


# ---- location KPIs: target attainment --------------------------------------------------------------

@pytest.fixture
def weekly():
    return pd.DataFrame({
        "location_id": ["L1", "L1", "L2"],
        "pledges": [10, 20, 6],
        "hours": [5, 15, 10],
        "target_pph": [3.0, 1.0, 1.0],
        "avg_monthly_donation_eur": [20.0, 10.0, 15.0],
    })


def test_location_target_attainment_by_hand(weekly):
    out = compute_location_kpis(weekly, ["location_id"]).set_index("location_id")
    # L1: pledges 30, hours 20 -> achieved 30/20 = 1.5
    #     target weighted by hours = (3.0*5 + 1.0*15) / 20 = 1.5 (a plain mean of targets, 2.0, would be wrong)
    l1 = out.loc["L1"]
    assert l1["achieved_pph"] == pytest.approx(1.5)
    assert l1["target_pph"] == pytest.approx(1.5)
    assert l1["target_attainment"] == pytest.approx(1.0)
    assert l1["productivity_gap"] == pytest.approx(0.0)
    # L1 value = 10*20 + 20*10 = 400; 400 / 30 pledges
    assert l1["avg_monthly_donation_eur"] == pytest.approx(400 / 30)  # 13.3333
    # L2: achieved 6/10 = 0.6, target 1.0 -> attainment 0.6, gap -0.4
    l2 = out.loc["L2"]
    assert l2["target_attainment"] == pytest.approx(0.6)
    assert l2["productivity_gap"] == pytest.approx(-0.4)


def test_location_with_no_target_has_nan_attainment():
    df = pd.DataFrame({"location_id": ["L1"], "pledges": [5], "hours": [10], "target_pph": [float("nan")]})
    out = compute_location_kpis(df, ["location_id"]).iloc[0]
    assert out["achieved_pph"] == pytest.approx(0.5)
    assert math.isnan(out["target_attainment"])


def test_targets_attached_to_shift_rows_from_location_master():
    shifts = pd.DataFrame({"location_id": ["L1", "L1", "L2"], "pledges": [4, 6, 3],
                           "active_hours": [2.0, 3.0, 3.0]})
    master = pd.DataFrame({"location_id": ["L1", "L2"], "target_pph": [2.5, 0.5],
                           "location_label": ["One", "Two"], "location_type": ["Stand", "Fair"]})
    out = compute_location_kpis(attach_location_targets(shifts, master), ["location_id"]).set_index("location_id")
    # L1: 10 pledges / 5 h = 2.0 vs target 2.5 -> 0.8 ; L2: 3 / 3 = 1.0 vs 0.5 -> 2.0
    assert out.loc["L1", "target_attainment"] == pytest.approx(0.8)
    assert out.loc["L2", "target_attainment"] == pytest.approx(2.0)
    assert out.loc["L1", "location_label"] == "One"
