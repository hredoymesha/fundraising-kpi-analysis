"""The five KPIs, plus grouped calculation.

Every KPI is a ratio of *sums*, never an average of row-level rates. A zero or missing denominator gives
NaN (not 0), so an empty region is not mistaken for a region that performed badly.
"""
from __future__ import annotations

import math

import pandas as pd

# --- the five KPIs (work on plain numbers or pandas Series) -----------------------------------------


def _div(numerator, denominator):
    if isinstance(denominator, pd.Series):
        return numerator / denominator.where(denominator != 0)
    if denominator is None or (isinstance(denominator, float) and math.isnan(denominator)) or denominator == 0:
        return math.nan
    return numerator / denominator


def conversation_rate(conversations, doors_knocked):
    """conversations / doors_knocked"""
    return _div(conversations, doors_knocked)


def pledge_rate(pledges, conversations):
    """pledges / conversations"""
    return _div(pledges, conversations)


def pledges_per_hour(pledges, active_hours):
    """pledges / active_hours"""
    return _div(pledges, active_hours)


def target_attainment(achieved_pph, target_pph):
    """achieved_pph / target_pph  (1.0 = exactly on target)"""
    return _div(achieved_pph, target_pph)


def avg_monthly_donation(total_monthly_value, pledges):
    """total monthly value / pledges"""
    return _div(total_monthly_value, pledges)


# --- grouped calculation -----------------------------------------------------------------------------


def _group(df: pd.DataFrame, by: list[str] | None):
    if by:
        return df.groupby(by, dropna=False, sort=False)
    return df.groupby(lambda _: "all", sort=False)


def _sum(grouped, column: str) -> pd.Series:
    return grouped[column].sum(min_count=1)


def compute_activity_kpis(activity: pd.DataFrame, by: list[str] | None = None) -> pd.DataFrame:
    """Totals and KPIs per group (e.g. by=['region']); by=None gives one row for the whole file.

    KPIs whose input columns are absent are left out and listed in result.attrs['skipped_kpis'].
    Sorted by pledges, highest first.
    """
    g = _group(activity, by)
    out = pd.DataFrame({"shifts": g.size()})
    for col in ["doors_knocked", "conversations", "pledges", "total_monthly_value_eur", "active_hours"]:
        if col in activity:
            out[col] = _sum(g, col)
    skipped: dict[str, str] = {}

    def needs(kpi: str, *cols: str) -> bool:
        missing = [c for c in cols if c not in out]
        if missing:
            skipped[kpi] = f"needs column(s): {', '.join(missing)}"
        return not missing

    if needs("conversation_rate", "conversations", "doors_knocked"):
        out["conversation_rate"] = conversation_rate(out["conversations"], out["doors_knocked"])
    if needs("pledge_rate", "pledges", "conversations"):
        out["pledge_rate"] = pledge_rate(out["pledges"], out["conversations"])
    if needs("pledges_per_hour", "pledges", "active_hours"):
        out["pledges_per_hour"] = pledges_per_hour(out["pledges"], out["active_hours"])
    if needs("avg_monthly_donation_eur", "total_monthly_value_eur", "pledges"):
        out["avg_monthly_donation_eur"] = avg_monthly_donation(out["total_monthly_value_eur"], out["pledges"])
    # target attainment needs a target; see compute_location_kpis
    skipped["target_attainment"] = "calculated per location (needs target_pph); see compute_location_kpis"

    if by:
        out = out.reset_index()
    else:
        out = out.reset_index(drop=True)
    if "pledges" in out:
        out = out.sort_values("pledges", ascending=False, kind="stable").reset_index(drop=True)
    out.attrs["skipped_kpis"] = skipped
    return out


def attach_location_targets(activity: pd.DataFrame, locations: pd.DataFrame) -> pd.DataFrame:
    """Add target_pph (and label/type) from the location master to shift-level rows; adds 'hours' alias."""
    master = locations.drop_duplicates("location_id")
    keep = ["location_id"] + [c for c in ["target_pph", "location_label", "location_type"] if c in master]
    merged = activity.merge(master[keep], on="location_id", how="left")
    merged["hours"] = merged["active_hours"]
    return merged


def compute_location_kpis(rows: pd.DataFrame, by: list[str] | None = None) -> pd.DataFrame:
    """Per-location (or any grouping) pledges, hours, achieved vs target PPH and target attainment.

    rows needs: pledges, hours, target_pph. Optional: total_monthly_value_eur, or avg_monthly_donation_eur
    (then value = avg x pledges).

    achieved_pph = sum(pledges) / sum(hours)
    target_pph   = hours-weighted mean of target_pph, i.e. sum(target x hours) / sum(hours)
    target_attainment = achieved_pph / target_pph
    """
    by = ["location_id"] if by is None else by  # by=[] gives one row for everything
    df = rows.copy()
    df["_target_hours"] = df["target_pph"] * df["hours"]
    df["_hours_with_target"] = df["hours"].where(df["target_pph"].notna())
    if "total_monthly_value_eur" not in df and "avg_monthly_donation_eur" in df:
        df["total_monthly_value_eur"] = df["avg_monthly_donation_eur"] * df["pledges"]

    g = _group(df, by)
    out = pd.DataFrame({"pledges": _sum(g, "pledges"), "hours": _sum(g, "hours")})
    out["target_pph"] = _div(_sum(g, "_target_hours"), _sum(g, "_hours_with_target"))
    out["achieved_pph"] = pledges_per_hour(out["pledges"], out["hours"])
    out["target_attainment"] = target_attainment(out["achieved_pph"], out["target_pph"])
    out["productivity_gap"] = out["achieved_pph"] - out["target_pph"]
    if "total_monthly_value_eur" in df:
        out["total_monthly_value_eur"] = _sum(g, "total_monthly_value_eur")
        out["avg_monthly_donation_eur"] = avg_monthly_donation(out["total_monthly_value_eur"], out["pledges"])
    out = out.reset_index(drop=not by)
    for col in ["location_label", "location_type"]:  # descriptive columns not in `by`: first value per group
        if by and col in df and col not in by:
            out[col] = out[by[0]].map(df.groupby(by[0])[col].first()) if len(by) == 1 else None
    return out.sort_values("target_attainment", ascending=False, na_position="last", kind="stable").reset_index(drop=True)


def compute_dimension_kpis(activity: pd.DataFrame, dimensions: list[str]) -> pd.DataFrame:
    """Activity KPIs for each value of each dimension, stacked into one table (dimension, value, ...KPIs).
    Dimensions that are not in the data are skipped. Within a dimension, most pledges first."""
    frames = []
    for dim in dimensions:
        if dim not in activity.columns:
            continue
        part = compute_activity_kpis(activity[activity[dim] != ""], [dim]).rename(columns={dim: "value"})
        part.insert(0, "dimension", dim)
        frames.append(part)
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)
