"""Validation: turn mapped text columns into typed data and log every problem as an Issue.

Rows with an 'error' issue are dropped from the clean output; 'warning' rows are kept (and corrected where the
rule says so). Nothing stops at the first problem - all issues are collected.
"""
from __future__ import annotations

import pandas as pd

from .config import Config
from .io import ROW
from .issues import IssueLog
from .schema import DATASETS


def _coerce(df: pd.DataFrame, dataset: str, config: Config, log: IssueLog) -> pd.DataFrame:
    """Parse numeric and date columns. Blank required -> missing_required_value; unreadable -> non_numeric/unparseable."""
    out = df.copy()
    for f in DATASETS[dataset]:
        if f.name not in out:
            continue
        raw = out[f.name]
        blank = raw == ""
        if f.required:
            for i in out.index[blank]:
                log.add(dataset, "missing_required_value", f"required value '{f.name}' is blank",
                        row=int(out.at[i, ROW]), column=f.name)
        if f.dtype == "float":
            text = raw
            if config.formats.decimal == ",":
                text = text.str.replace(".", "", regex=False).str.replace(",", ".", regex=False)
            num = pd.to_numeric(text, errors="coerce")
            for i in out.index[num.isna() & ~blank]:
                log.add(dataset, "non_numeric_value", f"'{raw[i]}' is not a number",
                        row=int(out.at[i, ROW]), column=f.name, value=raw[i])
            out[f.name] = num
        elif f.dtype == "date":
            fmt = config.formats.date or "ISO8601"
            dates = pd.to_datetime(raw.where(~blank), format=fmt, errors="coerce")
            if config.formats.date:  # real Excel date cells arrive as ISO text whatever pattern the team uses
                retry = dates.isna() & ~blank
                dates[retry] = pd.to_datetime(raw[retry], format="ISO8601", errors="coerce")
            for i in out.index[dates.isna() & ~blank]:
                hint = "" if config.formats.date else " (set formats.date in the config if dates are not YYYY-MM-DD)"
                log.add(dataset, "unparseable_date", f"'{raw[i]}' is not a valid date{hint}",
                        row=int(out.at[i, ROW]), column=f.name, value=raw[i])
            out[f.name] = dates
    return out


def _each(log: IssueLog, df: pd.DataFrame, mask: pd.Series, dataset: str, rule: str, column: str, message) -> None:
    for i in df.index[mask.fillna(False)]:
        log.add(dataset, rule, message(df.loc[i]), row=int(df.at[i, ROW]), column=column, value=df.at[i, column])


def _canonical_labels(df: pd.DataFrame, column: str, dataset: str, log: IssueLog) -> pd.DataFrame:
    """Unify spellings that differ only by case/spacing, using the most common spelling in the file."""
    out = df.copy()
    key = out[column].str.split().str.join(" ").str.casefold()
    spelled = out[column].str.split().str.join(" ")
    canon = spelled.groupby(key).agg(lambda s: s.value_counts().index[0])
    target = key.map(canon)
    for i in out.index[(spelled != target) & (out[column] != "")]:
        log.add(dataset, "inconsistent_region_label",
                f"'{out.at[i, column]}' spelled differently from '{target[i]}'; normalised",
                row=int(out.at[i, ROW]), column=column, value=out.at[i, column])
    out[column] = target.where(out[column] != "", out[column])
    return out


def _duplicates(df: pd.DataFrame, dataset: str, log: IssueLog) -> None:
    dup = df.drop(columns=[ROW]).duplicated(keep="first")
    for i in df.index[dup]:
        log.add(dataset, "exact_duplicate_row", "identical to an earlier row", row=int(df.at[i, ROW]))


def _empty_like(df: pd.DataFrame) -> pd.DataFrame:
    return df.iloc[0:0].copy()


def _finish(df: pd.DataFrame, dataset: str, log: IssueLog) -> pd.DataFrame:
    return df[~df[ROW].isin(log.error_rows(dataset))].reset_index(drop=True)


def _has_missing_columns(dataset: str, df: pd.DataFrame) -> bool:
    return any(f.required and f.name not in df for f in DATASETS[dataset])


def validate_activity(df: pd.DataFrame, config: Config, log: IssueLog, *,
                      fundraiser_ids: set[str] | None = None, location_ids: set[str] | None = None) -> pd.DataFrame:
    ds, v = "activity", config.validation
    if _has_missing_columns(ds, df):
        return _empty_like(df)
    _duplicates(df, ds, log)  # on the raw text, before anything is normalised
    d = _coerce(df, ds, config, log)
    d = _canonical_labels(d, "region", ds, log)

    for col in ["doors_knocked", "conversations", "pledges", "total_monthly_value_eur"]:
        if col in d:
            _each(log, d, d[col] < 0, ds, "negative_value", col, lambda r, c=col: f"{c} is negative")
    h, p = d["active_hours"], d["pledges"]
    _each(log, d, h < 0, ds, "negative_hours", "active_hours", lambda r: "active_hours is negative")
    activity = (p > 0)
    for col in ["conversations", "doors_knocked"]:
        if col in d:
            activity = activity | (d[col] > 0)
    _each(log, d, (h == 0) & activity, ds, "zero_hours_with_activity", "active_hours",
          lambda r: "active_hours is 0 but activity was recorded")
    if "conversations" in d and "doors_knocked" in d:
        _each(log, d, d["conversations"] > d["doors_knocked"], ds, "conversations_gt_doors", "conversations",
              lambda r: f"{r['conversations']:g} conversations > {r['doors_knocked']:g} doors knocked")
    if "conversations" in d:
        _each(log, d, p > d["conversations"], ds, "pledges_gt_conversations", "pledges",
              lambda r: f"{r['pledges']:g} pledges > {r['conversations']:g} conversations")
    _each(log, d, h > v.max_hours_per_row, ds, "implausible_hours", "active_hours",
          lambda r: f"{r['active_hours']:g} h exceeds the limit of {v.max_hours_per_row:g} h")
    if "total_monthly_value_eur" in d:
        per = d["total_monthly_value_eur"] / p.where(p > 0)
        _each(log, d, per > v.max_value_per_pledge, ds, "implausible_value_per_pledge", "total_monthly_value_eur",
              lambda r: f"{r['total_monthly_value_eur'] / r['pledges']:.0f} EUR per pledge exceeds {v.max_value_per_pledge:g}")
    if "date" in d:
        dates = d["date"]
        if v.expected_date_range:
            lo, hi = (pd.Timestamp(x) for x in v.expected_date_range)
            where = f"outside {v.expected_date_range[0]} to {v.expected_date_range[1]}"
        elif dates.notna().any():
            mid, span = dates.median(), pd.Timedelta(days=v.date_window_days)
            lo, hi = mid - span, mid + span
            where = f"more than {v.date_window_days} days from the median date {mid:%Y-%m-%d}"
        else:  # no readable date at all: the unparseable_date issues already say so, and there is no "typical" date
            lo = hi = None
        if lo is not None:
            _each(log, d, (dates < lo) | (dates > hi), ds, "date_out_of_range", "date",
                  lambda r: f"{r['date']:%Y-%m-%d} is {where}")
    for col, known, rule in [("fundraiser_id", fundraiser_ids, "unknown_fundraiser_id"),
                             ("location_id", location_ids, "unknown_location_id")]:
        if known is not None and col in d:
            _each(log, d, (d[col] != "") & ~d[col].isin(known), ds, rule, col,
                  lambda r, c=col: f"{r[c]} is not in the {c.replace('_id', '')} list")
    return _finish(d, ds, log)


def validate_locations(df: pd.DataFrame, config: Config, log: IssueLog) -> pd.DataFrame:
    ds = "locations"
    if _has_missing_columns(ds, df):
        return _empty_like(df)
    _duplicates(df, ds, log)
    d = _coerce(df, ds, config, log)
    _each(log, d, d["target_pph"] < 0, ds, "negative_value", "target_pph", lambda r: "target_pph is negative")
    already = log.error_rows(ds)  # exact copies were reported above; this catches the same ID with other details
    repeats = (d["location_id"] != "") & d["location_id"].duplicated(keep="first") & ~d[ROW].isin(already)
    _each(log, d, repeats, ds, "duplicate_location_id", "location_id",
          lambda r: f"{r['location_id']} is already in the list; this row is left out and the first one is used")
    return _finish(d, ds, log)


def validate_location_weekly(df: pd.DataFrame, config: Config, log: IssueLog, *,
                             location_ids: set[str] | None = None) -> pd.DataFrame:
    ds, v = "location_weekly", config.validation
    if _has_missing_columns(ds, df):
        return _empty_like(df)
    _duplicates(df, ds, log)
    d = _coerce(df, ds, config, log)
    for col in ["pledges", "target_pph"]:
        _each(log, d, d[col] < 0, ds, "negative_value", col, lambda r, c=col: f"{c} is negative")
    _each(log, d, d["hours"] < 0, ds, "negative_hours", "hours", lambda r: "hours is negative")
    _each(log, d, (d["hours"] == 0) & (d["pledges"] > 0), ds, "zero_hours_with_activity", "hours",
          lambda r: "hours is 0 but pledges were recorded")
    true_pph = d["pledges"] / d["hours"].where(d["hours"] > 0)
    if "achieved_pph" in d:
        off = (d["achieved_pph"] - true_pph).abs() > v.achieved_pph_tolerance
        _each(log, d, off, ds, "achieved_pph_mismatch", "achieved_pph",
              lambda r: f"supplied {r['achieved_pph']:g} but pledges / hours = {r['pledges'] / r['hours']:.2f}; recomputed")
    d["achieved_pph"] = true_pph  # always derived from the counts, so it cannot disagree with them
    if location_ids is not None:
        _each(log, d, ~d["location_id"].isin(location_ids), ds, "unknown_location_id", "location_id",
              lambda r: f"{r['location_id']} is not in the location list")
    return _finish(d, ds, log)


def validate_fundraisers(df: pd.DataFrame, config: Config, log: IssueLog) -> pd.DataFrame:
    ds = "fundraisers"
    if _has_missing_columns(ds, df):
        return _empty_like(df)
    _duplicates(df, ds, log)
    d = _coerce(df, ds, config, log)
    return _finish(d, ds, log)
