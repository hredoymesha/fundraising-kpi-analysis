"""Period-over-period trends. Same rule as the other KPIs: rates are ratios of sums, so a quiet week
counts for what it is instead of being averaged in as if it were a full one."""
from __future__ import annotations

import pandas as pd

from .kpis import avg_monthly_donation, conversation_rate, pledge_rate, pledges_per_hour

ROLLING_PERIODS = 4


def _label(period: pd.Period, kind: str) -> str:
    if kind == "month":
        return f"{period.start_time:%Y-%m}"
    iso = period.start_time.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def compute_trends(activity: pd.DataFrame, period: str = "week") -> pd.DataFrame:
    """One row per calendar week (Monday start) or month, including quiet periods with no rows.

    Columns: period, period_start, shifts, the summed counts, the four activity KPIs,
    pledges_change_pct and pph_change_pct (against the previous period; blank if that period had no data),
    and pph_rolling_4 (pledges / hours over the last four periods, blank until four periods exist).
    Rows without a usable date are left out.
    """
    if period not in ("week", "month"):
        raise ValueError("period must be 'week' or 'month'")
    if "date" not in activity.columns:
        return pd.DataFrame()
    df = activity[activity["date"].notna()]
    if df.empty:
        return pd.DataFrame()
    freq = "W-SUN" if period == "week" else "M"
    periods = df["date"].dt.to_period(freq)
    sums = [c for c in ["doors_knocked", "conversations", "pledges", "total_monthly_value_eur", "active_hours"]
            if c in df.columns]
    grouped = df.groupby(periods)
    out = grouped[sums].sum(min_count=1)
    out.insert(0, "shifts", grouped.size())
    full = pd.period_range(out.index.min(), out.index.max(), freq=freq)
    out = out.reindex(full)
    out["shifts"] = out["shifts"].fillna(0).astype(int)

    if {"conversations", "doors_knocked"} <= set(out):
        out["conversation_rate"] = conversation_rate(out["conversations"], out["doors_knocked"])
    if {"pledges", "conversations"} <= set(out):
        out["pledge_rate"] = pledge_rate(out["pledges"], out["conversations"])
    if {"pledges", "active_hours"} <= set(out):
        out["pledges_per_hour"] = pledges_per_hour(out["pledges"], out["active_hours"])
        roll = out[["pledges", "active_hours"]].fillna(0).rolling(ROLLING_PERIODS, min_periods=ROLLING_PERIODS).sum()
        out["pph_rolling_4"] = pledges_per_hour(roll["pledges"], roll["active_hours"])
        prev = out["pledges_per_hour"].shift(1)
        out["pph_change_pct"] = (out["pledges_per_hour"] - prev) / prev.where(prev > 0)
    if "pledges" in out:
        prev = out["pledges"].shift(1)
        out["pledges_change_pct"] = (out["pledges"] - prev) / prev.where(prev > 0)
    if {"total_monthly_value_eur", "pledges"} <= set(out):
        out["avg_monthly_donation_eur"] = avg_monthly_donation(out["total_monthly_value_eur"], out["pledges"])

    out.insert(0, "period_start", [p.start_time.normalize() for p in out.index])
    out.insert(0, "period", [_label(p, period) for p in out.index])
    return out.reset_index(drop=True)
